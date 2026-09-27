"""아카이브 기반 테마 자동 발굴 — 누적 뉴스/공시에서 AI가 테마 감지"""
from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import timedelta
from typing import Any, Optional

import anthropic
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.stock_search import search_stocks
from app.config import settings
from app.database import async_session
from app.models.brief import DailyBrief
from app.services import ai_verifier, telegram_service
from app.services.stock_name_rules import GROUP_PREFIX_NAMES, STOPWORDS
from app.utils.timezone import now_kst_naive, today_kst

logger = logging.getLogger(__name__)

# P2-3: 발굴 보조 코퍼스 — 섹터 고정 키워드 (거시 뉴스만으로는 니치 테마가
# 입력에 등장하지 않는 문제 보완). 운영하며 조정.
SECTOR_KEYWORDS = [
    "반도체 장비", "2차전지 소재", "방산 수주", "조선 수주", "제약 임상",
    "로봇", "원전", "전력기기", "화장품 수출", "게임 신작",
]
# 프롬프트 입력 배분: 거시(브리프) 400 + 섹터 200 (기존 상한 600 유지)
_MACRO_TITLE_CAP = 400
_SECTOR_TITLE_CAP = 200

# ── 주간 자동 등록/정리 임계 ──────────────────────────────────────────
# 테마 1개당 하루 평균 ~7.5회 AI 검증을 소비하므로 총량이 곧 크레딧 상한이다.
MAX_NEW_THEMES_PER_WEEK = 3   # 1회 발굴에서 등록할 신규 테마 상한
MAX_ACTIVE_THEMES = 15        # 활성 테마 총 상한 (하루 검증 ~113회)
RETIRE_YIELD_THRESHOLD = 0.05  # 정리 임계 — AI 검증 수율 5% 미만
RETIRE_MIN_VERDICTS = 20      # 수율 판정 최소 표본 (미만이면 판정 보류)
RETIRE_WINDOW_DAYS = 30       # 수율·수혜주 관찰 윈도우

# ── 상한 도달 시 저생산성 테마 교체(rotation) ────────────────────────
# 활성 상한에 막힌 4원칙 통과 신규 테마는 "가장 생산성 낮은 기존 테마"와 자리를
# 바꾼다. 생산성 = 30일 YES 감지 수 + 60일 수혜주(ThemeScanResult) 고유 종목 수.
# 생산성이 ROTATION_VICTIM_MAX_SCORE를 넘는 테마는 교체 대상이 아니다 — 검증된
# 테마를 미검증 신규와 바꾸는 역선택 방지. 교체 대상이 없으면 보류.
ROTATION_GRACE_DAYS = 14        # 등록 후 이 기간은 교체 대상에서 제외
ROTATION_VICTIM_MAX_SCORE = 1   # 생산성 ≤ 1 인 테마만 교체 가능
ROTATION_YES_WINDOW_DAYS = 30
ROTATION_SCAN_WINDOW_DAYS = 60
MIN_KEYWORDS_PER_THEME = 2      # 4원칙 정리 후 남는 키워드 최소 수

# ── 임시 초과석(probation) ───────────────────────────────────────────
# 상한 도달 + 교체 대상 없음 + 신규 테마 모멘텀 🔥🔥🔥 이면 기존 테마를 즉시
# 죽이지 않고 상한을 넘겨 등록한다. 전 활성 테마가 PROBATION_DAYS 이상 된 시점에
# 생산성 꼴찌(임계 없음)를 초과분만큼 비활성화해 상한으로 복귀 — 신규에게 증명
# 기회를 주되 결정은 AI 🔥 판정이 아니라 실측 생산성으로 한다.
PROBATION_SLOTS = 1             # 상한 초과 허용 자리 수
PROBATION_DAYS = 14             # 초과 해소 전 최소 관찰 기간 (= ROTATION_GRACE_DAYS)
PROBATION_MIN_MOMENTUM = 3      # 🔥 개수 — 3(강함)만 초과석 자격

