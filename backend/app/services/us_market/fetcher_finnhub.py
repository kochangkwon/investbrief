"""Finnhub API fetcher (yfinance fallback).

yfinance가 rate limit으로 실패할 때 자동 전환. 무료 plan(60 req/min, 무제한 일일).

지원 범위:
- ✅ ETF (5개) — /quote endpoint
- ✅ 빅네임 (7개) — /quote endpoint
- ❌ 매크로/선물 — 무료 plan 미지원 (v2에서 검토)

차이점 (vs yfinance):
- 시간외 가격 분리 미지원 → prepost=None
- /quote의 c(current price)는 시간외 거래 진행 시 그 가격 반영 → regular_close에 사용
- pc(prev close)로 변동률 계산
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

import requests

from app.config import settings

from .mappings import BIG_NAMES, ETF_MAPPING

logger = logging.getLogger(__name__)

FINNHUB_BASE = "https://finnhub.io/api/v1"
_TIMEOUT_SECONDS = 10.0


def _finnhub_quote(symbol: str) -> Optional[dict[str, float]]:
    """Finnhub /quote endpoint — 단일 심볼 가격 조회.

    응답: {"c": current, "d": change, "dp": change_pct, "pc": prev_close, ...}
    Returns:
        {"regular_close": float, "regular_change_pct": float} or None
    """
    if not settings.finnhub_api_key:
        return None

    try:
        resp = requests.get(
            f"{FINNHUB_BASE}/quote",
            params={"symbol": symbol, "token": settings.finnhub_api_key},
            timeout=_TIMEOUT_SECONDS,
        )
    except requests.exceptions.RequestException as e:
        logger.warning("[finnhub] %s request failed: %s", symbol, e)
        return None

    if resp.status_code == 429:
        logger.warning("[finnhub] %s rate limited", symbol)
        return None
    if resp.status_code != 200:
        logger.warning("[finnhub] %s HTTP %d", symbol, resp.status_code)
        return None

    try:
        data = resp.json()
    except Exception as e:
        logger.warning("[finnhub] %s JSON parse failed: %s", symbol, e)
        return None

    # Finnhub 미지원 심볼 또는 데이터 없음 → c=0 반환
    current = data.get("c")
    prev_close = data.get("pc")
    change_pct = data.get("dp")

    if not current or current == 0:
        return None

    try:
        regular_close = float(current)
        if change_pct is not None:
            regular_change_pct = float(change_pct)
        elif prev_close and prev_close != 0:
            regular_change_pct = (regular_close - float(prev_close)) / float(prev_close) * 100
        else:
            regular_change_pct = 0.0
        return {
            "regular_close": regular_close,
            "regular_change_pct": round(regular_change_pct, 2),
        }
    except (TypeError, ValueError) as e:
        logger.warning("[finnhub] %s parse failed: %s", symbol, e)
        return None


def _build_finnhub_record(ticker: str, metrics: dict[str, float]) -> dict[str, Any]:
    """Finnhub 결과 → fetcher.py와 동일한 record 형식 (시간외 None)."""
    return {
        "ticker": ticker,
        "regular_close": metrics["regular_close"],
        "regular_change_pct": metrics["regular_change_pct"],
        "prepost_price": None,
        "prepost_change_pct": None,
        "fetched_at": datetime.now().isoformat(),
    }


def fetch_etf_sectors_finnhub() -> list[dict[str, Any]]:
    """ETF 섹터 데이터 — Finnhub fallback."""
    if not settings.finnhub_api_key:
        return []

    results: list[dict[str, Any]] = []
    for ticker in ETF_MAPPING.keys():
        metrics = _finnhub_quote(ticker)
        if metrics is None:
            continue
        mapping = ETF_MAPPING[ticker]
        results.append({
            **_build_finnhub_record(ticker, metrics),
            "name": mapping["name"],
            "category": mapping["category"],
            "kr_stocks": mapping["kr_stocks"],
            "kr_themes": mapping["kr_themes"],
            "note": mapping.get("note", ""),
            "type": "etf",
        })
    results.sort(key=lambda x: abs(x["regular_change_pct"]), reverse=True)
    return results


def fetch_big_names_finnhub() -> list[dict[str, Any]]:
    """빅네임 종목 데이터 — Finnhub fallback (시간외 미지원)."""
    if not settings.finnhub_api_key:
        return []

    results: list[dict[str, Any]] = []
    for ticker in BIG_NAMES.keys():
        metrics = _finnhub_quote(ticker)
        if metrics is None:
            continue
        mapping = BIG_NAMES[ticker]
        regular_abs = abs(metrics["regular_change_pct"])
        is_alert = regular_abs >= mapping["alert_threshold"]
        results.append({
            **_build_finnhub_record(ticker, metrics),
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
