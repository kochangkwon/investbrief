"""아카이브 기반 테마 자동 발굴 — 누적 뉴스/공시에서 AI가 테마 감지"""
from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import timedelta
from typing import Any, Optional

import anthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.stock_search import search_stocks
from app.config import settings
from app.database import async_session
from app.models.brief import DailyBrief
from app.services import ai_verifier, telegram_service
from app.services.stock_name_rules import GROUP_PREFIX_NAMES, STOPWORDS
from app.utils.timezone import now_kst_naive, today_kst

logger = logging.getLogger(__name__)

STOCK_NAME_PATTERN = re.compile(r"([가-힣][가-힣A-Za-z0-9]{1,14})")


# ── 시장 주목 검증 게이트 (권고 3) ────────────────────────────────────────
# 공통 호출/파싱은 ai_verifier.verify_with_claude로 위임. 여기서는 프롬프트만 보유.

_ATTENTION_PROMPT_TEMPLATE = """당신은 한국 주식 시장 분석 전문가입니다.

종목 "{stock_name}"이 최근 {days}일간 뉴스에 {mention_count}회 등장했습니다.
({unique_days}일에 걸쳐 분산 언급)

뉴스 제목 샘플:
{sample_titles}

이 빈도가 **특정 이슈/테마로 인한 시장 주목**인지,
아니면 **단순 시장 전반 뉴스에 자주 등장하는 일반 대형주**인지 판정하세요.

판정 기준:
- **YES**: 특정 호재/모멘텀/실적/수주/정책 이슈로 부각된 종목
- **NO**: 시총 1-2위 시장 전반 뉴스 빈출 종목 (예: 삼성전자, SK하이닉스가 단순 시황 뉴스에 자주 등장)
- **NO**: 부정적 이슈(상폐, 사고, 사기 등)로 자주 언급되는 종목
- 애매하면 보수적으로 NO

출력 형식 (정확히 지켜주세요):
VERDICT: YES
REASON: (1줄 근거)

또는:

VERDICT: NO
REASON: (1줄 근거)
"""


# ── 데이터 조회 ──────────────────────────────────────────────────────


async def _get_recent_archives(
    session: AsyncSession, days: int
) -> list[DailyBrief]:
    """최근 N일 브리프 아카이브 조회"""
    cutoff = today_kst() - timedelta(days=days)
    result = await session.execute(
        select(DailyBrief)
        .where(DailyBrief.date >= cutoff)
        .order_by(DailyBrief.date.desc())
    )
    return list(result.scalars().all())


# ── 종목 빈도 분석 ───────────────────────────────────────────────────


