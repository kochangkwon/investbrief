"""국내 시장 요약 수집 (네이버 금융 API)"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

NAVER_INDEX_API = "https://m.stock.naver.com/api/index/{symbol}/basic"

DOMESTIC_INDICES = {
    "kospi": ("KOSPI", "코스피"),
    "kosdaq": ("KOSDAQ", "코스닥"),
}


async def get_domestic_summary() -> dict[str, Any]:
    """코스피/코스닥 종가, 등락률 수집 (네이버 금융 API)"""
    result: dict[str, Any] = {}

    async with httpx.AsyncClient(timeout=10) as client:
        for key, (symbol, label) in DOMESTIC_INDICES.items():
            try:
                resp = await client.get(NAVER_INDEX_API.format(symbol=symbol))
                resp.raise_for_status()
                data = resp.json()

                close = float(data["closePrice"].replace(",", ""))
                change = float(data["compareToPreviousClosePrice"].replace(",", ""))
                change_pct = float(data["fluctuationsRatio"])

                # 하락인 경우 부호 처리
                direction = data.get("compareToPreviousPrice", {}).get("code", "")
                if direction == "5":  # FALLING
                    change = -abs(change)
                    change_pct = -abs(change_pct)

                result[key] = {
                    "label": label,
                    "close": round(close, 2),
                    "change": round(change, 2),
                    "change_pct": round(change_pct, 2),
                }
            except Exception:
                logger.exception("국내 시장 데이터 수집 실패: %s", key)

    logger.info("국내 시장 수집 완료: %d/%d", len(result), len(DOMESTIC_INDICES))
    return result
