"""DART 재무 리스크 필터용 API 클라이언트.

실호출 검증(2026-08-09) 기준으로 작성. 응답 원본은 docs/dart_samples/ 참조.

- corpCode.xml: 종목코드 → corp_code 매핑 (ZIP/XML, 로컬 파일 캐시)
- fnlttSinglAcntAll.json: 전체 재무제표. 사업보고서 1건에 당기/전기/전전기 3개년이
  모두 담겨 있어 연간 3개년 확보에 1회 호출이면 충분함(검증 확인).
- piicDecsn.json: 유상증자 결정. corp_code + 기간으로 직접 조회 가능하므로
  list.json 사전 검색 없이 이 엔드포인트만 호출한다.
"""
from __future__ import annotations

import io
import json
import logging
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.risk_cache import DartApiCache

logger = logging.getLogger(__name__)

_KST = ZoneInfo("Asia/Seoul")
BASE_URL = "https://opendart.fss.or.kr/api"
_CORPCODE_CACHE = Path(__file__).resolve().parents[2] / "data" / "dart_corpcode.json"
_CORPCODE_TTL_DAYS = 7
_TIMEOUT = 30

# 보고서 코드
REPRT_ANNUAL = "11011"
REPRT_Q1 = "11013"
REPRT_HALF = "11012"
REPRT_Q3 = "11014"


# --------------------------------------------------------------------------
# corp_code 매핑
# --------------------------------------------------------------------------
async def _download_corpcode_map() -> dict[str, dict[str, str]]:
    """corpCode.xml 전체 다운로드 → 상장사만 {stock_code: {corp_code, corp_name}}."""
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(
            f"{BASE_URL}/corpCode.xml", params={"crtfc_key": settings.dart_api_key}
        )
        resp.raise_for_status()

    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    root = ET.fromstring(zf.read(zf.namelist()[0]).decode("utf-8"))

    mapping: dict[str, dict[str, str]] = {}
    for el in root.iter("list"):
        stock_code = (el.findtext("stock_code") or "").strip()
        if not stock_code:
            continue
        mapping[stock_code] = {
            "corp_code": (el.findtext("corp_code") or "").strip(),
            "corp_name": (el.findtext("corp_name") or "").strip(),
        }
    return mapping


async def get_corp_code(stock_code: str) -> Optional[dict[str, str]]:
    """종목코드 → {corp_code, corp_name}. 로컬 파일 캐시(7일)."""
    if not settings.dart_api_key:
        logger.warning("DART_API_KEY 미설정")
        return None

    mapping: Optional[dict[str, Any]] = None
    if _CORPCODE_CACHE.exists():
        age = datetime.now() - datetime.fromtimestamp(_CORPCODE_CACHE.stat().st_mtime)
        if age < timedelta(days=_CORPCODE_TTL_DAYS):
            try:
                mapping = json.loads(_CORPCODE_CACHE.read_text(encoding="utf-8"))
            except Exception:
                logger.warning("corpcode 캐시 손상 — 재다운로드")

    if mapping is None:
        try:
            mapping = await _download_corpcode_map()
        except Exception:
            logger.exception("corpCode.xml 다운로드 실패")
            return None
        _CORPCODE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _CORPCODE_CACHE.write_text(
            json.dumps(mapping, ensure_ascii=False), encoding="utf-8"
        )
        logger.info("corpCode 캐시 갱신: %d개 상장사", len(mapping))

    return mapping.get(stock_code)


# --------------------------------------------------------------------------
# 응답 캐시
# --------------------------------------------------------------------------
async def _cached_get(
    session: Optional[AsyncSession],
    cache_key: str,
    url: str,
    params: dict[str, str],
    ttl_hours: Optional[int] = None,
) -> Optional[dict[str, Any]]:
    """DB 캐시 조회 → 없거나 만료면 API 호출 후 저장.

    ttl_hours=None이면 무기한 (확정된 과거 보고서용).
    """
    hit = None
    if session is not None:
        row = await session.execute(
            select(DartApiCache).where(DartApiCache.cache_key == cache_key)
        )
        hit = row.scalar_one_or_none()
        if hit is not None:
            # SQLite는 tzinfo를 보존하지 않으므로 naive면 KST로 간주
            fetched_at = hit.fetched_at
            if fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=_KST)
            fresh = ttl_hours is None or (
                datetime.now(_KST) - fetched_at < timedelta(hours=ttl_hours)
            )
            if fresh:
                logger.debug("DART 캐시 히트: %s", cache_key)
                return json.loads(hit.payload)

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
        data = resp.json()
    except Exception:
        logger.exception("DART 호출 실패: %s", cache_key)
        return None

    # 정상 응답만 캐싱 (일시 오류·미공시 상태는 재시도 여지를 남긴다)
    if session is not None and data.get("status") == "000":
        payload = json.dumps(data, ensure_ascii=False)
        if hit is not None:
            hit.payload = payload
            hit.fetched_at = datetime.now(_KST)
        else:
            session.add(DartApiCache(cache_key=cache_key, payload=payload))
        await session.commit()

    return data


