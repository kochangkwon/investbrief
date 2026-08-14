"""국내 시장 요약 수집 (네이버 금융 API + FinanceDataReader 백필)"""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any

from app.collectors import price_collector

logger = logging.getLogger(__name__)

DOMESTIC_INDICES = {
    "kospi": ("KOSPI", "코스피"),
    "kosdaq": ("KOSDAQ", "코스닥"),
}

# FinanceDataReader 종목 코드 (백필용)
FDR_INDICES = {
    "kospi": ("KS11", "코스피"),
    "kosdaq": ("KQ11", "코스닥"),
}


def _fetch_fdr_sync(code: str, target_date: date | None) -> dict[str, Any] | None:
    """지수 히스토리로 기준일 종가/등락 조회 (round 2자리).

    target_date None이면 오늘 앵커 — 장전에는 전일 종가 + 전일 등락이 나온다.
    """
    result = price_collector.fetch_close_with_change(code, target_date=target_date)
    if result is None:
        return None
    return {
        "close": round(result["close"], 2),
        "change": round(result["change"], 2),
        "change_pct": round(result["change_pct"], 2),
    }


async def get_domestic_summary(target_date: date | None = None) -> dict[str, Any]:
    """코스피/코스닥 전일 종가·등락률 수집 (호출처: brief_service 단독).

    실시간·백필 모두 지수 히스토리(price_collector.fetch_close_with_change)로
    계산한다 — 단일 경로.

    ※ 기존 실시간 경로(네이버 모바일 basic API)는 장전(08:30 브리프 생성
    시점)에 등락 필드를 0으로 반환해 브리프 103건 중 88건의 change_pct가
    0.0으로 저장되는 구조 결함이 있었다 (실측 77/100쌍 오차). 히스토리 기반
    계산은 전일/전전일 종가 비교라 장전에도 정확하다.
    """
    result: dict[str, Any] = {}

    anchor = target_date  # None이면 helper가 오늘 기준 최근 영업일 사용
    keys = list(FDR_INDICES.keys())
    coros = [
        asyncio.to_thread(_fetch_fdr_sync, FDR_INDICES[k][0], anchor)
        for k in keys
    ]
    fdr_results = await asyncio.gather(*coros, return_exceptions=True)
    for key, res in zip(keys, fdr_results):
        if isinstance(res, Exception) or res is None:
            logger.warning("국내 시장 데이터 수집 실패: %s (%s)", key, res)
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
