"""브리프 생성 오케스트레이터"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors import dart_collector, market_collector, news_collector, stock_collector
from app.models.brief import DailyBrief
from app.services import ai_summarizer, watchlist_service

logger = logging.getLogger(__name__)


async def _safe_collect(name: str, coro, default=None):
    """개별 수집 실패가 전체를 중단하지 않도록"""
    try:
        return await coro
    except Exception:
        logger.exception("수집 실패 [%s] — 기본값 사용", name)
        return default if default is not None else {}


async def generate_daily_brief(session: AsyncSession) -> DailyBrief:
    """매일 아침 브리프 생성 파이프라인"""

    # 1. 데이터 수집 (개별 실패 허용)
    logger.info("브리프 생성 시작")
    global_market, domestic_market, news_items, dart_items = await asyncio.gather(
        _safe_collect("global_market", market_collector.get_global_summary(), {}),
        _safe_collect("domestic_market", stock_collector.get_domestic_summary(), {}),
        _safe_collect("news", news_collector.get_today_news(limit=20), []),
        _safe_collect("dart", dart_collector.get_today_disclosures(), []),
    )

    # 2. AI 요약
    news_summary = await _safe_collect(
        "ai_summary", ai_summarizer.summarize_news(news_items), "AI 요약을 생성하지 못했습니다."
    )

    # 3. 관심종목 체크
    watchlist_data = await _safe_collect("watchlist", watchlist_service.check_watchlist(session), [])

    # 4. 브리프 조립
    brief = DailyBrief(
        date=date.today(),
        global_market=global_market,
        domestic_market=domestic_market,
        news_summary=news_summary,
        news_raw=news_items,
        disclosures=dart_items,
        watchlist_check=watchlist_data,
        created_at=datetime.now(),
    )

    # 5. DB 저장
    session.add(brief)
    await session.commit()
    await session.refresh(brief)
    logger.info("브리프 생성 완료: %s", brief.date)

    return brief


async def get_brief_by_date(session: AsyncSession, target_date: date) -> DailyBrief | None:
    """특정일 브리프 조회"""
    result = await session.execute(
        select(DailyBrief).where(DailyBrief.date == target_date)
    )
    return result.scalar_one_or_none()


async def get_recent_briefs(session: AsyncSession, days: int = 7) -> list[dict[str, Any]]:
    """최근 N일 브리프 목록 (요약)"""
    result = await session.execute(
        select(DailyBrief).order_by(DailyBrief.date.desc()).limit(days)
    )
    briefs = result.scalars().all()
    return [
        {
            "id": b.id,
            "date": b.date.isoformat(),
            "news_summary": b.news_summary[:100] + "..." if len(b.news_summary) > 100 else b.news_summary,
            "created_at": b.created_at.isoformat(),
        }
        for b in briefs
    ]