# --------------------------------------------------------------------------
# 재무제표
# --------------------------------------------------------------------------
async def fetch_financial_statements(
    corp_code: str,
    bsns_year: str,
    reprt_code: str = REPRT_ANNUAL,
    session: Optional[AsyncSession] = None,
) -> Optional[dict[str, Any]]:
    """전체 재무제표 조회. CFS(연결) 우선, 없으면 OFS(별도) 폴백.

    Returns:
        {"fs_div": "CFS"|"OFS", "rows": [...]} 또는 None
    """
    if not settings.dart_api_key:
        return None

    for fs_div in ("CFS", "OFS"):
        key = f"fnltt:{corp_code}:{bsns_year}:{reprt_code}:{fs_div}"
        data = await _cached_get(
            session,
            key,
            f"{BASE_URL}/fnlttSinglAcntAll.json",
            {
                "crtfc_key": settings.dart_api_key,
                "corp_code": corp_code,
                "bsns_year": bsns_year,
                "reprt_code": reprt_code,
                "fs_div": fs_div,
            },
        )
        if data and data.get("status") == "000" and data.get("list"):
            return {"fs_div": fs_div, "rows": data["list"]}

    return None


def latest_annual_year(today: Optional[date] = None) -> int:
    """조회 가능한 최근 사업연도.

    사업보고서는 결산 후 90일 이내 제출(12월 결산 → 익년 3월말).
    여유를 두어 4월 이후부터 전년도 사업보고서를 조회한다.
    """
    d = today or date.today()
    return d.year - 1 if d.month >= 4 else d.year - 2


async def fetch_latest_quarter(
    corp_code: str, session: Optional[AsyncSession] = None, today: Optional[date] = None
) -> Optional[dict[str, Any]]:
    """최근 확보 가능한 분기/반기 보고서. 최신부터 역순 탐색.

    Returns:
        {"label": "2026Q1", "fs_div": "CFS", "rows": [...]} 또는 None
    """
    d = today or date.today()
    # 분기보고서는 분기말 후 45일 이내 제출. 여유를 두고 발표 완료된 것만 후보로 둔다.
    # (미발표 분기를 조회하면 status=013이 캐싱되지 않아 매번 재호출된다)
    sequence = [
        (d.year, REPRT_Q3, "Q3"),
        (d.year, REPRT_HALF, "Q2"),
        (d.year, REPRT_Q1, "Q1"),
        (d.year - 1, REPRT_Q3, "Q3"),
        (d.year - 1, REPRT_HALF, "Q2"),
    ]
    if d.month >= 12:
        start = 0
    elif d.month >= 9:
        start = 1
    elif d.month >= 6:
        start = 2
    else:
        start = 3
    candidates = sequence[start : start + 2]

    for year, reprt, label in candidates:
        result = await fetch_financial_statements(corp_code, str(year), reprt, session)
        if result:
            result["label"] = f"{year}{label}"
            return result
    return None


# --------------------------------------------------------------------------
# 유상증자 결정
# --------------------------------------------------------------------------
async def fetch_paid_in_capital_increase(
    corp_code: str,
    bgn_de: str,
    end_de: str,
    session: Optional[AsyncSession] = None,
) -> list[dict[str, Any]]:
    """기간 내 유상증자 결정 공시 목록 (없으면 빈 리스트)."""
    if not settings.dart_api_key:
        return []

    key = f"piic:{corp_code}:{bgn_de}:{end_de}"
    data = await _cached_get(
        session,
        key,
        f"{BASE_URL}/piicDecsn.json",
        {
            "crtfc_key": settings.dart_api_key,
            "corp_code": corp_code,
            "bgn_de": bgn_de,
            "end_de": end_de,
        },
        ttl_hours=24,  # 신규 공시 반영
    )
    if not data or data.get("status") != "000":
        return []
    return data.get("list") or []
