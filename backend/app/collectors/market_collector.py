"""해외 시장 데이터 수집 (yfinance)"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import yfinance as yf

logger = logging.getLogger(__name__)

TICKERS = {
    "sp500": "^GSPC",
    "nasdaq": "^IXIC",
    "dow": "^DJI",
    "nikkei": "^N225",
    "shanghai": "000001.SS",
    "vix": "^VIX",
    "usdkrw": "KRW=X",
    "wti": "CL=F",
    "gold": "GC=F",
    "us10y": "^TNX",
}

LABELS = {
    "sp500": "S&P 500",
    "nasdaq": "나스닥",
    "dow": "다우존스",
    "nikkei": "니케이 225",
    "shanghai": "상해종합",
    "vix": "VIX",
    "usdkrw": "원/달러",
    "wti": "WTI 유가",
    "gold": "금 선물",
    "us10y": "미국 10년물",
}


async def get_global_summary(target_date: date | None = None) -> dict[str, Any]:
    """해외지수/환율/원자재 요약 데이터 수집 (일괄 다운로드)

    target_date가 지정되면 해당 일자 기준 종가/등락률을 반환 (백필용).
    기준일에 데이터가 없으면 그 이전 가장 가까운 거래일 사용.
    """
    result: dict[str, Any] = {}

    symbols = list(TICKERS.values())
    try:
        if target_date is None:
            df = yf.download(symbols, period="2d", group_by="ticker", progress=False, threads=True)
        else:
            # 기준일 기준 직전 ~10일 범위로 받아서 마지막 2일 사용 (휴장/주말 흡수)
            start = (target_date - timedelta(days=10)).isoformat()
            end = (target_date + timedelta(days=1)).isoformat()
            df = yf.download(
                symbols, start=start, end=end, group_by="ticker", progress=False, threads=True
            )
    except Exception:
        logger.exception("yfinance 일괄 다운로드 실패")
        return result

    for key, ticker in TICKERS.items():
        try:
            if len(symbols) == 1:
                hist = df
            else:
                hist = df[ticker]

            close_series = hist["Close"].dropna()
            if target_date is not None:
                # target_date 이하의 데이터만 사용
                close_series = close_series[close_series.index.date <= target_date]

            if len(close_series) < 1:
                logger.warning("데이터 없음: %s (%s)", key, ticker)
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
            logger.exception("시장 데이터 파싱 실패: %s", key)

    logger.info("글로벌 시장 수집 완료: %d/%d", len(result), len(TICKERS))
    return result
