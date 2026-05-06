"""yfinance를 사용한 미국 시장 데이터 수집 (sync — 호출 측에서 to_thread).

핵심 설계 원칙:
- fail-soft: 한 종목/지표 실패해도 나머지는 진행
- 시간외 거래 포함 (prepost=True)
- 휴장일/주말 자동 처리 (period="5d"로 충분한 윈도우 확보)
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

import yfinance as yf

from .mappings import BIG_NAMES, ETF_MAPPING, MACRO_INDICATORS, SP500_FUTURES

logger = logging.getLogger(__name__)


def _fetch_single(ticker: str, prepost: bool = False) -> Optional[dict[str, Any]]:
    """단일 ticker 정규장 + 시간외 데이터 수집."""
    try:
        t = yf.Ticker(ticker)
        # 정규장 종가 (5일치 → 휴장 안전)
        hist = t.history(period="5d", interval="1d", prepost=False)
        if hist.empty:
            logger.warning("[us_market] %s no regular history", ticker)
            return None

        regular_close = float(hist["Close"].iloc[-1])
        regular_prev = (
            float(hist["Close"].iloc[-2]) if len(hist) >= 2 else regular_close
        )
        regular_change_pct = (
            (regular_close - regular_prev) / regular_prev * 100 if regular_prev else 0.0
        )

        # 시간외/프리마켓 (선택적)
        prepost_change_pct: Optional[float] = None
        prepost_price: Optional[float] = None
        if prepost:
            try:
                fast = t.fast_info
                # yfinance 버전에 따라 dict-like / attribute 접근 모두 지원
                last_price = None
                try:
                    last_price = fast.get("last_price")  # type: ignore[union-attr]
                except Exception:
                    last_price = getattr(fast, "last_price", None)
                if last_price and last_price != regular_close:
                    prepost_price = float(last_price)
                    prepost_change_pct = (
                        (prepost_price - regular_close) / regular_close * 100
                    )
            except Exception as e:
                logger.debug("[us_market] %s prepost fetch skip: %s", ticker, e)

        return {
            "ticker": ticker,
            "regular_close": regular_close,
            "regular_change_pct": round(regular_change_pct, 2),
            "prepost_price": prepost_price,
            "prepost_change_pct": (
                round(prepost_change_pct, 2)
                if prepost_change_pct is not None
                else None
            ),
            "fetched_at": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error("[us_market] %s fetch failed: %s", ticker, e)
        return None


def fetch_etf_sectors() -> list[dict[str, Any]]:
    """ETF 섹터 데이터 수집."""
    results: list[dict[str, Any]] = []
    for ticker in ETF_MAPPING.keys():
        data = _fetch_single(ticker, prepost=False)
        if data is None:
            continue
        mapping = ETF_MAPPING[ticker]
        results.append({
            **data,
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
    """빅네임 종목 데이터 수집 (시간외 포함)."""
    results: list[dict[str, Any]] = []
    for ticker in BIG_NAMES.keys():
        data = _fetch_single(ticker, prepost=True)
        if data is None:
            continue
        mapping = BIG_NAMES[ticker]
        regular_abs = abs(data["regular_change_pct"])
        prepost_abs = abs(data["prepost_change_pct"] or 0)
        is_alert = (
            regular_abs >= mapping["alert_threshold"]
            or prepost_abs >= mapping["alert_threshold"]
        )
        results.append({
            **data,
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
    """매크로 지표 수집."""
    results: list[dict[str, Any]] = []
    for ticker, mapping in MACRO_INDICATORS.items():
        data = _fetch_single(ticker, prepost=False)
        if data is None:
            continue
        results.append({
            **data,
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
    """S&P500 선물 (한국 갭 예측 시그널)."""
    ticker = "ES=F"
    data = _fetch_single(ticker, prepost=True)
    if data is None:
        return None
    mapping = SP500_FUTURES[ticker]
    return {
        **data,
        "name": mapping["name"],
        "category": mapping["category"],
        "implication": mapping["implication"],
        "type": "futures",
    }


def fetch_all() -> dict[str, Any]:
    """모든 데이터 한 번에 수집 (모닝브리프에서 호출)."""
    return {
        "etf": fetch_etf_sectors(),
        "big_names": fetch_big_names(),
        "macro": fetch_macro_indicators(),
        "sp500_futures": fetch_sp500_futures(),
        "fetched_at": datetime.now().isoformat(),
    }