# ── 키워드 4원칙 기계 판정 규칙 (원칙 3 범용어) ─────────────────────
# 발굴 프롬프트의 원칙 3 예시("차세대반도체", "공급망 재편", "소재혁신")를 포함하는
# 형태 규칙. 의미 판정(원칙 1·2)은 _semantic_keyword_check(Claude)가 맡는다.
GENERIC_KEYWORD_EXACT = {
    "공급망", "공급망 재편", "소재", "장비", "기술", "산업", "혁신", "성장",
    "수출", "수주", "정책", "투자", "신사업", "글로벌", "미래", "전환",
    "트렌드", "패러다임", "모멘텀", "테마", "AI", "인공지능", "반도체",
    "2차전지", "바이오", "로봇", "친환경", "에너지", "디지털", "플랫폼",
}
GENERIC_KEYWORD_PREFIXES = ("차세대", "신개념", "첨단", "미래형")
GENERIC_KEYWORD_SUFFIXES = (
    "혁신", "재편", "고도화", "패러다임", "트렌드", "확대", "강화", "전환기",
)

# radar와 동일 패턴 — 영문 시작 허용 (LG·SK·HD·POSCO 등 대형주가
# 빈도 분석에서 구조적으로 제외되던 불일치 해소)
STOCK_NAME_PATTERN = re.compile(r"([A-Za-z가-힣][A-Za-z가-힣0-9&]{1,14})")


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
        # 단음절 차단 (정규식이 이미 2자 이상 보장 — 기아 등 2자 상장사를
        # 차단하던 <= 2 조건을 주석 의도대로 정정)
        if len(name) < 2:
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
        existing_result = await session.execute(select(Theme.name, Theme.keywords))
        existing_rows = list(existing_result.all())
        existing_themes = [name for name, _ in existing_rows]
        # 키워드 4원칙 대조용 — 활성/비활성 무관 전체 테마 키워드를 평탄화
        existing_keywords = sorted({
            kw.strip()
            for _, keywords in existing_rows
            for kw in (keywords or "").split(",")
            if kw.strip()
        })

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

    # P2-3: 섹터 보조 코퍼스 — 거시 400 + 섹터 200 배분
    news_titles = news_titles[:_MACRO_TITLE_CAP]
    sector_titles: list[str] = []
    from app.collectors.news_collector import _fetch_naver_news
    for kw in SECTOR_KEYWORDS:
        try:
            items = await _fetch_naver_news(kw, display=10)
        except Exception:
            logger.exception("섹터 키워드 뉴스 수집 실패: %s", kw)
            continue
        for it in items:
            title = it.get("title", "")
            if title:
                sector_titles.append(f"[섹터:{kw}] {title}")
    news_titles += sector_titles[:_SECTOR_TITLE_CAP]
    logger.info(
        "테마 발굴 코퍼스: 거시 %d + 섹터 %d",
        len(news_titles) - min(len(sector_titles), _SECTOR_TITLE_CAP),
        min(len(sector_titles), _SECTOR_TITLE_CAP),
    )

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
        existing_keywords=existing_keywords,
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
    existing_keywords: Optional[list[str]] = None,
) -> str:
    """테마 발굴용 Claude 프롬프트 (v2.1 — 9~12개 항목 분석가 리포트).

    events_text가 제공되면 카탈리스트 항목에 활용.
    없으면 카탈리스트 항목은 뉴스/공시에서만 추출 시도.
    existing_themes가 제공되면 의미상 중복 테마 재생성을 회피하도록 지시.
    existing_keywords가 제공되면 키워드 4원칙(§키워드 작성 규칙)의 중복 금지 대조에 사용.
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

    existing_kw_block = ""
    if existing_keywords:
        existing_kw_list = ", ".join(existing_keywords)
        existing_kw_block = f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔑 기존 테마 키워드 (중복 금지 대조용 — 원칙 4):
{existing_kw_list}

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

{events_block}{existing_block}{existing_kw_block}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

다음 형식으로 답변하세요:

## 📈 부상 중인 테마 (3~4개)

### 1. [테마명]

**필수 항목** (모든 테마에 작성):
- **부상 근거**: 왜 이 테마가 주목받는지 (2~3줄)
- **핵심 키워드**: 해당 테마를 관통하는 키워드 3~5개 (쉼표 구분) — 아래 **키워드 작성 4원칙**을 반드시 준수
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

7. **키워드 작성 4원칙** (핵심 키워드는 테마 스캐너가 뉴스 매칭에 그대로 사용하므로 아래를 **모두** 지킬 것):
   - **원칙 1 — 기업명·인명 금지**: 특정 기업명("한화시스템", "포스코인터")이나 인명("최태원")을 키워드로 쓰지 말 것. 개별 종목이 아니라 테마 전체를 포착하는 개념어를 사용.
   - **원칙 2 — 수요·원인 단어 금지**: 수요/원인을 가리키는 말("데이터센터", "AI 전력난", "AI인프라")은 금지. 그 수요가 유발하는 **공급·제품·기술 축**(예: "변압기", "HVDC")을 키워드로 삼을 것.
   - **원칙 3 — 범용어 금지**: 너무 넓어 아무 종목에나 걸리는 말("차세대반도체", "공급망 재편", "소재혁신")은 금지. 테마를 특정하는 구체어를 쓸 것.
   - **원칙 4 — 기존 키워드 중복 금지**: 위 "🔑 기존 테마 키워드" 목록에 이미 있는 키워드와 **동일하거나 사실상 같은** 키워드는 쓰지 말 것. 신규 테마는 기존과 겹치지 않는 고유 키워드로 구성.

8. 서론/결론 없이 위 형식대로 바로 작성."""


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
    momentum_pattern = re.compile(r"\*\*모멘텀\s*강도\*\*\s*:\s*(.+?)(?=\n|$)")

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

        momentum_match = momentum_pattern.search(section)
        momentum = momentum_match.group(1).count("🔥") if momentum_match else 0

        themes.append({
            "name": theme_name,
            "keywords": keywords,
            "momentum": momentum,   # 🔥 개수 (0=미기재)
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


# ── 키워드 4원칙 검증 (자동 등록 게이트) ──────────────────────────────


def _norm_kw(kw: str) -> str:
    return re.sub(r"\s+", "", kw).lower()


def is_generic_keyword(kw: str) -> bool:
    """원칙 3 — 범용어 형태 규칙 (순수 함수)."""
    k = kw.strip()
    n = _norm_kw(k)
    if len(n) < 2:
        return True
    if k in STOPWORDS or n in {_norm_kw(g) for g in GENERIC_KEYWORD_EXACT}:
        return True
    if any(k.startswith(p) for p in GENERIC_KEYWORD_PREFIXES):
        return True
    if any(k.endswith(s) for s in GENERIC_KEYWORD_SUFFIXES):
        return True
    return False


def keyword_duplicates_existing(kw: str, existing_keywords: set[str]) -> Optional[str]:
    """원칙 4 — 기존 키워드와 동일/포함 관계면 그 기존 키워드를 반환 (순수 함수).

    포함 관계(HVDC ⊂ HVDC케이블)도 중복으로 본다: 스캐너의 부분 문자열 매칭은
    두 키워드가 같은 기사를 잡으므로 "사실상 같은" 키워드다.
    """
    n = _norm_kw(kw)
    if not n:
        return None
    for ex in existing_keywords:
        e = _norm_kw(ex)
        if not e:
            continue
        if n == e or (len(e) >= 2 and e in n) or (len(n) >= 2 and n in e):
            return ex
    return None


class KeywordValidation:
    """validate_theme_keywords 결과 — kept가 최소 수 이상이면 ok."""

    def __init__(self) -> None:
        self.kept: list[str] = []
        self.dropped: list[tuple[str, str]] = []  # (키워드, 사유)

    @property
    def ok(self) -> bool:
        return len(self.kept) >= MIN_KEYWORDS_PER_THEME

    @property
    def reason(self) -> str:
        parts = [f"{kw}({why})" for kw, why in self.dropped]
        head = "" if self.ok else f"유효 키워드 {len(self.kept)}개 < {MIN_KEYWORDS_PER_THEME}"
        body = "제외: " + ", ".join(parts) if parts else ""
        return " · ".join(p for p in (head, body) if p)


def validate_theme_keywords(
    keywords: list[str],
    existing_keywords: set[str],
    corp_names: set[str],
) -> KeywordValidation:
    """키워드 4원칙 기계 판정 (순수 함수) — 위반 키워드를 제거하고 나머지를 보존.

    - 원칙 1 (기업명): stock_corp_map 상장사명 / 그룹명과 정확히 일치
    - 원칙 3 (범용어): is_generic_keyword
    - 원칙 4 (중복): keyword_duplicates_existing — 같은 테마 안의 중복도 제거
    - 원칙 2 (수요·원인어)는 형태로 판정 불가 → Claude 의미 검증에 위임
    """
    v = KeywordValidation()
    seen: set[str] = set()
    corp_norm = {_norm_kw(c) for c in corp_names if c}
    group_norm = {_norm_kw(g) for g in GROUP_PREFIX_NAMES}
    for raw in keywords:
        kw = raw.strip()
        n = _norm_kw(kw)
        if not n:
            continue
        if n in seen:
            continue
        seen.add(n)
        if n in corp_norm or n in group_norm:
            v.dropped.append((kw, "원칙1 기업명"))
            continue
        if is_generic_keyword(kw):
            v.dropped.append((kw, "원칙3 범용어"))
            continue
        dup = keyword_duplicates_existing(kw, existing_keywords)
        if dup is not None:
            v.dropped.append((kw, f"원칙4 중복←{dup}"))
            continue
        v.kept.append(kw)
    return v


_KEYWORD_SEMANTIC_PROMPT = """당신은 한국 주식 테마 스캐너의 키워드 검수자입니다.

테마명: {name}
키워드: {keywords}

이 키워드들은 뉴스 제목·본문 매칭에 **그대로** 사용됩니다. 아래 원칙을 **모든** 키워드가 지키는지 판정하세요.

- 원칙 1 — 기업명·인명 금지: 특정 기업명(예: "한화시스템", "포스코인터"), 브랜드명, 인명(예: "최태원")은 불가. 테마 전체를 포착하는 개념어여야 함.
- 원칙 2 — 수요·원인 단어 금지: 수요/원인을 가리키는 말(예: "데이터센터", "AI 전력난", "AI인프라")은 불가. 그 수요가 유발하는 공급·제품·기술 축(예: "변압기", "HVDC")이어야 함.
- 원칙 3 — 범용어 금지: 너무 넓어 아무 종목에나 걸리는 말(예: "차세대반도체", "공급망 재편", "소재혁신")은 불가.

하나라도 위반하면 NO. 애매하면 보수적으로 NO.

출력 형식 (정확히):
VERDICT: YES
REASON: (1줄)

또는:

VERDICT: NO
REASON: (위반 키워드와 원칙 번호, 1줄)
"""


def build_keyword_semantic_prompt(name: str, keywords: list[str]) -> str:
    return _KEYWORD_SEMANTIC_PROMPT.format(name=name, keywords=", ".join(keywords))


async def _semantic_keyword_check(name: str, keywords: list[str]) -> tuple[Optional[bool], str]:
    """원칙 1·2(의미) Claude 판정. None = 판정 불가(API 실패) — 호출측 fail-closed."""
    return await ai_verifier.verify_with_claude(
        build_keyword_semantic_prompt(name, keywords),
        log_context=f"[keyword-4rules] {name}",
    )


async def _load_corp_names() -> set[str]:
    """stock_corp_map 상장사명 (원칙 1 기계 판정용). 실패 시 빈 집합."""
    try:
        from app.models.fundamental_cache import StockCorpMap
        async with async_session() as session:
            result = await session.execute(select(StockCorpMap.corp_name))
            return {n for n in result.scalars().all() if n}
    except Exception:
        logger.exception("상장사명 로드 실패 — 원칙1 기계 판정 없이 진행")
        return set()


# ── 저생산성 테마 교체 (활성 상한 도달 시) ─────────────────────────────


def select_rotation_victim(
    stats: list[dict[str, Any]],
    *,
    grace_cutoff,
    exclude: Optional[set[str]] = None,
    max_score: Optional[int] = ROTATION_VICTIM_MAX_SCORE,
) -> Optional[dict[str, Any]]:
    """교체 대상 선택 (순수 함수).

    stats: [{"name", "created_at", "yes_30d", "stocks_60d"}]
    - 등록 ROTATION_GRACE_DAYS 미경과 / exclude 제외
    - score = yes_30d + stocks_60d 가 max_score 이하인 것 중 최소
      (동점이면 오래된 테마 우선). max_score=None 이면 임계 없이 꼴찌.
    """
    exclude = exclude or set()
    eligible = []
    for s in stats:
        if s["name"] in exclude:
            continue
        created = s.get("created_at")
        if created is None or created > grace_cutoff:
            continue
        score = int(s.get("yes_30d", 0)) + int(s.get("stocks_60d", 0))
        if max_score is not None and score > max_score:
            continue
        eligible.append((score, created, s))
    if not eligible:
        return None
    eligible.sort(key=lambda x: (x[0], x[1]))
    victim = dict(eligible[0][2])
    victim["score"] = eligible[0][0]
    return victim


async def _collect_active_theme_stats(session: AsyncSession) -> list[dict[str, Any]]:
    """활성 테마별 생산성 지표 수집."""
    from app.models.theme import Theme, ThemeDetection, ThemeScanResult

    yes_cutoff = now_kst_naive() - timedelta(days=ROTATION_YES_WINDOW_DAYS)
    scan_cutoff = today_kst() - timedelta(days=ROTATION_SCAN_WINDOW_DAYS)

    result = await session.execute(select(Theme).where(Theme.enabled == True))  # noqa: E712
    stats: list[dict[str, Any]] = []
    for theme in result.scalars().all():
        yes_count = await session.scalar(
            select(func.count(ThemeDetection.id))
            .where(ThemeDetection.theme_id == theme.id)
            .where(ThemeDetection.detected_at >= yes_cutoff)
            .where(ThemeDetection.is_active.is_(True))
            .where(
                (ThemeDetection.verdict.is_(None))
                | (ThemeDetection.verdict != "NO")
            )
        ) or 0
        stock_count = await session.scalar(
            select(func.count(func.distinct(ThemeScanResult.stock_code)))
            .where(ThemeScanResult.theme_name == theme.name)
            .where(ThemeScanResult.scan_date >= scan_cutoff)
            .where(ThemeScanResult.is_active.is_(True))
        ) or 0
        stats.append({
            "name": theme.name,
            "created_at": theme.created_at,
            "yes_30d": int(yes_count),
            "stocks_60d": int(stock_count),
        })
    return stats


def select_overflow_evictions(
    stats: list[dict[str, Any]],
    *,
    now,
    max_active: int = MAX_ACTIVE_THEMES,
    probation_days: int = PROBATION_DAYS,
) -> Optional[list[dict[str, Any]]]:
    """임시 초과 해소 대상 (순수 함수).

    활성 수가 max_active를 넘을 때, **모든** 활성 테마가 probation_days 이상
    됐으면 생산성 꼴찌를 초과분만큼 반환. 아직 관찰 중인 테마가 있으면 None
    (이번 주 보류). 초과가 없으면 빈 리스트.
    """
    excess = len(stats) - max_active
    if excess <= 0:
        return []
    cutoff = now - timedelta(days=probation_days)
    if any(s.get("created_at") is None or s["created_at"] > cutoff for s in stats):
        return None
    ranked = sorted(
        stats,
        key=lambda s: (int(s.get("yes_30d", 0)) + int(s.get("stocks_60d", 0)), s["created_at"]),
    )
    out = []
    for s in ranked[:excess]:
        v = dict(s)
        v["score"] = int(s.get("yes_30d", 0)) + int(s.get("stocks_60d", 0))
        out.append(v)
    return out


async def resolve_overflow_themes() -> list[str]:
    """임시 초과석 해소 — 상한 복귀 (주간 정리 단계에서 호출).

    Returns: 비활성화된 테마명 리스트 (관찰 중이면 빈 리스트).
    """
    from app.models.theme import Theme

    retired: list[str] = []
    async with async_session() as session:
        stats = await _collect_active_theme_stats(session)
        victims = select_overflow_evictions(stats, now=now_kst_naive())
        if victims is None:
            logger.info(
                "임시 초과 %d건 — 관찰 기간(%d일) 미경과 테마 있어 이번 주 보류",
                len(stats) - MAX_ACTIVE_THEMES, PROBATION_DAYS,
            )
            return []
        for v in victims:
            theme = (
                await session.execute(select(Theme).where(Theme.name == v["name"]))
            ).scalar_one_or_none()
            if theme is None:
                continue
            theme.enabled = False
            retired.append(theme.name)
            logger.info(
                "임시 초과 해소: %s 비활성화 (30일 YES %d · 60일 수혜주 %d)",
                theme.name, v["yes_30d"], v["stocks_60d"],
            )
        if retired:
            await session.commit()
    return retired


def format_auto_register_report(
    *,
    registered: list[dict[str, Any]],
    replaced: list[tuple[dict[str, Any], str]],
    deferred: list[str],
    manual: list[tuple[dict[str, Any], str]],
    skipped_dup: list[str],
    active_count: int,
    probation: Optional[list[str]] = None,
) -> str:
    """자동 등록 결과 텔레그램 블록 (순수 함수)."""
    escape = telegram_service.escape_html
    lines: list[str] = [""]
    probation = probation or []

    if registered:
        lines.append(f"🆕 <b>신규 테마 {len(registered)}건 자동 등록</b> (키워드 4원칙 통과)")
        for t in registered:
            lines.append(f"· {escape(t['name'])} — {escape(', '.join(t['keywords']))}")
            if t.get("dropped"):
                dropped = ", ".join(f"{kw}({why})" for kw, why in t["dropped"])
                lines.append(f"  <i>키워드 정리: {escape(dropped)}</i>")

    if replaced:
        lines.append("")
        lines.append(f"🔁 <b>저생산성 테마 교체 {len(replaced)}건</b>")
        for victim, new_name in replaced:
            lines.append(
                f"· {escape(victim['name'])} → {escape(new_name)} "
                f"(30일 YES {victim['yes_30d']}건 · 60일 수혜주 {victim['stocks_60d']}개)"
            )
        lines.append('  <i>되돌리기: /theme-on "테마명"</i>')

    if probation:
        lines.append("")
        lines.append(
            f"🧪 <b>임시 초과 등록 {len(probation)}건</b> (🔥🔥🔥 · 활성 {active_count}/{MAX_ACTIVE_THEMES}): "
            f"{escape(', '.join(probation))}"
        )
        lines.append(
            f"  <i>{PROBATION_DAYS}일 관찰 후 생산성 꼴찌 {len(probation)}개 자동 비활성화로 상한 복귀</i>"
        )

    if deferred:
        lines.append("")
        lines.append(
            f"⏸️ 상한 초과 보류 {len(deferred)}건 "
            f"(활성 {active_count}/{MAX_ACTIVE_THEMES}, 교체 가능 테마 없음): "
            f"{escape(', '.join(deferred))}"
        )

    if manual:
        lines.append("")
        lines.append(f"✋ <b>수동 확인 {len(manual)}건</b> — 4원칙 미통과, 키워드 수정 후 등록하려면:")
        for t, why in manual:
            cmd = f'/theme-add "{t["name"]}" {",".join(t["keywords"])}'
            lines.append(f"<code>{escape(cmd)}</code>")
            lines.append(f"  <i>{escape(why)}</i>")

    if skipped_dup:
        lines.append("")
        lines.append(f"ℹ️ 기존 테마 {len(skipped_dup)}건 스킵: {escape(', '.join(skipped_dup))}")
        if any(n.endswith("(비활성)") for n in skipped_dup):
            lines.append('  <i>비활성 테마가 재발굴됨 — 되살리려면 /theme-on "테마명"</i>')

    lines.append("")
    lines.append(f"📊 활성 테마 {active_count}/{MAX_ACTIVE_THEMES}")
    return "\n".join(lines)


async def auto_register_themes(analysis: str) -> tuple[list[str], str]:
    """AI 발굴 결과를 Theme DB에 자동 등록 (주간 스케줄 전용).

    수동 경로(/theme-discover)는 승인 게이트(suggest_themes_from_analysis)를
    그대로 유지하고, 주간 자동 경로만 등록까지 수행한다.

    등록 조건·상한:
    1) 키워드 4원칙 통과분만 — 기계 판정(원칙 1·3·4)으로 위반 키워드를 제거한 뒤
       남은 키워드에 Claude 의미 판정(원칙 1·2). 불통과·판정불가는 등록하지 않고
       /theme-add 수동 명령으로 제안 (fail-closed).
    2) 1회 최대 MAX_NEW_THEMES_PER_WEEK건
    3) 활성 총 MAX_ACTIVE_THEMES건 — 초과 시 저생산성 테마와 교체
       (select_rotation_victim). 교체 대상이 없으면: 모멘텀 🔥🔥🔥 신규는
       임시 초과석(PROBATION_SLOTS)으로 등록하고 나머지는 보류.
       초과분은 주간 정리 단계 resolve_overflow_themes가 실측 생산성으로 해소.

    Returns: (등록된 테마명 리스트, 텔레그램 요약 메시지)
    """
    from app.models.theme import Theme  # 지연 import (순환 방지)
    from app.services import theme_radar_service

    try:
        extracted = _extract_themes_from_analysis(analysis)
        if not extracted:
            return [], ""

        async with async_session() as session:
            # 이름은 unique 제약 — 비활성 테마도 중복 판정에 포함해야 한다
            rows = list(
                (await session.execute(select(Theme.name, Theme.keywords, Theme.enabled))).all()
            )
        existing_names = {name for name, _, _ in rows}
        inactive_names = {name for name, _, enabled in rows if not enabled}
        existing_keywords = {
            kw.strip() for _, kws, _ in rows for kw in (kws or "").split(",") if kw.strip()
        }

        candidates = [t for t in extracted if t["name"] not in existing_names]
        # 재발굴된 기존 테마: 비활성이면 되살릴 후보라고 표시 (자동 재활성화는 하지 않음)
        skipped_dup = [
            t["name"] + (" (비활성)" if t["name"] in inactive_names else "")
            for t in extracted if t["name"] in existing_names
        ]
        rediscovered = {t["name"] for t in extracted if t["name"] in existing_names}
        if not candidates:
            if skipped_dup:
                return [], f"\nℹ️ 발굴된 테마 {len(skipped_dup)}건 모두 기존 테마와 중복"
            return [], ""

        # 1) 키워드 4원칙 게이트
        corp_names = await _load_corp_names()
        passed: list[dict[str, Any]] = []
        manual: list[tuple[dict[str, Any], str]] = []
        for t in candidates:
            v = validate_theme_keywords(t["keywords"], existing_keywords, corp_names)
            if not v.ok:
                manual.append((t, v.reason))
                continue
            sem_ok, sem_reason = await _semantic_keyword_check(t["name"], v.kept)
            if sem_ok is None:
                manual.append((t, f"AI 판정 불가({sem_reason}) — 안전상 미등록"))
                continue
            if sem_ok is False:
                manual.append((t, f"AI 판정 NO: {sem_reason}"))
                continue
            passed.append({
                "name": t["name"], "keywords": v.kept, "dropped": v.dropped,
                "momentum": t.get("momentum", 0),
            })
            existing_keywords.update(v.kept)  # 같은 주 후보 간 중복도 차단

        deferred: list[str] = [t["name"] for t in passed[MAX_NEW_THEMES_PER_WEEK:]]
        passed = passed[:MAX_NEW_THEMES_PER_WEEK]

        # 2) 등록 + 상한 교체
        registered: list[dict[str, Any]] = []
        replaced: list[tuple[dict[str, Any], str]] = []
        probation: list[str] = []
        async with async_session() as session:
            stats = await _collect_active_theme_stats(session)
            active_count = len(stats)
            grace_cutoff = now_kst_naive() - timedelta(days=ROTATION_GRACE_DAYS)
            # 이번 주 다시 발굴된 테마는 "여전히 유효"한 신호 — 교체 대상에서 제외
            evicted: set[str] = set(rediscovered)

            for t in passed:
                victim_obj = None
                on_probation = False
                if active_count >= MAX_ACTIVE_THEMES:
                    victim = select_rotation_victim(
                        stats, grace_cutoff=grace_cutoff, exclude=evicted
                    )
                    if victim is None:
                        # 교체 대상 없음 → 🔥🔥🔥 이면 임시 초과석, 아니면 보류
                        if (
                            t.get("momentum", 0) >= PROBATION_MIN_MOMENTUM
                            and active_count < MAX_ACTIVE_THEMES + PROBATION_SLOTS
                        ):
                            on_probation = True
                        else:
                            deferred.append(t["name"])
                            continue
                    if not on_probation:
                        victim_obj = (
                            await session.execute(
                                select(Theme).where(Theme.name == victim["name"])
                            )
                        ).scalar_one_or_none()
                        if victim_obj is None:
                            deferred.append(t["name"])
                            continue
                        victim_obj.enabled = False  # add_theme의 commit에 함께 실림
                        evicted.add(victim["name"])
                        active_count -= 1

                ok, msg = await theme_radar_service.add_theme(
                    session, t["name"], ",".join(t["keywords"])
                )
                if ok:
                    registered.append(t)
                    active_count += 1
                    if victim_obj is not None:
                        replaced.append((victim, t["name"]))
                        logger.info("저생산성 테마 교체: %s → %s", victim["name"], t["name"])
                    if on_probation:
                        probation.append(t["name"])
                        logger.info("임시 초과 등록(🔥🔥🔥): %s (활성 %d)", t["name"], active_count)
                    logger.info("신규 테마 자동 등록: %s", t["name"])
                else:
                    if victim_obj is not None:
                        victim_obj.enabled = True
                        evicted.discard(victim["name"])
                        active_count += 1
                    logger.warning("신규 테마 등록 스킵: %s", msg)
                    manual.append((t, msg))

        summary = format_auto_register_report(
            registered=registered,
            replaced=replaced,
            deferred=deferred,
            manual=manual,
            skipped_dup=skipped_dup,
            active_count=active_count,
            probation=probation,
        )
        return [t["name"] for t in registered], summary
    except Exception:
        logger.exception("테마 자동 등록 실패 (발굴 메시지는 정상)")
        return [], ""


# ── 텔레그램 리포트 ─────────────────────────────────────────────────


async def send_weekly_theme_report() -> None:
    """주간 테마 발굴 리포트 (스케줄러에서 호출)

    - 발굴 결과 중 키워드 4원칙 통과분만 자동 등록 (auto_register_themes —
      상한 초과 시 저생산성 테마 교체, 불통과분은 /theme-add 수동 제안)
    - 빈도 분석 + 시장 주목 검증 (TOP 5)
    - 결과 메시지에 등록/교체/보류/수동확인 요약 + ✅/⚠️ 마크 추가
    """
    logger.info("주간 테마 발굴 리포트 시작")

    result = await discover_themes(days=30)

    if "error" in result:
        await telegram_service.send_text(
            f"⚠️ 주간 테마 발굴 실패: {result['error']}"
        )
        return

    # 주간 경로는 4원칙 통과분 자동 등록 (상한 내·교체). 수동 /theme-discover는 승인 게이트 유지.
    _registered, suggest_summary = await auto_register_themes(result["analysis"])

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

    # 자동 등록 요약 (등록/교체/보류/수동확인)
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


async def deactivate_stale_themes(inactive_days: int = 42) -> list[str]:
    """휴면 테마 자동 비활성화 (삭제 아님 — 감지 이력 보존).

    기준 (3개 모두 충족):
    - enabled=True
    - 생성 후 inactive_days일 이상 경과
    - 최근 inactive_days일간 ThemeDetection 0건

    기본 42일(6주) 근거: ~3개월 데이터 축적 초기 단계라 28일은 분기 실적·정책
    사이클 등 계절성 테마를 조기에 죽일 위험 → 6주로 완화.

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
                .where(ThemeDetection.is_active.is_(True))
                # NO 판정 기록은 "활동"으로 치지 않음 (NULL=레거시 YES)
                .where(
                    (ThemeDetection.verdict.is_(None))
                    | (ThemeDetection.verdict != "NO")
                )
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


async def retire_low_yield_themes(
    grace_days: int = 42,
    window_days: int = RETIRE_WINDOW_DAYS,
) -> list[str]:
    """저수율 테마 자동 비활성화 (삭제 아님 — 감지 이력 보존).

    기준 (4개 모두 충족):
    - enabled=True
    - 생성 후 grace_days일 이상 경과 (계절성·신규 테마 보호)
    - 최근 window_days일 AI 검증 수율 < RETIRE_YIELD_THRESHOLD
    - 최근 window_days일 수혜주 산출(ThemeScanResult) 0건

    수율 표본이 RETIRE_MIN_VERDICTS건 미만이면 판정을 보류한다. 감지가 적은
    테마를 우연한 0건으로 죽이는 것을 막기 위함.

    Returns: 비활성화된 테마명 리스트.
    """
    from app.models.theme import Theme, ThemeDetection, ThemeScanResult

    cutoff = now_kst_naive() - timedelta(days=window_days)
    grace_cutoff = now_kst_naive() - timedelta(days=grace_days)
    scan_cutoff = today_kst() - timedelta(days=window_days)
    retired: list[str] = []

    async with async_session() as session:
        result = await session.execute(
            select(Theme).where(Theme.enabled == True)  # noqa: E712
        )
        themes = list(result.scalars().all())

        for theme in themes:
            if theme.created_at is None or theme.created_at > grace_cutoff:
                continue

            # 최근 window_days일 AI 검증 수율
            verdict_result = await session.execute(
                select(ThemeDetection.verdict)
                .where(ThemeDetection.theme_id == theme.id)
                .where(ThemeDetection.detected_at >= cutoff)
                .where(ThemeDetection.is_active.is_(True))
                .where(ThemeDetection.verdict.isnot(None))
            )
            verdicts = list(verdict_result.scalars().all())
            if len(verdicts) < RETIRE_MIN_VERDICTS:
                continue  # 표본 부족 — 판정 보류

            yield_rate = sum(1 for v in verdicts if v == "YES") / len(verdicts)
            if yield_rate >= RETIRE_YIELD_THRESHOLD:
                continue

            # 최근 window_days일 수혜주 산출
            scan_result = await session.execute(
                select(func.count(ThemeScanResult.id))
                .where(ThemeScanResult.theme_name == theme.name)
                .where(ThemeScanResult.scan_date >= scan_cutoff)
                .where(ThemeScanResult.is_active.is_(True))
            )
            if (scan_result.scalar() or 0) > 0:
                continue

            theme.enabled = False
            retired.append(theme.name)
            logger.info(
                "저수율 테마 비활성화: %s (수율 %.1f%%, 표본 %d건, 수혜주 0건)",
                theme.name, yield_rate * 100, len(verdicts),
            )

        if retired:
            await session.commit()

    return retired