async def _analyze_stock_frequency_with_titles(
    days: int = 30,
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """analyze_stock_frequency + 검증 컨텍스트(샘플 제목) 동시 반환.

    내부용 (send_weekly_theme_report 전용).
    공개 API(analyze_stock_frequency)는 그대로 유지.

    권고 2: GROUP_PREFIX_NAMES 차단 + 단음절 차단
    권고 3: 종목별 샘플 뉴스 제목 수집 (검증용)
    """
    async with async_session() as session:
        archives = await _get_recent_archives(session, days)

    if not archives:
        return [], {}

    name_counter: Counter[str] = Counter()
    name_dates: dict[str, set[str]] = {}
    name_titles: dict[str, list[str]] = {}  # 권고 3 검증 컨텍스트

    for brief in archives:
        news_raw = brief.news_raw or []
        date_str = brief.date.isoformat()
        for news in news_raw:
            title = news.get("title", "")
            description = news.get("description", "")
            combined_text = f"{title} {description[:200]}"
            candidates = set(STOCK_NAME_PATTERN.findall(combined_text))
            for candidate in candidates:
                if candidate in STOPWORDS or len(candidate) < 2:
                    continue
                # 권고 2: 그룹명 차단
                if candidate in GROUP_PREFIX_NAMES:
                    continue
                name_counter[candidate] += 1
                name_dates.setdefault(candidate, set()).add(date_str)
                # 권고 3: 검증용 샘플 제목 (최대 3개)
                titles_list = name_titles.setdefault(candidate, [])
                if len(titles_list) < 3:
                    titles_list.append(title)

    top_candidates = name_counter.most_common(50)
    verified: list[dict[str, Any]] = []

    for name, count in top_candidates:
        # 권고 2: 단음절 차단 (동음이의어 위험)
        if len(name) <= 2:
            continue

        try:
            matches = await search_stocks(name, limit=1)
        except Exception:
            continue
        if not matches or matches[0].get("stock_name") != name:
            continue

        verified.append({
            "stock_code": matches[0]["stock_code"],
            "stock_name": name,
            "mention_count": count,
            "unique_days": len(name_dates[name]),
            "period_days": days,
        })

        if len(verified) >= 20:
            break

    verified.sort(key=lambda x: x["mention_count"], reverse=True)
    return verified, name_titles


async def analyze_stock_frequency(days: int = 30) -> list[dict[str, Any]]:
    """공개 API: 빈도 TOP 20만 반환 (외부 호환성 유지)"""
    stocks, _ = await _analyze_stock_frequency_with_titles(days)
    return stocks


# ── 시장 주목 검증 (권고 3) ─────────────────────────────────────────────


async def _verify_market_attention(
    stock_name: str,
    sample_titles: list[str],
    mention_count: int,
    unique_days: int,
    days: int,
) -> tuple[Optional[bool], str]:
    """이 종목이 특별 이슈로 시장 주목 받는지 판정.

    Pass-through: API key 없음 / 예외 / 파싱 실패 → (None, reason).
    빈 샘플은 호출 전 자체 가드.

    Returns: (verdict, reason)
        verdict: True (특별 주목), False (일반 빈출/부정), None (검증 실패)
    """
    if not sample_titles:
        return None, "no sample"

    sample_section = "\n".join(f"- {t}" for t in sample_titles[:3])

    prompt = _ATTENTION_PROMPT_TEMPLATE.format(
        stock_name=stock_name,
        days=days,
        mention_count=mention_count,
        unique_days=unique_days,
        sample_titles=sample_section,
    )

    return await ai_verifier.verify_with_claude(
        prompt,
        log_context=f"attention stock={stock_name}",
    )


async def _verify_top_stocks_attention(
    top_stocks: list[dict[str, Any]],
    sample_news: dict[str, list[str]],
    days: int,
    verify_count: int = 5,
) -> list[dict[str, Any]]:
    """TOP N 종목의 시장 주목 여부를 AI로 검증."""
    if not top_stocks:
        return top_stocks

    enriched = list(top_stocks)

    for stock in enriched[:verify_count]:
        name = stock["stock_name"]
        titles = sample_news.get(name, [])

        verdict, reason = await _verify_market_attention(
            stock_name=name,
            sample_titles=titles,
            mention_count=stock["mention_count"],
            unique_days=stock["unique_days"],
            days=days,
        )
        stock["attention_verified"] = verdict
        stock["attention_reason"] = reason

        logger.info(
            "시장 주목 검증: %s → %s (%s)",
            name,
            "✅ YES" if verdict is True else ("⚠️ NO" if verdict is False else "? UNVERIFIED"),
            reason,
        )

    for stock in enriched[verify_count:]:
        stock["attention_verified"] = None
        stock["attention_reason"] = ""

    return enriched


# ── AI 기반 테마 발굴 ────────────────────────────────────────────────


async def discover_themes(days: int = 30) -> dict[str, Any]:
    """최근 N일 아카이브를 Claude API에 보내 테마 자동 발굴"""
    from app.models.theme import Theme  # 지연 import (순환 방지)

    async with async_session() as session:
        archives = await _get_recent_archives(session, days)
        existing_result = await session.execute(select(Theme.name))
        existing_themes = list(existing_result.scalars().all())

    if not archives:
        return {"error": "분석할 아카이브가 없습니다."}

    if not settings.anthropic_api_key:
        return {"error": "Anthropic API 키가 설정되지 않았습니다."}

    news_titles: list[str] = []
    disclosure_titles: list[str] = []
    ai_summaries: list[str] = []

    for brief in archives:
        date_str = brief.date.isoformat()
        for news in (brief.news_raw or [])[:20]:
            title = news.get("title", "")
            if title:
                news_titles.append(f"[{date_str}] {title}")
        for disc in (brief.disclosures or [])[:5]:
            title = disc.get("title", "") or disc.get("report_nm", "")
            if title:
                disclosure_titles.append(f"[{date_str}] {title}")
        if brief.news_summary:
            ai_summaries.append(f"[{date_str}] {brief.news_summary[:200]}")

    events_text = ""
    try:
        from app.services import event_calendar_service
        events = await event_calendar_service.get_upcoming_events(days=30)
        if events:
            events_lines = []
            for e in events[:15]:
                events_lines.append(
                    f"[{e.get('date', '?')}] {e.get('title', '?')} "
                    f"({e.get('category', '?')})"
                )
            events_text = "\n".join(events_lines)
    except ImportError:
        pass
    except Exception:
        logger.exception("이벤트 캘린더 조회 실패 (선택사항, 무시)")

    prompt = _build_theme_discovery_prompt(
        days, news_titles, disclosure_titles, ai_summaries,
        events_text=events_text,
        existing_themes=existing_themes,
    )

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model=settings.ai_model,
            max_tokens=3500,
            messages=[{"role": "user", "content": prompt}],
        )
        analysis = response.content[0].text
        logger.info(
            "테마 발굴 v2.1: 입력 %d 뉴스 + %d 공시 + %d 요약 + %d 이벤트 → 출력 %d 토큰",
            len(news_titles), len(disclosure_titles), len(ai_summaries),
            len(events_text.split("\n")) if events_text else 0,
            response.usage.output_tokens,
        )
    except anthropic.RateLimitError:
        return {"error": "Claude API 호출 한도 초과 — 잠시 후 재시도해주세요."}
    except Exception:
        logger.exception("테마 발굴 실패")
        return {"error": "테마 발굴 중 오류 발생"}

    return {
        "days": days,
        "archive_count": len(archives),
        "news_count": len(news_titles),
        "disclosure_count": len(disclosure_titles),
        "analysis": analysis,
    }


