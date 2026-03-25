"""종목 검색 (네이버 증권 자동완성)"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

NAVER_AC_URL = "https://ac.stock.naver.com/ac"


async def search_stocks(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """종목명/코드로 검색"""
    if not query.strip():
        return []

    params = {"q": query, "target": "stock"}
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(NAVER_AC_URL, params=params)
            resp.raise_for_status()

        data = resp.json()
        results = []
        for item in data.get("items", []):
            if item.get("nationCode") != "KOR":
                continue
            results.append({
                "stock_name": item["name"],
                "stock_code": item["code"],
                "market": item.get("typeName", ""),
            })
            if len(results) >= limit:
                break
        return results
    except Exception:
        logger.exception("종목 검색 실패: %s", query)
        return []
