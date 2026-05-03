"""국내 시장 요약 수집 (네이버 금융 API + FinanceDataReader 백필)"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

import FinanceDataReader as fdr
import httpx

logger = logging.getLogger(__name__)

NAVER_INDEX_API = "https://m.stock.naver.com/api/index/{symbol}/basic"

DOMESTIC_INDICES = {
    "kospi": ("KOSPI", "코스피"),
    "kosdaq": ("KOSDAQ", "코스닥"),
}

# FinanceDataReader 종목 코드 (백필용)
FDR_INDICES = {
    "kospi": ("KS11", "코스피"),
    "kosdaq": ("KQ11", "코스닥"),
}


async def _fetch_naver_basic(symbol: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(NAVER_INDEX_API.format(symbol=symbol))
        resp.raise_for_status()
        return resp.json()


def _fetch_fdr_sync(code: str, target_date: date) -> dict[str, Any] | None:
    """FDR로 target_date 기준 종가/등락 조회"""
    try:
        start = (target_date - timedelta(days=14)).isoformat()
        end = (target_date + timedelta(days=1)).isoformat()
        df = fdr.DataReader(code, start, end)
        if df.empty:
            return None
        # target_date 이하 행만
        df = df[df.index.date <= target_date]
        if df.empty:
            return None

        close = float(df["Close"].iloc[-1])
        if len(df) >= 2:
            prev_close = float(df["Close"].iloc[-2])
            change = close - prev_close
            change_pct = (change / prev_close) * 100
        else:
            change = 0.0
            change_pct = 0.0

        return {
            "close": round(close, 2),
            "change": round(change, 2),
            "change_pct": round(change_pct, 2),
        }
    except Exception:
        logger.exception("FDR 지수 조회 실패: %s @ %s", code, target_date)
        return None


async def get_domestic_summary(target_date: date | None = None) -> dict[str, Any]:
    """코스피/코스닥 종가, 등락률 수집

    target_date가 None이면 네이버 모바일 API(현재 시점) 사용.
    target_date가 지정되면 FinanceDataReader로 해당 거래일 데이터 조회.
    """
    result: dict[str, Any] = {}

    if target_date is None:
        async with httpx.AsyncClient(timeout=10) as client:
            for key, (symbol, label) in DOMESTIC_INDICES.items():
                try:
                    resp = await client.get(NAVER_INDEX_API.format(symbol=symbol))
                    resp.raise_for_status()
                    data = resp.json()

                    close = float(data["closePrice"].replace(",", ""))
                    change = float(data["compareToPreviousClosePrice"].replace(",", ""))
                    change_pct = float(data["fluctuationsRatio"])

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
    else:
        # 백필: FDR로 병렬 조회
        keys = list(FDR_INDICES.keys())
        coros = [
            asyncio.to_thread(_fetch_fdr_sync, FDR_INDICES[k][0], target_date)
            for k in keys
        ]
        fdr_results = await asyncio.gather(*coros, return_exceptions=True)
        for key, res in zip(keys, fdr_results):
            if isinstance(res, Exception) or res is None:
                continue
            label = FDR_INDICES[key][1]
            result[key] = {"label": label, **res}

    logger.info(
        "국내 시장 수집 완료: %d/%d (target=%s)",
        len(result),
        len(DOMESTIC_INDICES),
        target_date or "today",
    )
    return result
