"""국내 시장 요약 수집 (yfinance)"""
from __future__ import annotations

import logging
from typing import Any

import yfinance as yf

logger = logging.getLogger(__name__)

DOMESTIC_TICKERS = {
    "kospi": "^KS11",
    "kosdaq": "^KQ11",
}

LABELS = {
    "kospi": "코스피",
    "kosdaq": "코스닥",
}


async def get_domestic_summary() -> dict[str, Any]:
    """코스피/코스닥 종가, 등락률 수집 (일괄 다운로드)"""
    result: dict[str, Any] = {}

    symbols = list(DOMESTIC_TICKERS.values())
    try:
        df = yf.download(symbols, period="2d", group_by="ticker", progress=False, threads=True)
    except Exception:
        logger.exception("yfinance 국내 시장 다운로드 실패")
        return result

    for key, ticker in DOMESTIC_TICKERS.items():
        try:
            if len(symbols) == 1:
                hist = df
            else:
                hist = df[ticker]

            close_series = hist["Close"].dropna()
            if len(close_series) < 1:
                logger.warning("데이터 없음: %s", key)
                continue

            close = float(close_series.iloc[-1])
            if len(close_series) >= 2:
                prev_close = float(close_series.iloc[-2])
                change = close - prev_close
                change_pct = (change / prev_close) * 100
            else:
                change = 0.0
                change_pct = 0.0

            result[key] = {
                "label": LABELS[key],
                "close": round(close, 2),
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
            }
        except Exception:
            logger.exception("국내 시장 데이터 파싱 실패: %s", key)

    logger.info("국내 시장 수집 완료: %d/%d", len(result), len(DOMESTIC_TICKERS))
    return result
