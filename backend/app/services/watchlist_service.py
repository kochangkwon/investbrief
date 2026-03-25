"""관심종목 관리"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

import yfinance as yf
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors import dart_collector, news_collector
from app.models.watchlist import Watchlist

logger = logging.getLogger(__name__)


async def add(session: AsyncSession, stock_code: str, stock_name: str, memo: str | None = None) -> Watchlist:
    """관심종목 추가"""
    item = Watchlist(
        stock_code=stock_code,
        stock_name=stock_name,
        memo=memo,
        created_at=datetime.now(),
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    logger.info("관심종목 추가: %s (%s)", stock_name, stock_code)
    return item


async def remove(session: AsyncSession, stock_code: str) -> bool:
    """관심종목 제거"""
    result = await session.execute(
        delete(Watchlist).where(Watchlist.stock_code == stock_code)
    )
    await session.commit()
    deleted = result.rowcount > 0
    if deleted:
        logger.info("관심종목 제거: %s", stock_code)
    return deleted


async def list_all(session: AsyncSession) -> list[Watchlist]:
    """전체 관심종목 조회"""
    result = await session.execute(
        select(Watchlist).order_by(Watchlist.created_at.desc())
    )
    return list(result.scalars().all())


def _get_stock_price_sync(stock_code: str) -> dict[str, Any] | None:
    """yfinance로 종목 가격 조회 (KRX) — 동기 함수"""
    ticker = f"{stock_code}.KS"
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="2d")
        if len(hist) < 1:
            # 코스닥 시도
            ticker = f"{stock_code}.KQ"
            t = yf.Ticker(ticker)
            hist = t.history(period="2d")
            if len(hist) < 1:
                return None

        close = float(hist["Close"].iloc[-1])
        if len(hist) >= 2:
            prev_close = float(hist["Close"].iloc[-2])
            change = close - prev_close
            change_pct = (change / prev_close) * 100
        else:
            change = 0.0
            change_pct = 0.0

        return {
            "close": round(close, 0),
            "change": round(change, 0),
            "change_pct": round(change_pct, 2),
        }
    except Exception:
        logger.warning("주가 조회 실패: %s", stock_code)
        return None


async def _get_stock_price(stock_code: str) -> dict[str, Any] | None:
    """yfinance 동기 호출을 스레드풀로 실행"""
    return await asyncio.to_thread(_get_stock_price_sync, stock_code)


async def check_watchlist(session: AsyncSession) -> list[dict[str, Any]]:
    """관심종목별 오늘의 변동사항 체크"""
    items = await list_all(session)
    if not items:
        return []

    # DART 공시 한 번만 조회
    all_disclosures = await dart_collector.get_today_disclosures()

    results: list[dict[str, Any]] = []
    for w in items:
        check: dict[str, Any] = {
            "stock_code": w.stock_code,
            "stock_name": w.stock_name,
        }

        # 1. 주가 등락
        price = await _get_stock_price(w.stock_code)
        if price:
            check["price"] = price
        else:
            check["price"] = None

        # 2. 뉴스 (네이버 검색 — 상위 2건)
        try:
            news = await news_collector._fetch_naver_news(w.stock_name)
            check["news"] = [n["title"] for n in news[:2]]
        except Exception:
            check["news"] = []

        # 3. DART 공시
        matched = [d for d in all_disclosures if d.get("stock_code") == w.stock_code]
        check["disclosures"] = [
            {"title": d["title"], "importance": d["importance"]}
            for d in matched[:5]
        ]

        # 4. 요약 텍스트
        parts = []
        if price:
            sign = "+" if price["change_pct"] > 0 else ""
            parts.append(f"{int(price['close']):,}원 ({sign}{price['change_pct']}%)")
        if check["news"]:
            parts.append(f"뉴스 {len(check['news'])}건")
        else:
            parts.append("뉴스 없음")
        if matched:
            parts.append(f"공시 {len(matched)}건")
        check["summary"] = " | ".join(parts)

        results.append(check)
        logger.info("관심종목 체크: %s — %s", w.stock_name, check["summary"])

    return results
