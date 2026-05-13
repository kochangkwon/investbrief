"""DART 분기 재무 단순 조회 — 매출/영업이익/당기순이익만.

corp_code는 DART 공시 응답에서 자연스럽게 캐시되는 stock_corp_map 활용.
별도 전체 corp_code 다운로드는 P2-7 도입 시 추가.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

DART_SINGL_ACNT_URL = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"


def _current_year_quarter() -> tuple[int, int]:
    """가장 최근 발표 가능 분기."""
    today = date.today()
    y, m = today.year, today.month
    if m >= 11:
        return y, 3
    if m >= 8:
        return y, 2
    if m >= 5:
        return y, 1
    return y - 1, 4


async def fetch_quarterly_simple(
    corp_code: str, year: Optional[int] = None, quarter: Optional[int] = None
) -> Optional[dict[str, Any]]:
    """분기 매출/영업이익/당기순이익 조회.

    Returns:
        {"revenue": float, "operating_profit": float, "net_income": float}
        (단위: 억원)
        실패 시 None.
    """
    if not settings.dart_api_key:
        return None

    if year is None or quarter is None:
        year, quarter = _current_year_quarter()

    reprt_code_map = {1: "11013", 2: "11012", 3: "11014", 4: "11011"}
    reprt_code = reprt_code_map.get(quarter)
    if not reprt_code:
        return None

    params = {
        "crtfc_key": settings.dart_api_key,
        "corp_code": corp_code,
        "bsns_year": str(year),
        "reprt_code": reprt_code,
        "fs_div": "CFS",  # 연결, 없으면 OFS 폴백
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(DART_SINGL_ACNT_URL, params=params)
            resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "000":
            # CFS 없으면 OFS 재시도
            params["fs_div"] = "OFS"
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(DART_SINGL_ACNT_URL, params=params)
            data = resp.json()
            if data.get("status") != "000":
                logger.debug(
                    "DART 재무 없음: %s %d Q%d (status=%s)",
                    corp_code, year, quarter, data.get("status"),
                )
                return None

        return _parse_simple(data.get("list", []))
    except Exception:
        logger.exception("DART 재무 조회 실패: %s %d Q%d", corp_code, year, quarter)
        return None


def _parse_simple(items: list[dict[str, Any]]) -> dict[str, Optional[float]]:
    """3개 항목만 추출."""
    result: dict[str, Optional[float]] = {
        "revenue": None,
        "operating_profit": None,
        "net_income": None,
    }

    def _to_billion(s: str) -> Optional[float]:
        try:
            return round(float(s.replace(",", "")) / 1e8, 2)
        except (ValueError, AttributeError):
            return None

    matchers = {
        "revenue": ["매출액", "수익(매출액)", "영업수익"],
        "operating_profit": ["영업이익", "영업이익(손실)"],
        "net_income": ["당기순이익", "당기순이익(손실)"],
    }

    for item in items:
        account_nm = item.get("account_nm", "")
        amount_str = item.get("thstrm_amount", "")
        for key, candidates in matchers.items():
            if result[key] is None and account_nm in candidates:
                result[key] = _to_billion(amount_str)
                break

    return result
