"""DART 공시 수집"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

import httpx

from app.config import settings
from app.utils.timezone import today_kst

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


MAX_PAGES = 5  # 페이지당 100건 × 5 = 최대 500건 (P2-1)


def _prev_business_day(d: date) -> date:
    """직전 영업일 (주말만 건너뜀 — 공휴일은 미반영, 순수 함수)."""
    prev = d - timedelta(days=1)
    while prev.weekday() >= 5:
        prev -= timedelta(days=1)
    return prev


def _dedup_by_rcept(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """rcept_no 기준 중복 제거 (순서 유지, 순수 함수)."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for it in items:
        key = it.get("rcept_no") or ""
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        out.append(it)
    return out


async def _fetch_disclosures_for_date(
    client: httpx.AsyncClient, date_str: str
) -> list[dict[str, Any]]:
    """단일 일자 공시를 페이징으로 수집 (최대 MAX_PAGES).

    기존에는 1페이지(100건)만 조회해 DART 일 공시 수백 건 중 대부분이
    유실됐다 — 공시발 테마 감지 0건의 주 원인 (P2-1).
    """
    raw: list[dict[str, Any]] = []
    for page_no in range(1, MAX_PAGES + 1):
        params = {
            "crtfc_key": settings.dart_api_key,
            "bgn_de": date_str,
            "end_de": date_str,
            "page_no": page_no,
            "page_count": 100,
        }
        try:
            resp = await client.get(DART_LIST_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logger.exception("DART 페이지 %d 수집 실패 (%s) — 수집분까지 반환", page_no, date_str)
            break
        if data.get("status") != "000":
            if page_no == 1:
                logger.warning("DART 응답 오류: %s", data.get("message"))
            break
        raw.extend(data.get("list", []))
        total_page = int(data.get("total_page") or 1)
        if page_no >= total_page:
            break
        await asyncio.sleep(0.2)  # DART rate limit 배려
    return raw


async def get_today_disclosures(
    target_date: date | None = None,
    include_previous_day: bool = False,
) -> list[dict[str, Any]]:
    """당일(옵션: +직전 영업일) 주요 공시 수집.

    include_previous_day: 스캔이 08:10이라 당일 공시가 거의 없는 문제 보완 —
    직전 영업일 공시를 함께 반환한다 (rcept_no 기준 dedup). 테마 스캔 경로 전용.
    """
    if not settings.dart_api_key:
        logger.warning("DART API 키 미설정")
        return []

    d = target_date or today_kst()
    dates = [d]
    if include_previous_day:
        dates.append(_prev_business_day(d))

    raw: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            for dd in dates:
                raw.extend(await _fetch_disclosures_for_date(client, dd.strftime("%Y%m%d")))
    except Exception:
        logger.exception("DART 공시 수집 실패")

    items: list[dict[str, Any]] = [
        {
            "corp_name": item.get("corp_name", ""),
            "corp_code": item.get("corp_code", ""),
            "stock_code": item.get("stock_code", ""),
            "title": item.get("report_nm", ""),
            "rcept_no": item.get("rcept_no", ""),
            "rcept_dt": item.get("rcept_dt", ""),
            "importance": _classify_importance(item.get("report_nm", "")),
        }
        for item in raw
    ]
    items = _dedup_by_rcept(items)

    # P0-4: corp_code 자연스러운 캐시 누적 (운영하며 자동 확장)
    try:
        from app.services import fundamental_simple_service
        for item in raw:
            stock_code = item.get("stock_code", "")
            corp_code = item.get("corp_code", "")
            corp_name = item.get("corp_name", "")
            if stock_code and corp_code and len(stock_code) == 6:
                await fundamental_simple_service.update_corp_map(
                    stock_code, corp_code, corp_name,
                )
    except Exception:
        logger.exception("corp_code 캐시 업데이트 실패 (무시)")

    logger.info(
        "DART 공시 수집: %d건 (%s%s)",
        len(items), d.strftime("%Y%m%d"),
        f"+전일 {dates[1].strftime('%Y%m%d')}" if include_previous_day else "",
    )
    return items
