"""모닝브리프에서 호출하는 단일 진입점.

외부에서는 get_us_market_section()만 호출하면 됨.
캐싱 + fail-soft 정책 캡슐화.

설계:
- yfinance는 sync 블로킹 → asyncio.to_thread로 워커 스레드에서 실행
- 메모리 캐시 60분 (서버 재시작 시 무효, 단일 worker 가정)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from .fetcher import fetch_all
from .formatter import format_full_section

logger = logging.getLogger(__name__)

# 메모리 캐시 (단일 worker 가정 — uvicorn --workers 1)
_cache: dict[str, Any] = {
    "data": None,
    "expires_at": None,
}
_CACHE_TTL_MINUTES = 60


def _is_cache_valid() -> bool:
    if _cache["data"] is None or _cache["expires_at"] is None:
        return False
    return datetime.now() < _cache["expires_at"]


async def get_us_market_data(use_cache: bool = True) -> dict[str, Any]:
    """미국 시장 raw 데이터 (디버깅/내부용). yfinance 호출은 to_thread."""
    if use_cache and _is_cache_valid():
        return _cache["data"]

    try:
        data = await asyncio.to_thread(fetch_all)
        _cache["data"] = data
        _cache["expires_at"] = datetime.now() + timedelta(minutes=_CACHE_TTL_MINUTES)
        return data
    except Exception:
        logger.exception("[us_market] fetch_all failed")
        return {"etf": [], "big_names": [], "macro": [], "sp500_futures": None}


async def get_us_market_section(use_cache: bool = True) -> str:
    """모닝브리프에 삽입할 미국 시장 섹션 텍스트.

    Returns:
        포맷된 텔레그램 HTML 문자열. 실패 시 빈 문자열 (fail-soft).
    """
    try:
        data = await get_us_market_data(use_cache=use_cache)
        return format_full_section(data)
    except Exception:
        logger.exception("[us_market] section build failed")
        return ""


def clear_cache() -> None:
    """수동 캐시 비우기 (테스트/스모크용)."""
    _cache["data"] = None
    _cache["expires_at"] = None