def _build_theme_discovery_prompt(
    days: int,
    news_titles: list[str],
    disclosure_titles: list[str],
    ai_summaries: list[str],
    events_text: str = "",
    existing_themes: Optional[list[str]] = None,
) -> str:
    """테마 발굴용 Claude 프롬프트 (v2.1 — 9~12개 항목 분석가 리포트).

    events_text가 제공되면 카탈리스트 항목에 활용.
    없으면 카탈리스트 항목은 뉴스/공시에서만 추출 시도.
    existing_themes가 제공되면 의미상 중복 테마 재생성을 회피하도록 지시.
    """
    news_section = "\n".join(news_titles[:600])
    disclosure_section = "\n".join(disclosure_titles[:100])
    summary_section = "\n\n".join(ai_summaries[:30])

    existing_block = ""
    if existing_themes:
        existing_list = "\n".join(f"- {n}" for n in existing_themes)
        existing_block = f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📚 이미 등록된 테마 (중복 발굴 금지 대상):
{existing_list}

"""

    events_block = ""
    if events_text and events_text.strip():
        events_block = f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📅 향후 30일 예정 이벤트 (P1-4 캘린더):
{events_text}

"""

    return f"""당신은 한국 주식 시장 테마 분석 전문가입니다.

다음은 최근 {days}일간 한국 증시 관련 데이터입니다.

이 데이터에서 **부상 중인 투자 테마를 3~4개** 발굴하고,
**깊이 우선** 원칙으로 분석가 리포트 수준의 분석을 제공하세요.
(테마 수보다 분석 깊이가 더 중요)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📰 뉴스 제목 (최근 {days}일):
{news_section}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 DART 공시 제목:
{disclosure_section}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🤖 일일 AI 요약:
{summary_section}

{events_block}{existing_block}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

다음 형식으로 답변하세요:

## 📈 부상 중인 테마 (3~4개)

### 1. [테마명]

**필수 항목** (모든 테마에 작성):
- **부상 근거**: 왜 이 테마가 주목받는지 (2~3줄)
- **핵심 키워드**: 해당 테마를 관통하는 키워드 3~5개 (쉼표 구분)
- **핵심 드라이버**: 정책 / 기술 / 수요 중 무엇이 추진력인지 (1줄)
- **밸류체인 위치**: 상류(소재/장비) / 중류(제조) / 하류(서비스/유통) 중 한국 기업이 강한 위치
- **라이프 스테이지**: 초기 부상 / 가속 성장 / 성숙 / 조정 중 하나 + 1줄 근거
- **수혜 종목**: 뉴스/공시에 명시적으로 등장한 종목 (종목명만, 최대 5개)
- **깨질 시나리오**: 이 테마가 끝날 수 있는 리스크 요인 (1~2줄)
- **모멘텀 강도**: 🔥🔥🔥 (강함) / 🔥🔥 (중간) / 🔥 (약함)

**선택 항목** (입력 데이터에서 추출 가능한 경우만 작성, 불확실하면 생략):
- **시장 규모 (TAM)**: 추정 시장 규모 + 연 성장률(CAGR)
- **한국 노출도**: 글로벌 시장 대비 한국 기업 점유율 또는 매출 비중
- **과거 유사 사례**: 비슷한 흐름이 있었던 과거 테마 (예: "2017 메모리 슈퍼사이클")
- **다음 카탈리스트**: 7~30일 내 예정 일정 (어닝/정책/컨퍼런스 등)

## ⚠️ 주의 섹터 (1~2개)

각 항목 형식:
- **섹터명**: 하방 압력 이유 (1줄) + 깨질/지속 시나리오 (1줄)

## 💡 한 줄 인사이트

이 {days}일간 시장을 관통하는 핵심 스토리를 한 줄로.

## 🔄 테마 간 관계 (선택사항)

상호 보강 또는 반비례 관계인 테마 쌍이 있으면 1~2쌍만:
- "테마 A ↔ 테마 B: 관계 설명 (1줄)"

---

**중요 규칙:**

1. **양보다 깊이**: 테마는 3~4개로 충분. 5개는 깊이가 떨어지므로 지양.
2. **선택 항목은 진짜 있을 때만**: 추측하지 말고, 입력 데이터에서 명확한 근거가 있을 때만 작성. 불확실하면 **항목 자체를 생략**. "데이터 부족" 같은 표기 불필요.
3. **다음 카탈리스트**: 위 "📅 향후 30일 예정 이벤트" 섹션이 제공되면 그 일정을 우선 활용. 없으면 뉴스/공시에서 추출. 둘 다 없으면 항목 생략.
4. **수혜 종목**: 뉴스에 **실제로 등장한** 종목만. 한 종목은 한 테마에만 배정 권장 (가장 강한 매칭).
5. **이미 누구나 아는 테마**(예: "반도체 수혜")는 제외. **새롭게 부상 중인** 것 중심.
5-1. **중복 회피**: 위 "📚 이미 등록된 테마" 목록과 **의미·대상이 겹치는 테마는 발굴하지 말 것**. 이름 표현이 달라도(예: "피지컬AI 로봇 상용화" vs "물리적 AI 로봇 혁명") 같은 대상을 가리키면 중복으로 간주하고 제외. 기존 테마에 없는 **진짜 새로운** 흐름만 제시.
6. **라이프 스테이지**: 입력 데이터의 언급 빈도, 가격 동향, 정책 단계 등 종합 판단. 일관성을 위해 보수적으로(과대 단계 평가 회피).
7. 서론/결론 없이 위 형식대로 바로 작성."""


