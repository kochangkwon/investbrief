"""KRX 투자자별 매매 + 외인 매수/매도 TOP 종목 (pykrx)."""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _fetch_market_flow_sync(target_date: date) -> Optional[dict[str, float]]:
    """전체 시장(KOSPI+KOSDAQ) 투자자별 순매수 (단위: 억원)."""
    try:
        from pykrx import stock
        date_str = target_date.strftime("%Y%m%d")

        kospi_df = stock.get_market_trading_value_by_investor(
            date_str, date_str, "KOSPI"
        )
        kosdaq_df = stock.get_market_trading_value_by_investor(
            date_str, date_str, "KOSDAQ"
        )

        def _net(df, label: str) -> float:
            try:
                return float(df.loc[label, "순매수"]) / 1e8
            except (KeyError, IndexError):
                return 0.0

        foreign = _net(kospi_df, "외국인") + _net(kosdaq_df, "외국인")
        inst = _net(kospi_df, "기관합계") + _net(kosdaq_df, "기관합계")
        retail = _net(kospi_df, "개인") + _net(kosdaq_df, "개인")

        return {
            "foreign_net_billion": round(foreign, 0),
            "institution_net_billion": round(inst, 0),
            "retail_net_billion": round(retail, 0),
            "trade_date": target_date.isoformat(),
        }
    except Exception:
        logger.exception("KRX 시장 수급 조회 실패 (%s)", target_date)
        return None


def _fetch_top_foreign_traders_sync(
    target_date: date, limit_buy: int = 10, limit_sell: int = 5
) -> list[dict[str, Any]]:
    """외국인 순매수/매도 상위 종목.

    Returns: 매수 TOP + 매도 TOP 통합 리스트
    """
    try:
        from pykrx import stock
        date_str = target_date.strftime("%Y%m%d")

        df_kospi = stock.get_market_net_purchases_of_equities(
            date_str, date_str, "KOSPI", "외국인"
        )
        df_kosdaq = stock.get_market_net_purchases_of_equities(
            date_str, date_str, "KOSDAQ", "외국인"
        )

        items: list[dict[str, Any]] = []
        for df in (df_kospi, df_kosdaq):
            if df is None or df.empty:
                continue
            value_col = None
            for c in df.columns:
                if "순매수" in c and "대금" in c:
                    value_col = c
                    break
            if value_col is None:
                continue
            for code, row in df.iterrows():
                items.append({
                    "stock_code": str(code).zfill(6),
                    "stock_name": str(row.get("종목명", "")),
                    "net_billion": round(float(row[value_col]) / 1e8, 0),
                })

        items.sort(key=lambda x: x["net_billion"], reverse=True)
        buys = items[:limit_buy]
        sells = [i for i in items if i["net_billion"] < 0]
        sells.sort(key=lambda x: x["net_billion"])
        sells = sells[:limit_sell]

        return buys + sells
    except Exception:
        logger.exception("KRX 외인 매수/매도 조회 실패 (%s)", target_date)
        return []


async def get_market_flow(target_date: date) -> Optional[dict[str, float]]:
    return await asyncio.to_thread(_fetch_market_flow_sync, target_date)


async def get_top_foreign_traders(
    target_date: date, limit_buy: int = 10, limit_sell: int = 5
) -> list[dict[str, Any]]:
    return await asyncio.to_thread(
        _fetch_top_foreign_traders_sync, target_date, limit_buy, limit_sell
    )


def latest_trading_date(today: Optional[date] = None) -> date:
    """주말 회피한 직전 거래일."""
    d = today or date.today()
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d - timedelta(days=2)
    yesterday = d - timedelta(days=1)
    if yesterday.weekday() == 6:
        return yesterday - timedelta(days=2)
    if yesterday.weekday() == 5:
        return yesterday - timedelta(days=1)
    return yesterday
