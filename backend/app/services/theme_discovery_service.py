"""아카이브 기반 테마 자동 발굴 — 누적 뉴스/공시에서 AI가 테마 감지"""
from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import date, timedelta
from typing import Any, Optional

import anthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.stock_search import search_stocks
from app.config import settings
from app.database import async_session
from app.models.brief import DailyBrief
from app.services import ai_verifier, telegram_service

logger = logging.getLogger(__name__)

STOCK_NAME_PATTERN = re.compile(r"([가-힣][가-힣A-Za-z0-9]{1,14})")

STOPWORDS = {
    "한국", "미국", "중국", "일본", "유럽", "코스피", "코스닥",
    "증시", "시장", "투자", "기업", "정부", "대통령", "장관", "위원회",
    "분석", "전망", "예상", "발표", "공시", "뉴스", "기사", "매출", "실적",
    "영업이익", "순이익", "주가", "주식", "종목", "거래", "상승", "하락",
    "오늘", "내일", "어제", "금주", "이번", "지난", "최근",
}

# 한국 주요 그룹명 — 단독 등장 시 지주사로 잘못 매핑되므로 차단
# (그룹명 + 후속 단어 결합한 종목명은 정상 매칭됨, 예: "한화에어로스페이스")
GROUP_PREFIX_NAMES = {
    "삼성", "LG", "현대", "SK", "롯데", "한화", "한국", "GS",
    "CJ", "두산", "포스코", "효성", "한진", "신세계", "농심",
    "오리온", "동원", "코오롱", "대상",
}


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
    cutoff = date.today() - timedelta(days=days)
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
            candidates = set(STOCK_NAME_PATTERN.findall(title))
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
    async with async_session() as session:
        archives = await _get_recent_archives(session, days)

    if not archives:
        return {"error": "분석할 아카이브가 없습니다."}

    if not settings.anthropic_api_key:
        return {"error": "Anthropic API 키가 설정되지 않았습니다."}

    news_titles: list[str] = []
    disclosure_titles: list[str] = []
    ai_summaries: list[str] = []

    for brief in archives:
        date_str = brief.date.isoformat()
        for news in (brief.news_raw or [])[:10]:
            title = news.get("title", "")
            if title:
                news_titles.append(f"[{date_str}] {title}")
        for disc in (brief.disclosures or [])[:5]:
            title = disc.get("title", "") or disc.get("report_nm", "")
            if title:
                disclosure_titles.append(f"[{date_str}] {title}")
        if brief.news_summary:
            ai_summaries.append(f"[{date_str}] {brief.news_summary[:200]}")

    prompt = _build_theme_discovery_prompt(
        days, news_titles, disclosure_titles, ai_summaries
    )

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model=settings.ai_model,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        analysis = response.content[0].text
        logger.info(
            "테마 발굴 완료 (%d tokens, %d days)",
            response.usage.output_tokens, days,
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
) -> str:
    """테마 발굴용 Claude 프롬프트 구성"""
    news_section = "\n".join(news_titles[:300])
    disclosure_section = "\n".join(disclosure_titles[:100])
    summary_section = "\n\n".join(ai_summaries[:30])

    return f"""당신은 한국 주식 시장 테마 분석 전문가입니다.

다음은 최근 {days}일간 한국 증시 관련 뉴스 제목, DART 공시 제목, 그리고 일일 AI 요약입니다.

이 데이터에서 **부상 중인 투자 테마**와 **수혜 종목**을 발굴해주세요.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📰 뉴스 제목 (최근 {days}일):
{news_section}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 DART 공시 제목:
{disclosure_section}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🤖 일일 AI 요약:
{summary_section}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

다음 형식으로 답변하세요:

## 📈 부상 중인 테마 (3~5개)

각 테마에 대해:

### 1. [테마명]
- **부상 근거**: 왜 이 테마가 주목받는지 (2~3줄)
- **핵심 키워드**: 해당 테마를 관통하는 키워드 3~5개
- **수혜 종목**: 뉴스/공시에 등장한 관련 종목 (종목명만 나열, 최대 5개)
- **모멘텀 강도**: 🔥🔥🔥 (강함) / 🔥🔥 (중간) / 🔥 (약함)

## ⚠️ 주의 섹터

단기적으로 하방 압력을 받고 있는 섹터가 있다면 1~2개만 간단히.

## 💡 한 줄 인사이트

이 {days}일간 시장을 관통하는 핵심 스토리를 한 줄로.

---

**중요 규칙:**
- 뉴스에 **실제로 등장한** 종목/키워드만 사용. 추측 금지.
- 이미 누구나 아는 테마(예: "반도체 수혜")는 제외. **새롭게 부상 중인** 것 중심.
- 수혜 종목은 뉴스 제목이나 공시에 명시적으로 나온 것만 포함.
- 서론/결론 없이 위 형식대로 바로 작성."""


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