# ── AI 응답 파싱 + Theme DB 자동 등록 (권고 1) ─────────────────────────


def _extract_themes_from_analysis(analysis: str) -> list[dict[str, Any]]:
    """AI 응답에서 테마명 + 키워드 추출.

    파싱 규칙:
    - "### 1. [테마명]" 또는 "### 1. 테마명" 형식 매칭
    - 다음 줄들에서 "**핵심 키워드**:" 라인 찾기
    - 키워드는 쉼표 / 슬래시 / 세미콜론으로 구분

    Returns: [{"name": str, "keywords": list[str]}, ...]
    """
    themes: list[dict[str, Any]] = []

    theme_pattern = re.compile(
        r"^###\s+\d+\.\s+\[?([^\]\n]+?)\]?\s*$",
        re.MULTILINE,
    )
    keyword_pattern = re.compile(
        r"\*\*핵심\s*키워드\*\*\s*:\s*(.+?)(?=\n|$)",
    )

    theme_matches = list(theme_pattern.finditer(analysis))

    for idx, match in enumerate(theme_matches):
        theme_name = match.group(1).strip()
        if not theme_name or len(theme_name) > 100:
            continue

        start = match.end()
        end = theme_matches[idx + 1].start() if idx + 1 < len(theme_matches) else len(analysis)
        section = analysis[start:end]

        kw_match = keyword_pattern.search(section)
        if not kw_match:
            logger.warning("테마 '%s' 키워드 파싱 실패 — 스킵", theme_name)
            continue

        keyword_str = kw_match.group(1)
        keyword_str = re.sub(r"\*+", "", keyword_str)
        keywords = re.split(r"[,/;]", keyword_str)
        keywords = [k.strip() for k in keywords if k.strip() and len(k.strip()) <= 30]

        if not keywords:
            logger.warning("테마 '%s' 키워드 비어있음 — 스킵", theme_name)
            continue

        themes.append({
            "name": theme_name,
            "keywords": keywords,
        })

    logger.info("AI 응답에서 %d개 테마 추출", len(themes))
    return themes


