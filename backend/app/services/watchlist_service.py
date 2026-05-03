"""관심종목 관리"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Any

import FinanceDataReader as fdr
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


def _get_stock_price_sync(
    stock_code: str, target_date: date | None = None
) -> dict[str, Any] | None:
    """FinanceDataReader로 종목 가격 조회 — 동기 함수

    target_date가 지정되면 그 일자 기준 종가/등락 (백필용).
    """
    try:
        anchor = target_date or datetime.now().date()
        start = (anchor - timedelta(days=14)).strftime("%Y-%m-%d")
        end = (anchor + timedelta(days=1)).strftime("%Y-%m-%d")
        df = fdr.DataReader(stock_code, start, end)
        if len(df) < 1:
            return None

        if target_date is not None:
            df = df[df.index.date <= target_date]
            if df.empty:
                return None

        close = float(df["Close"].iloc[-1])
        if len(df) >= 2:
            prev_close = float(df["Close"].iloc[-2])
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


async def _get_stock_price(
    stock_code: str, target_date: date | None = None
) -> dict[str, Any] | None:
    """FDR 동기 호출을 스레드풀로 실행"""
    return await asyncio.to_thread(_get_stock_price_sync, stock_code, target_date)


async def check_watchlist(
    session: AsyncSession, target_date: date | None = None
) -> list[dict[str, Any]]:
    """관심종목별 변동사항 체크 (target_date 지정 시 해당 일자 기준 백필)"""
    items = await list_all(session)
    if not items:
        return []

    # DART 공시 한 번만 조회 (target_date 전파)
    all_disclosures = await dart_collector.get_today_disclosures(target_date=target_date)

    # 시세 일괄 병렬 조회
    price_results = await asyncio.gather(
        *[_get_stock_price(w.stock_code, target_date) for w in items],
        return_exceptions=True,
    )
    price_map: dict[str, dict[str, Any] | None] = {}
    for w, result in zip(items, price_results):
        price_map[w.stock_code] = result if not isinstance(result, Exception) else None

    results: list[dict[str, Any]] = []
    for w in items:
        check: dict[str, Any] = {
            "stock_code": w.stock_code,
            "stock_name": w.stock_name,
        }

        # 1. 주가 등락 (일괄 조회 결과 사용)
        price = price_map.get(w.stock_code)
        check["price"] = price if price else None

        # 2. 뉴스 (네이버 검색 — 상위 2건)
        try:
            display = 100 if target_date is not None else 10
            news = await news_collector._fetch_naver_news(w.stock_name, display=display)
            if target_date is not None:
                news = [
                    n for n in news
                    if news_collector._parse_pub_date(n.get("published", "")) == target_date
                ]
            filtered = [n for n in news if w.stock_name in n["title"]]
            if not filtered:
                filtered = [n for n in news if w.stock_code in n["title"]]
            check["news"] = [
                {"title": n["title"], "link": n.get("link", "")}
                for n in filtered[:2]
            ]
        except Exception:
            check["news"] = []

        # 3. DART 공시 (stock_code 또는 corp_name 매칭)
        matched = [
            d for d in all_disclosures
            if d.get("stock_code") == w.stock_code
            or (w.stock_name and w.stock_name in d.get("corp_name", ""))
        ]
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
