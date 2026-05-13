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
from app.services import (
    ai_summarizer,
    investor_flow_service,
    market_risk_simple,
    watchlist_service,
)

logger = logging.getLogger(__name__)


async def _safe_collect(name: str, coro, default=None):
    """개별 수집 실패가 전체를 중단하지 않도록"""
    try:
        return await coro
    except Exception:
        logger.exception("수집 실패 [%s] — 기본값 사용", name)
        return default if default is not None else {}


async def _diagnose_market_risk(global_market: dict[str, Any]) -> dict[str, Any]:
    """P0-5 위험 진단 헬퍼 — 외인 5일 흐름 함께 조회."""
    flow_history = await market_risk_simple.get_investor_flow_history(days=5)
    return await market_risk_simple.diagnose_simple(
        global_market=global_market,
        investor_flow_history=flow_history,
    )


async def generate_daily_brief(
    session: AsyncSession, target_date: date | None = None
) -> DailyBrief:
    """매일 아침 브리프 생성 파이프라인 (target_date 지정 시 백필)"""

    brief_date = target_date or date.today()

    # 1. 데이터 수집 (개별 실패 허용)
    logger.info("브리프 생성 시작 (date=%s)", brief_date)
    global_market, domestic_market, news_items, dart_items = await asyncio.gather(
        _safe_collect(
            "global_market", market_collector.get_global_summary(target_date=target_date), {}
        ),
        _safe_collect(
            "domestic_market",
            stock_collector.get_domestic_summary(target_date=target_date),
            {},
        ),
        _safe_collect(
            "news", news_collector.get_today_news(limit=20, target_date=target_date), []
        ),
        _safe_collect(
            "dart", dart_collector.get_today_disclosures(target_date=target_date), []
        ),
    )

    # 2. 수급 데이터 (P0-2)
    investor_flow = await _safe_collect(
        "investor_flow",
        investor_flow_service.get_today_flow_summary(target_date=target_date),
        {},
    )

    # 3. 시장 위험 모드 진단 (P0-5)
    market_risk = await _safe_collect(
        "market_risk",
        _diagnose_market_risk(global_market),
        {"level": "정상", "factors": [], "score": 0},
    )

    # 4. AI 요약 (P0-1: 전문가 5섹션 브리프, P0-5 위험 모드 주입)
    news_summary = await _safe_collect(
        "ai_summary",
        ai_summarizer.generate_expert_brief(
            global_market=global_market,
            domestic_market=domestic_market,
            investor_flow=investor_flow,
            news_items=news_items,
            disclosure_items=dart_items,
            market_risk=market_risk,
        ),
        "AI 요약을 생성하지 못했습니다.",
    )

    # 3. 관심종목 체크
    watchlist_data = await _safe_collect(
        "watchlist", watchlist_service.check_watchlist(session, target_date=target_date), []
    )

    # 4. 브리프 조립
    brief = DailyBrief(
        date=brief_date,
        global_market=global_market,
        domestic_market=domestic_market,
        news_summary=news_summary,
        news_raw=news_items,
        disclosures=dart_items,
        watchlist_check=watchlist_data,
        investor_flow=investor_flow,
        market_risk=market_risk,
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