async def suggest_themes_from_analysis(analysis: str) -> str:
    """AI 분석 결과에서 테마 추출 + 등록 명령어 제안 메시지 생성.

    자동 등록하지 않는다. 사용자가 복사-전송할 수 있는 /theme-add 명령어
    목록을 만들어 승인 게이트를 둔다 (테마 무한 증식 방지).

    수동 (/theme-discover)와 자동 (send_weekly_theme_report) 양쪽에서 호출.

    Args:
        analysis: discover_themes()의 result["analysis"] 텍스트

    Returns:
        제안 메시지 (텔레그램 메시지에 추가). 신규 후보 0개면 빈 문자열 또는 스킵 안내.
    """
    from app.models.theme import Theme  # 지연 import (순환 방지)

    try:
        themes_extracted = _extract_themes_from_analysis(analysis)
        if not themes_extracted:
            return ""

        async with async_session() as session:
            existing_result = await session.execute(select(Theme.name))
            existing_names = set(existing_result.scalars().all())

        new_themes = [t for t in themes_extracted if t["name"] not in existing_names]
        skipped = [t["name"] for t in themes_extracted if t["name"] in existing_names]

        if not new_themes:
            if skipped:
                return f"\nℹ️ 발굴된 테마 {len(skipped)}건 모두 기존 테마와 중복"
            return ""

        escape = telegram_service.escape_html
        lines = [
            "",
            f"🆕 <b>신규 테마 후보 {len(new_themes)}건</b> — 등록하려면 아래 명령을 그대로 보내세요:",
            "",
        ]
        for theme in new_themes:
            keywords = ",".join(theme["keywords"])
            cmd = f'/theme-add "{theme["name"]}" {keywords}'
            lines.append(f"<code>{escape(cmd)}</code>")

        if skipped:
            lines.append("")
            lines.append(f"ℹ️ 기존 테마 {len(skipped)}건 스킵: {escape(', '.join(skipped))}")

        return "\n".join(lines)
    except Exception:
        logger.exception("테마 제안 생성 실패 (발굴 메시지는 정상)")
        return ""


# ── 텔레그램 리포트 ─────────────────────────────────────────────────


