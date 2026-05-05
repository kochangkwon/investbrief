"""관심종목 일일 리포트 (16:30 장 마감 후)"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

from app.collectors import dart_collector, news_collector, price_collector
from app.database import async_session
from app.services import telegram_service, watchlist_service

logger = logging.getLogger(__name__)


def _fetch_stock_data_sync(stock_code: str) -> dict[str, Any] | None:
    """종가/RSI/이동평균/거래량 수집 — 동기 함수.

    raw 시계열은 price_collector.fetch_close_history로 가져온 뒤
    여기서 RSI/MA/거래량 비율을 계산한다 (도메인 로직).
    """
    try:
        start = date.today() - timedelta(days=120)
        df = price_collector.fetch_close_history(stock_code, start=start)
        if df is None or len(df) < 2:
            return None

        close = float(df["Close"].iloc[-1])
        prev_close = float(df["Close"].iloc[-2])
        change = close - prev_close
        change_pct = (change / prev_close) * 100

        # RSI(14일) 계산
        closes = df["Close"]
        delta = closes.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.rolling(window=14, min_periods=14).mean()
        avg_loss = loss.rolling(window=14, min_periods=14).mean()
        rs = avg_gain / avg_loss
        rsi_series = 100 - (100 / (1 + rs))
        rsi = float(rsi_series.iloc[-1]) if len(rsi_series.dropna()) > 0 else None

        # 20일 이동평균 이격률
        ma20 = float(closes.rolling(window=20, min_periods=20).mean().iloc[-1])
        if ma20 > 0:
            ma20_gap = ((close - ma20) / ma20) * 100
        else:
            ma20_gap = None

        # 거래량 비율 (당일 / 5일 평균)
        volumes = df["Volume"]
        today_vol = float(volumes.iloc[-1])
        avg_vol_5 = float(volumes.iloc[-6:-1].mean()) if len(volumes) >= 6 else None
        if avg_vol_5 and avg_vol_5 > 0:
            vol_ratio = today_vol / avg_vol_5
        else:
            vol_ratio = None

        return {
            "close": round(close, 0),
            "change_pct": round(change_pct, 2),
            "rsi": round(rsi, 0) if rsi is not None else None,
            "ma20_gap": round(ma20_gap, 1) if ma20_gap is not None else None,
            "vol_ratio": round(vol_ratio, 1) if vol_ratio is not None else None,
        }
    except Exception:
        logger.warning("리포트 주가 조회 실패: %s", stock_code)
        return None


async def _fetch_stock_data(stock_code: str) -> dict[str, Any] | None:
    """비동기 래퍼"""
    return await asyncio.to_thread(_fetch_stock_data_sync, stock_code)


async def generate_daily_report() -> str | None:
    """관심종목 일일 리포트 생성"""
    async with async_session() as session:
        items = await watchlist_service.list_all(session)

    if not items:
        logger.info("리포트: 관심종목 없음, 스킵")
        return None

    all_disclosures = await dart_collector.get_today_disclosures()
    today_str = date.today().strftime("%m/%d")

    lines = [f"📊 <b>관심종목 일일 리포트</b> ({today_str})", ""]

    for w in items:
        lines.append(f"<b>{telegram_service.escape_html(w.stock_name)}</b> ({w.stock_code})")

        # 주가 데이터
        data = await _fetch_stock_data(w.stock_code)
        if data:
            sign = "+" if data["change_pct"] > 0 else ""
            lines.append(f"  종가 {int(data['close']):,}원 ({sign}{data['change_pct']}%)")

            parts = []
            if data["rsi"] is not None:
                parts.append(f"RSI {int(data['rsi'])}")
            if data["ma20_gap"] is not None:
                gap_sign = "+" if data["ma20_gap"] > 0 else ""
                parts.append(f"20일선 이격 {gap_sign}{data['ma20_gap']}%")
            if data["vol_ratio"] is not None:
                parts.append(f"거래량 {data['vol_ratio']}배")
            if parts:
                lines.append(f"  {' | '.join(parts)}")
        else:
            lines.append("  주가 데이터 없음")

        # 뉴스
        try:
            news = await news_collector._fetch_naver_news(w.stock_name)
            filtered = [n for n in news if w.stock_name in n["title"]]
            if not filtered:
                filtered = [n for n in news if w.stock_code in n["title"]]
            news_items = filtered[:2]
        except Exception:
            news_items = []

        # 공시 (stock_code 또는 corp_name 매칭)
        matched_disc = [
            d for d in all_disclosures
            if d.get("stock_code") == w.stock_code
            or (w.stock_name and w.stock_name in d.get("corp_name", ""))
        ]

        news_str = f"{len(news_items)}건" if news_items else "없음"
        disc_str = f"{len(matched_disc)}건" if matched_disc else "없음"
        lines.append(f"  뉴스: {news_str} | 공시: {disc_str}")
        for n in news_items:
            link = n.get("link", "")
            title = n.get("title", "")
            if link:
                lines.append(f'    • <a href="{link}">{title}</a>')
            else:
                lines.append(f"    • {title}")

        lines.append("")

    return "\n".join(lines)


async def send_daily_report() -> bool:
    """리포트 생성 + 텔레그램 발송"""
    logger.info("일일 리포트 생성 시작")
    try:
        msg = await generate_daily_report()
        if not msg:
            return False

        if len(msg) > 4000:
            msg = msg[:4000] + "\n\n... (전체 내용은 웹에서 확인)"

        result = await telegram_service.send_text(msg)
        logger.info("일일 리포트 발송 완료")
        return result
    except Exception:
        logger.exception("일일 리포트 실패")
        return False
