"""yfinance를 사용한 미국 시장 데이터 수집 (sync — 호출 측에서 to_thread).

핵심 설계 원칙:
- fail-soft: 한 종목/지표 실패해도 나머지는 진행
- **카테고리별 yf.download 일괄 호출** — Yahoo rate limit 회피
  (ETF 5+매크로 4+빅네임 7+선물 1 = 17 req → 카테고리 4회 download + 시간외 8회 = 약 12 req)
- 시간외(`fast_info`)는 빅네임/선물에만 필요 → 개별 호출 유지
- 휴장일/주말 자동 처리 (period="5d"로 충분한 윈도우 확보)
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

import pandas as pd
import yfinance as yf

from .mappings import BIG_NAMES, ETF_MAPPING, MACRO_INDICATORS, SP500_FUTURES

logger = logging.getLogger(__name__)


def _bulk_download(tickers: list[str]) -> Optional[pd.DataFrame]:
    """여러 ticker history를 한 번의 HTTP 요청으로 수집.

    yf.download(["A","B"], group_by='ticker') → MultiIndex columns DataFrame.
    실패/빈 결과 → None.
    """
    if not tickers:
        return None
    try:
        df = yf.download(
            tickers,
            period="5d",
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=False,
        )
    except Exception as e:
        logger.error("[us_market] bulk download failed (%s): %s", tickers, e)
        return None
    if df is None or df.empty:
        logger.warning("[us_market] bulk download empty (%s)", tickers)
        return None
    return df


def _extract_history_metrics(
    df: pd.DataFrame, ticker: str, single_ticker: bool = False
) -> Optional[dict[str, float]]:
    """multi-ticker DataFrame에서 단일 ticker의 종가/변동률 추출.

    Args:
        df: yf.download 결과 (MultiIndex columns 또는 단일 ticker시 평면)
        ticker: 추출할 ticker 코드
        single_ticker: 호출 시 ticker 1개였으면 True (column 구조 평면)

    Returns:
        {"regular_close": float, "regular_change_pct": float} or None
    """
    try:
        if single_ticker:
            # ticker 1개 download — columns: Open/High/Low/Close/Volume
            close_series = df["Close"].dropna()
        else:
            # MultiIndex: df[ticker] → ticker별 sub-frame
            if isinstance(df.columns, pd.MultiIndex):
                if ticker not in df.columns.get_level_values(0):
                    return None
                close_series = df[ticker]["Close"].dropna()
            else:
                # group_by='ticker'인데 단일 ticker로 평면 반환된 케이스 (yfinance quirk)
                close_series = df["Close"].dropna()
    except Exception as e:
        logger.warning("[us_market] %s extract failed: %s", ticker, e)
        return None

    if close_series.empty:
        return None

    try:
        regular_close = float(close_series.iloc[-1])
        regular_prev = (
            float(close_series.iloc[-2]) if len(close_series) >= 2 else regular_close
        )
        change_pct = (
            (regular_close - regular_prev) / regular_prev * 100 if regular_prev else 0.0
        )
        return {
            "regular_close": regular_close,
            "regular_change_pct": round(change_pct, 2),
        }
    except Exception as e:
        logger.warning("[us_market] %s metrics calc failed: %s", ticker, e)
        return None


def _fetch_prepost_price(ticker: str) -> Optional[float]:
    """단일 ticker의 시간외/실시간 가격 (yf.Ticker.fast_info).

    빅네임/선물에만 호출 — ETF/매크로는 시간외 무의미.
    """
    try:
        t = yf.Ticker(ticker)
        fast = t.fast_info
        last_price = None
        try:
            last_price = fast.get("last_price")  # type: ignore[union-attr]
        except Exception:
            last_price = getattr(fast, "last_price", None)
        return float(last_price) if last_price else None
    except Exception as e:
        logger.debug("[us_market] %s prepost fetch skip: %s", ticker, e)
        return None


def _build_record(
    ticker: str,
    metrics: dict[str, float],
    prepost_price: Optional[float] = None,
) -> dict[str, Any]:
    """history 메트릭 + 시간외 가격 → 표준 record dict."""
    regular_close = metrics["regular_close"]
    prepost_change_pct: Optional[float] = None
    if prepost_price is not None and prepost_price != regular_close and regular_close:
        prepost_change_pct = round(
            (prepost_price - regular_close) / regular_close * 100, 2
        )
    return {
        "ticker": ticker,
        "regular_close": regular_close,
        "regular_change_pct": metrics["regular_change_pct"],
        "prepost_price": prepost_price,
        "prepost_change_pct": prepost_change_pct,
        "fetched_at": datetime.now().isoformat(),
    }


def fetch_etf_sectors() -> list[dict[str, Any]]:
    """ETF 섹터 데이터 수집 (시간외 미사용)."""
    tickers = list(ETF_MAPPING.keys())
    df = _bulk_download(tickers)
    if df is None:
        return []

    results: list[dict[str, Any]] = []
    for ticker in tickers:
        metrics = _extract_history_metrics(df, ticker, single_ticker=len(tickers) == 1)
        if metrics is None:
            continue
        mapping = ETF_MAPPING[ticker]
        results.append({
            **_build_record(ticker, metrics),
            "name": mapping["name"],
            "category": mapping["category"],
            "kr_stocks": mapping["kr_stocks"],
            "kr_themes": mapping["kr_themes"],
            "note": mapping.get("note", ""),
            "type": "etf",
        })
    results.sort(key=lambda x: abs(x["regular_change_pct"]), reverse=True)
    return results


def fetch_big_names() -> list[dict[str, Any]]:
    """빅네임 종목 데이터 수집 (history 일괄 + 시간외 개별)."""
    tickers = list(BIG_NAMES.keys())
    df = _bulk_download(tickers)
    if df is None:
        return []

    results: list[dict[str, Any]] = []
    for ticker in tickers:
        metrics = _extract_history_metrics(df, ticker, single_ticker=len(tickers) == 1)
        if metrics is None:
            continue
        prepost_price = _fetch_prepost_price(ticker)
        record = _build_record(ticker, metrics, prepost_price=prepost_price)

        mapping = BIG_NAMES[ticker]
        regular_abs = abs(record["regular_change_pct"])
        prepost_abs = abs(record["prepost_change_pct"] or 0)
        is_alert = (
            regular_abs >= mapping["alert_threshold"]
            or prepost_abs >= mapping["alert_threshold"]
        )
        results.append({
            **record,
            "name": mapping["name"],
            "kr_stocks": mapping["kr_stocks"],
            "relation": mapping.get("relation", ""),
            "kr_themes": mapping["kr_themes"],
            "alert_threshold": mapping["alert_threshold"],
            "is_alert": is_alert,
            "type": "big_name",
        })
    results.sort(key=lambda x: abs(x["regular_change_pct"]), reverse=True)
    return results


def fetch_macro_indicators() -> list[dict[str, Any]]:
    """매크로 지표 수집 (시간외 미사용)."""
    tickers = list(MACRO_INDICATORS.keys())
    df = _bulk_download(tickers)
    if df is None:
        return []

    results: list[dict[str, Any]] = []
    for ticker in tickers:
        metrics = _extract_history_metrics(df, ticker, single_ticker=len(tickers) == 1)
        if metrics is None:
            continue
        mapping = MACRO_INDICATORS[ticker]
        results.append({
            **_build_record(ticker, metrics),
            "name": mapping["name"],
            "category": mapping["category"],
            "implication_up": mapping["implication_up"],
            "implication_down": mapping["implication_down"],
            "alert_threshold": mapping["alert_threshold"],
            "format": mapping["format"],
            "is_yield": mapping.get("is_yield", False),
            "warning_levels": mapping.get("warning_levels"),
            "kr_related": mapping.get("kr_related", []),
            "type": "macro",
        })
    return results


def fetch_sp500_futures() -> Optional[dict[str, Any]]:
    """S&P500 선물 (한국 갭 예측 시그널). 단일 ticker라 download도 1 req."""
    ticker = "ES=F"
    df = _bulk_download([ticker])
    if df is None:
        return None
    metrics = _extract_history_metrics(df, ticker, single_ticker=True)
    if metrics is None:
        return None
    prepost_price = _fetch_prepost_price(ticker)
    record = _build_record(ticker, metrics, prepost_price=prepost_price)
    mapping = SP500_FUTURES[ticker]
    return {
        **record,
        "name": mapping["name"],
        "category": mapping["category"],
        "implication": mapping["implication"],
        "type": "futures",
    }


def fetch_all() -> dict[str, Any]:
    """모든 데이터 한 번에 수집 (모닝브리프에서 호출).

    HTTP 호출 수:
    - ETF bulk: 1
    - 매크로 bulk: 1
    - 빅네임 bulk: 1 + 시간외 7 = 8
    - 선물 bulk: 1 + 시간외 1 = 2
    - 합계: 약 12 req (기존 34 req에서 65% 감소)
    """
    return {
        "etf": fetch_etf_sectors(),
        "big_names": fetch_big_names(),
        "macro": fetch_macro_indicators(),
        "sp500_futures": fetch_sp500_futures(),
        "fetched_at": datetime.now().isoformat(),
    }
