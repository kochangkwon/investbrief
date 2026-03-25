"""DART 공시 수집"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

DART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"

# 공시 중요도 분류 키워드
IMPORTANCE_RULES = {
    "🔴": [
        "유상증자", "전환사채", "감자", "상장폐지", "CB발행",
        "신주인수권부사채", "교환사채", "파산", "회생절차", "관리종목",
        "불성실공시", "상장적격성", "거래정지", "BW발행",
    ],
    "🟡": [
        "최대주주변경", "소송", "영업정지", "횡령", "배임",
        "합병", "분할", "영업양수", "영업양도", "주식교환",
        "임원변동", "대표이사변경", "감사의견거절", "한정",
    ],
    "🟢": [
        "자사주매입", "배당", "수주", "자기주식",
        "자사주소각", "무상증자", "주식배당", "중간배당",
        "특별배당", "수주공시", "계약체결",
    ],
    "⚪": [
        "실적", "사업보고서", "분기보고서", "반기보고서", "IR",
        "감사보고서", "정기주주총회", "기업설명회", "기업가치제고",
    ],
}


def _classify_importance(title: str) -> str:
    """공시 제목으로 중요도 분류"""
    for level, keywords in IMPORTANCE_RULES.items():
        if any(kw in title for kw in keywords):
            return level
    return "⚪"


async def get_today_disclosures(target_date: date | None = None) -> list[dict[str, Any]]:
    """당일 주요 공시 수집"""
    if not settings.dart_api_key:
        logger.warning("DART API 키 미설정")
        return []

    d = target_date or date.today()
    date_str = d.strftime("%Y%m%d")

    items: list[dict[str, Any]] = []
    try:
        params = {
            "crtfc_key": settings.dart_api_key,
            "bgn_de": date_str,
            "end_de": date_str,
            "page_count": 100,
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(DART_LIST_URL, params=params)
            resp.raise_for_status()

        data = resp.json()
        if data.get("status") != "000":
            logger.warning("DART 응답 오류: %s", data.get("message"))
            return []

        for item in data.get("list", []):
            items.append({
                "corp_name": item.get("corp_name", ""),
                "corp_code": item.get("corp_code", ""),
                "stock_code": item.get("stock_code", ""),
                "title": item.get("report_nm", ""),
                "rcept_no": item.get("rcept_no", ""),
                "rcept_dt": item.get("rcept_dt", ""),
                "importance": _classify_importance(item.get("report_nm", "")),
            })
    except Exception:
        logger.exception("DART 공시 수집 실패")

    logger.info("DART 공시 수집: %d건 (%s)", len(items), date_str)
    return items