async def _auto_register_themes(themes_data: list[dict[str, Any]]) -> tuple[int, int]:
    """추출된 테마를 Theme DB에 자동 등록.

    중복 처리:
    - 동일 name 이미 존재 → 스킵 (사용자 등록 보존)
    - 신규 → Theme(enabled=True)로 추가

    Returns: (신규_등록_수, 기존_스킵_수)
    """
    from app.models.theme import Theme  # 지연 import (순환 방지)

    if not themes_data:
        return 0, 0

    new_count = 0
    skip_count = 0

    async with async_session() as session:
        existing_result = await session.execute(select(Theme.name))
        existing_names = set(existing_result.scalars().all())

        for theme in themes_data:
            name = theme["name"]
            keywords = theme["keywords"]

            if name in existing_names:
                skip_count += 1
                logger.info("테마 자동등록 스킵 (이미 존재): %s", name)
                continue

            new_theme = Theme(
                name=name,
                keywords=",".join(keywords),
                enabled=True,
            )
            session.add(new_theme)
            new_count += 1
            logger.info(
                "테마 자동등록: %s (키워드 %d개)",
                name, len(keywords),
            )

        try:
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("테마 자동등록 commit 실패")
            return 0, skip_count

    return new_count, skip_count


async def auto_register_from_analysis(analysis: str) -> str:
    """AI 분석 결과에서 테마 추출 + 자동 등록 + 결과 메시지 생성.

    수동 (/theme-discover)와 자동 (send_weekly_theme_report) 양쪽에서 호출.

    Args:
        analysis: discover_themes()의 result["analysis"] 텍스트

    Returns:
        결과 요약 메시지 (텔레그램 메시지에 추가할 1줄). 자동 등록 0개면 빈 문자열.
    """
    try:
        themes_extracted = _extract_themes_from_analysis(analysis)
        if not themes_extracted:
            return ""

        new_count, skip_count = await _auto_register_themes(themes_extracted)

        if new_count > 0:
            msg = (
                f"\n✅ <b>{new_count}개 테마 자동 등록됨</b> "
                f"(다음 월요일 08:00 자동 스캔 예정)"
            )
            if skip_count > 0:
                msg += f" · 기존 {skip_count}개 스킵"
            return msg
        elif skip_count > 0:
            return f"\nℹ️ 모두 기존 테마 ({skip_count}개)"
        else:
            return ""
    except Exception:
        logger.exception("테마 자동 등록 실패 (발굴 메시지는 정상)")
        return ""


# ── 텔레그램 리포트 ─────────────────────────────────────────────────


async def send_weekly_theme_report() -> None:
    """주간 테마 발굴 리포트 (스케줄러에서 호출)

    v3 권고 1+2+3 통합:
    - 발굴 결과를 Theme DB에 자동 등록
    - 빈도 분석 + 시장 주목 검증 (TOP 5)
    - 결과 메시지에 자동 등록 + ✅/⚠️ 마크 추가
    """
    logger.info("주간 테마 발굴 리포트 시작")

    result = await discover_themes(days=30)

    if "error" in result:
        await telegram_service.send_text(
            f"⚠️ 주간 테마 발굴 실패: {result['error']}"
        )
        return

    # 권고 1: 자동 등록 (공통 헬퍼)
    auto_register_summary = await auto_register_from_analysis(result["analysis"])

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

    # 권고 1: 자동 등록 결과
    if auto_register_summary:
        parts.append(auto_register_summary)

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
