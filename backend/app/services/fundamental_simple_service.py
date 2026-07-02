"""펀더멘털 최소 서비스 — 캐시 우선, 14일 freshness."""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from sqlalchemy import select

from app.collectors import dart_financial_simple
from app.database import async_session
from app.models.fundamental_cache import FundamentalSimple, StockCorpMap

logger = logging.getLogger(__name__)


FUNDAMENTAL_FRESH_DAYS = 14


async def get_corp_code(stock_code: str) -> Optional[str]:
    """stock_code → corp_code (DART 공시 누적 캐시에서 조회).

    캐시 miss 시 None — 해당 종목 펀더 점수는 중립(50점) 처리.
    운영하며 공시 발생 시 자연스럽게 캐시 누적.
    """
    async with async_session() as session:
        result = await session.execute(
            select(StockCorpMap).where(StockCorpMap.stock_code == stock_code)
        )
        row = result.scalar_one_or_none()
        return row.corp_code if row else None


async def update_corp_map(
    stock_code: str, corp_code: str, corp_name: str
) -> None:
    """DART 공시에서 corp_code 발견 시 호출 — idempotent."""
    if not stock_code or not corp_code:
        return
    async with async_session() as session:
        result = await session.execute(
            select(StockCorpMap).where(StockCorpMap.stock_code == stock_code)
        )
        row = result.scalar_one_or_none()
        if row:
            row.corp_code = corp_code
            row.corp_name = corp_name
            row.last_seen = datetime.now()
        else:
            session.add(StockCorpMap(
                stock_code=stock_code, corp_code=corp_code, corp_name=corp_name,
            ))
        await session.commit()


async def get_or_fetch_fundamental(
    stock_code: str,
) -> Optional[FundamentalSimple]:
    """캐시 우선, miss/stale 시 DART 직접 조회."""
    corp_code = await get_corp_code(stock_code)
    if not corp_code:
        return None  # corp_code 모름 → 펀더 점수 중립 처리

    today = date.today()
    async with async_session() as session:
        result = await session.execute(
            select(FundamentalSimple)
            .where(FundamentalSimple.stock_code == stock_code)
            .order_by(
                FundamentalSimple.year.desc(),
                FundamentalSimple.quarter.desc(),
            )
            .limit(1)
        )
        cached = result.scalar_one_or_none()
        if cached and (today - cached.fetched_at.date()).days < FUNDAMENTAL_FRESH_DAYS:
            return cached

    # DART 조회
    data = await dart_financial_simple.fetch_quarterly_simple(corp_code)
    if not data or not any(data.values()):
        return cached  # 실패 → stale라도 반환

    revenue = data.get("revenue")
    operating_profit = data.get("operating_profit")
    net_income = data.get("net_income")

    operating_margin = None
    if revenue and revenue > 0 and operating_profit is not None:
        operating_margin = round((operating_profit / revenue) * 100, 2)

    is_profitable = None
    if net_income is not None:
        is_profitable = net_income > 0

    from app.collectors.dart_financial_simple import _current_year_quarter
    year, quarter = _current_year_quarter()

    async with async_session() as session:
        existing = await session.execute(
            select(FundamentalSimple)
            .where(FundamentalSimple.stock_code == stock_code)
            .where(FundamentalSimple.year == year)
            .where(FundamentalSimple.quarter == quarter)
        )
        row = existing.scalar_one_or_none()
        if row:
            row.revenue = revenue
            row.operating_profit = operating_profit
            row.net_income = net_income
            row.operating_margin_pct = operating_margin
            row.is_profitable = is_profitable
            row.fetched_at = datetime.now()
        else:
            row = FundamentalSimple(
                stock_code=stock_code,
                corp_code=corp_code,
                year=year,
                quarter=quarter,
                revenue=revenue,
                operating_profit=operating_profit,
                net_income=net_income,
                operating_margin_pct=operating_margin,
                is_profitable=is_profitable,
            )
            session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


def calculate_score(fs: Optional[FundamentalSimple]) -> float:
    """펀더멘털 점수 0-100.

    데이터 없음 → 50 (중립)
    적자 → 20
    흑자 + 영업이익률 미상 → 60
    흑자 + 영업이익률 0-5% → 65
    흑자 + 영업이익률 5-10% → 75
    흑자 + 영업이익률 10-20% → 85
    흑자 + 영업이익률 20%+ → 95
    """
    if fs is None:
        return 50.0

    if fs.is_profitable is False:
        return 20.0

    if fs.is_profitable is True:
        if fs.operating_margin_pct is None:
            return 60.0
        margin = fs.operating_margin_pct
        if margin >= 20:
            return 95.0
        if margin >= 10:
            return 85.0
        if margin >= 5:
            return 75.0
        if margin >= 0:
            return 65.0
        return 40.0  # 영업적자지만 당기순이익 흑자 (이례)

    return 50.0