async def send_weekly_theme_report() -> None:
    """주간 테마 발굴 리포트 (스케줄러에서 호출)

    v3 권고 2+3 + 승인 게이트:
    - 발굴 결과는 자동 등록하지 않고 /theme-add 명령어로 제안 (승인 게이트)
    - 빈도 분석 + 시장 주목 검증 (TOP 5)
    - 결과 메시지에 등록 명령어 제안 + ✅/⚠️ 마크 추가
    """
    logger.info("주간 테마 발굴 리포트 시작")

    result = await discover_themes(days=30)

    if "error" in result:
        await telegram_service.send_text(
            f"⚠️ 주간 테마 발굴 실패: {result['error']}"
        )
        return

    # 승인 게이트: 자동 등록 대신 명령어 제안
    suggest_summary = await suggest_themes_from_analysis(result["analysis"])

    # 권고 2+3: 빈도 분석 + 시장 주목 검증
    top_stocks, name_titles = await _analyze_stock_frequency_with_titles(days=30)

    if top_stocks and settings.anthropic_api_key:
        try:
            top_stocks = await _verify_top_stocks_attention(
                top_stocks=top_stocks,
                sample_news=name_titles,
                days=30,
                verify_count=5,
            )
        except Exception:
            logger.exception("TOP 종목 시장 주목 검증 실패")

    escape = telegram_service.escape_html

    parts = [
        "🎯 <b>주간 테마 발굴 리포트</b>",
        f"(최근 {result['days']}일 · 뉴스 {result['news_count']}건 · 공시 {result['disclosure_count']}건 분석)",
        "",
        escape(result["analysis"]),
    ]

    # 승인 게이트: 등록 명령어 제안
    if suggest_summary:
        parts.append(suggest_summary)

    if top_stocks:
        parts.append("")
        parts.append("━━━━━━━━━━━━━━━━━━━━")
        parts.append("📊 <b>언급 빈도 TOP 10 (최근 30일)</b>")
        parts.append("")
        for i, s in enumerate(top_stocks[:10], 1):
            # 권고 3: 시장 주목 검증 마크
            attention_mark = ""
            verdict = s.get("attention_verified")
            if verdict is True:
                attention_mark = " ✅"
            elif verdict is False:
                attention_mark = " ⚠️"

            parts.append(
                f"{i}. <b>{escape(s['stock_name'])}</b> ({s['stock_code']})"
                f"{attention_mark} — {s['mention_count']}회 · {s['unique_days']}일 언급"
            )

        parts.append("")
        parts.append("<i>✅ 특별 이슈로 시장 주목 / ⚠️ 일반 빈출 (TOP 5 검증)</i>")

    message = "\n".join(parts)

    await telegram_service.send_long_text(message)


# ── 스테일 테마 자동 비활성화 (F-2) ──────────────────────────────────────


async def deactivate_stale_themes(inactive_days: int = 28) -> list[str]:
    """휴면 테마 자동 비활성화 (삭제 아님 — 감지 이력 보존).

    기준 (3개 모두 충족):
    - enabled=True
    - 생성 후 inactive_days일 이상 경과
    - 최근 inactive_days일간 ThemeDetection 0건

    Returns: 비활성화된 테마명 리스트.
    """
    from app.models.theme import Theme, ThemeDetection  # 지연 import (순환 방지)

    cutoff = now_kst_naive() - timedelta(days=inactive_days)
    deactivated: list[str] = []

    async with async_session() as session:
        result = await session.execute(
            select(Theme).where(Theme.enabled == True)  # noqa: E712
        )
        themes = list(result.scalars().all())

        for theme in themes:
            # 생성 후 inactive_days일 이상 경과한 테마만 대상
            if theme.created_at is None or theme.created_at > cutoff:
                continue
            # 최근 inactive_days일간 감지 이력이 하나라도 있으면 유지
            det_result = await session.execute(
                select(ThemeDetection.id)
                .where(ThemeDetection.theme_id == theme.id)
                .where(ThemeDetection.detected_at >= cutoff)
                .limit(1)
            )
            if det_result.first() is not None:
                continue

            theme.enabled = False
            deactivated.append(theme.name)
            logger.info("휴면 테마 비활성화: %s", theme.name)

        if deactivated:
            await session.commit()

    return deactivated
