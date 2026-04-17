"""아카이브 기반 테마 자동 발굴 — 누적 뉴스/공시에서 AI가 테마 감지"""
from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import date, timedelta
from typing import Any

import anthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.stock_search import search_stocks
from app.config import settings
from app.database import async_session
from app.models.brief import DailyBrief
from app.services import telegram_service

logger = logging.getLogger(__name__)

STOCK_NAME_PATTERN = re.compile(r"([가-힣][가-힣A-Za-z0-9]{1,14})")

STOPWORDS = {
    "한국", "미국", "중국", "일본", "유럽", "코스피", "코스닥",
    "증시", "시장", "투자", "기업", "정부", "대통령", "장관", "위원회",
    "분석", "전망", "예상", "발표", "공시", "뉴스", "기사", "매출", "실적",
    "영업이익", "순이익", "주가", "주식", "종목", "거래", "상승", "하락",
    "오늘", "내일", "어제", "금주", "이번", "지난", "최근",
}


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


async def analyze_stock_frequency(days: int = 30) -> list[dict[str, Any]]:
    """최근 N일 동안 뉴스에서 가장 많이 언급된 종목 TOP 20"""
    async with async_session() as session:
        archives = await _get_recent_archives(session, days)

    if not archives:
        return []

    name_counter: Counter[str] = Counter()
    name_dates: dict[str, set[str]] = {}

    for brief in archives:
        news_raw = brief.news_raw or []
        date_str = brief.date.isoformat()
        for news in news_raw:
            title = news.get("title", "")
            candidates = set(STOCK_NAME_PATTERN.findall(title))
            for candidate in candidates:
                if candidate in STOPWORDS or len(candidate) < 2:
                    continue
                name_counter[candidate] += 1
                name_dates.setdefault(candidate, set()).add(date_str)

    top_candidates = name_counter.most_common(50)
    verified: list[dict[str, Any]] = []

    for name, count in top_candidates:
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
    return verified


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


# ── 텔레그램 리포트 ─────────────────────────────────────────────────


async def send_weekly_theme_report() -> None:
    """주간 테마 발굴 리포트 (스케줄러에서 호출)"""
    logger.info("주간 테마 발굴 리포트 시작")

    result = await discover_themes(days=30)

    if "error" in result:
        await telegram_service.send_text(
            f"⚠️ 주간 테마 발굴 실패: {result['error']}"
        )
        return

    top_stocks = await analyze_stock_frequency(days=30)

    def escape(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    parts = [
        "🎯 <b>주간 테마 발굴 리포트</b>",
        f"(최근 {result['days']}일 · 뉴스 {result['news_count']}건 · 공시 {result['disclosure_count']}건 분석)",
        "",
        escape(result["analysis"]),
    ]

    if top_stocks:
        parts.append("")
        parts.append("━━━━━━━━━━━━━━━━━━━━")
        parts.append("📊 <b>언급 빈도 TOP 10 (최근 30일)</b>")
        parts.append("")
        for i, s in enumerate(top_stocks[:10], 1):
            parts.append(
                f"{i}. <b>{escape(s['stock_name'])}</b> ({s['stock_code']}) "
                f"— {s['mention_count']}회 · {s['unique_days']}일 언급"
            )

    message = "\n".join(parts)

    await _send_long_message(message)


async def _send_long_message(text: str, max_length: int = 4000) -> None:
    """긴 메시지를 분할해서 텔레그램 전송"""
    if len(text) <= max_length:
        await telegram_service.send_text(text)
        return

    lines = text.split("\n")
    current: list[str] = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1
        if current_len + line_len > max_length:
            if current:
                await telegram_service.send_text("\n".join(current))
            current = [line]
            current_len = line_len
        else:
            current.append(line)
            current_len += line_len

    if current:
        await telegram_service.send_text("\n".join(current))
