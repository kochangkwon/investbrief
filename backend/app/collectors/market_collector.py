"""해외 시장 데이터 수집 (yfinance + Finnhub ETF 프록시 폴백).

yfinance 전체 실패(rate limit 등)가 2026-08-10부터 5거래일 연속 발생해
브리프의 글로벌 섹션·VIX/환율 리스크 시그널이 조용히 비어 나가던 문제 대응:
- 1차 실패 시 짧은 대기 후 1회 재시도 (threads=False — rate limit 완화)
- 지수 3종(sp500/nasdaq/dow)은 Finnhub ETF 프록시(SPY/QQQ/DIA)로 폴백
  (Finnhub 무료 플랜은 지수·매크로 미지원 — ETF quote만 가능)
- VIX·환율 등 나머지는 폴백 불가 → market_risk가 "데이터 없음"을 명시(F3)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

import yfinance as yf

logger = logging.getLogger(__name__)

# Finnhub ETF 프록시 (지수 자체는 무료 플랜 미지원) — 등락률 대용
_FINNHUB_PROXY = {
    "sp500": "SPY",
    "nasdaq": "QQQ",
    "dow": "DIA",
}

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

    def _download(threads: bool):
        if target_date is None:
            return yf.download(
                symbols, period="2d", group_by="ticker", progress=False, threads=threads
            )
        # 기준일 기준 직전 ~10일 범위로 받아서 마지막 2일 사용 (휴장/주말 흡수)
        start = (target_date - timedelta(days=10)).isoformat()
        end = (target_date + timedelta(days=1)).isoformat()
        return yf.download(
            symbols, start=start, end=end, group_by="ticker", progress=False, threads=threads
        )

    df = None
    for attempt, threads in ((1, True), (2, False)):
        try:
            df = await asyncio.to_thread(_download, threads)
            if df is not None and not df.empty:
                break
            logger.warning("yfinance 빈 응답 (시도 %d/2)", attempt)
        except Exception:
            logger.exception("yfinance 일괄 다운로드 실패 (시도 %d/2)", attempt)
        if attempt == 1:
            await asyncio.sleep(3)
    if df is None or df.empty:
        return await _apply_finnhub_proxies(result)

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

    if not result:
        result = await _apply_finnhub_proxies(result)

    logger.info("글로벌 시장 수집 완료: %d/%d", len(result), len(TICKERS))
    return result


async def _apply_finnhub_proxies(result: dict[str, Any]) -> dict[str, Any]:
    """yfinance 전멸 시 지수 3종을 Finnhub ETF 프록시로 채운다.

    프록시임을 label에 명시 — AI·독자가 지수 실측치로 오인하지 않게.
    Finnhub 키 미설정/실패 시 그대로 반환 (F3의 '데이터 없음' 명시가 후속 방어).
    """
    try:
        from app.services.us_market.fetcher_finnhub import _finnhub_quote
    except Exception:
        return result

    filled = 0
    for key, etf in _FINNHUB_PROXY.items():
        if key in result:
            continue
        try:
            quote = await asyncio.to_thread(_finnhub_quote, etf)
        except Exception:
            logger.warning("[finnhub-proxy] %s(%s) 조회 예외", key, etf, exc_info=True)
            continue
        if not quote:
            continue
        close = quote["regular_close"]
        pct = quote["regular_change_pct"]
        result[key] = {
            "label": f"{LABELS[key]} ({etf} 프록시)",
            "close": round(close, 2),
            "change": round(close * pct / (100 + pct), 2) if pct != -100 else 0.0,
            "change_pct": pct,
        }
        filled += 1
    if filled:
        logger.info("[finnhub-proxy] yfinance 실패 → ETF 프록시 %d종 채움", filled)
    return result
