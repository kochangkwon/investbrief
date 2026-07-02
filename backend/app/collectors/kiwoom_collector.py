"""키움 REST API 수급 데이터 수집 (테마 선정 정확도용).

테마 스캔이 후보 종목을 거를 때 "세력이 실제로 들어오는지"를 판정하기 위한
수급 신호를 제공한다. 조회 전용 — 주문/계좌 기능은 호출하지 않는다.

제공 TR:
- ka10009 주식기관요청       (/api/dostk/frgnistt) — 기관·외국인 순매매 스냅샷
- ka10014 공매도추이요청     (/api/dostk/shsa)     — 일자별 공매도량·비중
- ka20068 대차거래추이(종목별) (/api/dostk/slb)      — 일자별 대차잔고·증감

키(KIWOOM_APP_KEY/SECRET)가 비어 있으면 모든 함수가 None을 반환해서
호출부(prefilter)가 보수적으로 통과하도록 한다 (fail-open).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any, Optional

import httpx

from app.config import settings
from app.utils.timezone import now_kst, today_kst

logger = logging.getLogger(__name__)

_BASE_URL = "https://mockapi.kiwoom.com" if settings.kiwoom_is_mock else "https://api.kiwoom.com"

# 키움 REST 초당 호출 제한 회피용 (prefilter 동시성 위에 추가 상한)
_API_SEMAPHORE = asyncio.Semaphore(3)

# 토큰 캐시 (모듈 전역 — expires_dt까지 재사용)
_token: Optional[str] = None
_token_expiry: Optional[Any] = None  # datetime (naive KST)
_token_lock = asyncio.Lock()


def _enabled() -> bool:
    return bool(settings.kiwoom_app_key and settings.kiwoom_app_secret)


def _parse_num(raw: Any) -> Optional[float]:
    """'+7.28', '-339500', '1,234', '' → float / None. 부호·콤마 처리."""
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "")
    if s in ("", "-", "+"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


async def _get_token() -> Optional[str]:
    """접근토큰 발급/캐시. 만료 60초 전이면 재발급."""
    global _token, _token_expiry
    if not _enabled():
        return None

    async with _token_lock:
        now = now_kst().replace(tzinfo=None)
        if _token and _token_expiry and now < _token_expiry - timedelta(seconds=60):
            return _token
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{_BASE_URL}/oauth2/token",
                    json={
                        "grant_type": "client_credentials",
                        "appkey": settings.kiwoom_app_key,
                        "secretkey": settings.kiwoom_app_secret,
                    },
                    headers={"Content-Type": "application/json;charset=UTF-8"},
                )
            resp.raise_for_status()
            data = resp.json()
            if data.get("return_code") not in (0, None) or not data.get("token"):
                logger.warning("[kiwoom] 토큰 발급 실패: %s", data.get("return_msg"))
                return None
            _token = data["token"]
            # expires_dt: 'YYYYMMDDHHMMSS'
            from datetime import datetime
            try:
                _token_expiry = datetime.strptime(data["expires_dt"], "%Y%m%d%H%M%S")
            except (KeyError, ValueError):
                _token_expiry = now + timedelta(hours=1)
            return _token
        except Exception:
            logger.exception("[kiwoom] 토큰 발급 예외")
            return None


async def _request(api_id: str, path: str, body: dict[str, Any]) -> Optional[dict[str, Any]]:
    """단일 TR 호출. 실패/오류코드 시 None."""
    token = await _get_token()
    if not token:
        return None
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {token}",
        "api-id": api_id,
        "cont-yn": "N",
        "next-key": "",
    }
    # 키움 초당 호출 제한(429) 회피 — 짧은 백오프로 최대 3회 재시도
    for attempt in range(3):
        try:
            async with _API_SEMAPHORE:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.post(f"{_BASE_URL}{path}", json=body, headers=headers)
            if resp.status_code == 429:
                if attempt < 2:
                    await asyncio.sleep(0.4 * (attempt + 1))
                    continue
                logger.warning("[kiwoom] %s 429 재시도 소진 (%s)", api_id, body.get("stk_cd"))
                return None
            resp.raise_for_status()
            data = resp.json()
            if data.get("return_code") not in (0, None):
                logger.warning("[kiwoom] %s 오류: %s", api_id, data.get("return_msg"))
                return None
            return data
        except Exception:
            logger.warning("[kiwoom] %s 호출 예외 (%s)", api_id, body.get("stk_cd"), exc_info=True)
            return None
    return None


# ── 개별 TR ──────────────────────────────────────────────────────────


async def get_institution_foreign(stock_code: str) -> Optional[dict[str, Any]]:
    """ka10009 주식기관요청 — 기관·외국인 순매매 스냅샷.

    ※ 장중에는 순매매 필드가 비어 올 수 있다(정산 후 채워짐) → None 가능.
    """
    data = await _request("ka10009", "/api/dostk/frgnistt", {"stk_cd": stock_code})
    if data is None:
        return None
    return {
        "date": data.get("date"),
        "institution_net": _parse_num(data.get("orgn_daly_nettrde")),
        "foreign_net": _parse_num(data.get("frgnr_daly_nettrde")),
        "foreign_ratio": _parse_num(data.get("frgnr_qota_rt")),
    }


async def get_short_selling(stock_code: str, days: int = 30) -> list[dict[str, Any]]:
    """ka10014 공매도추이요청 — 일자별 공매도량·비중 (최신순)."""
    end = today_kst()
    start = end - timedelta(days=days + 15)  # 거래일 확보용 여유
    data = await _request(
        "ka10014",
        "/api/dostk/shsa",
        {
            "stk_cd": stock_code,
            "tm_tp": "1",
            "strt_dt": start.strftime("%Y%m%d"),
            "end_dt": end.strftime("%Y%m%d"),
        },
    )
    if data is None:
        return []
    rows = data.get("shrts_trnsn") or []
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append({
            "date": r.get("dt"),
            "short_volume": _parse_num(r.get("shrts_qty")),
            "short_weight": _parse_num(r.get("trde_wght")),  # 공매도 거래비중(%)
            "trade_volume": _parse_num(r.get("trde_qty")),
        })
    return out


async def get_lending_trend(stock_code: str, days: int = 30) -> list[dict[str, Any]]:
    """ka20068 대차거래추이(종목별) — 일자별 대차잔고·증감 (최신순)."""
    end = today_kst()
    start = end - timedelta(days=days + 15)
    data = await _request(
        "ka20068",
        "/api/dostk/slb",
        {
            "stk_cd": stock_code,
            "strt_dt": start.strftime("%Y%m%d"),
            "end_dt": end.strftime("%Y%m%d"),
            "all_tp": "0",
        },
    )
    if data is None:
        return []
    rows = data.get("dbrt_trde_trnsn") or []
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append({
            "date": r.get("dt"),
            "balance": _parse_num(r.get("rmnd")),            # 대차잔고 주수
            "change": _parse_num(r.get("dbrt_trde_irds")),   # 당일 증감
        })
    return out


async def get_investor_history(stock_code: str) -> list[dict[str, Any]]:
    """ka10059 종목별투자자·기관별 — 일자별 기관·외국인 순매수 히스토리 (최신순).

    ka10009(스냅샷·장중 공란)와 달리 일자별 히스토리를 제공한다 →
    수급 누적/백테스트용. amt_qty_tp=1(금액), trde_tp=0(순매수), unit_tp=1000.
    """
    data = await _request(
        "ka10059",
        "/api/dostk/stkinfo",
        {
            "dt": today_kst().strftime("%Y%m%d"),
            "stk_cd": stock_code,
            "amt_qty_tp": "1",
            "trde_tp": "0",
            "unit_tp": "1000",
        },
    )
    if data is None:
        return []
    rows = data.get("stk_invsr_orgn") or []
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append({
            "date": r.get("dt"),
            "institution_net": _parse_num(r.get("orgn")),         # 기관 순매수
            "foreign_net": _parse_num(r.get("frgnr_invsr")),      # 외국인 순매수
            "trade_value": _parse_num(r.get("acc_trde_prica")),   # 거래대금
        })
    return out


# ── 집계 신호 (prefilter 입력) ──────────────────────────────────────


def _avg(vals: list[float]) -> Optional[float]:
    nums = [v for v in vals if v is not None]
    if not nums:
        return None
    return sum(nums) / len(nums)


async def get_supply_demand_signal(stock_code: str) -> Optional[dict[str, Any]]:
    """종목별 수급 신호 집계 — 공매도/대차/기관·외국인.

    키 미설정 시 None(호출부 fail-open). 세 TR 중 일부만 성공해도 가능한
    메트릭은 채운다.

    반환 메트릭:
    - short_weight_5d:    최근 5거래일 공매도 비중 평균(%)
    - short_weight_prev5: 직전 5거래일 공매도 비중 평균(%)
    - short_weight_rising: 최근5 > 직전5 여부
    - lending_balance:    최신 대차잔고
    - lending_surge:      최신 대차잔고 / 직전 5~20일 평균
    - institution_net / foreign_net: 기관·외국인 순매매(정산 전 None 가능)
    """
    if not _enabled():
        return None

    short, lending, instfrgn = await asyncio.gather(
        get_short_selling(stock_code),
        get_lending_trend(stock_code),
        get_institution_foreign(stock_code),
    )

    metrics: dict[str, Any] = {}

    # 공매도 비중 추세 (리스트 최신순 가정)
    if short:
        weights = [r["short_weight"] for r in short if r["short_weight"] is not None]
        recent5 = _avg(weights[:5])
        prev5 = _avg(weights[5:10])
        if recent5 is not None:
            metrics["short_weight_5d"] = round(recent5, 2)
        if prev5 is not None:
            metrics["short_weight_prev5"] = round(prev5, 2)
        if recent5 is not None and prev5 is not None:
            metrics["short_weight_rising"] = recent5 > prev5

    # 대차잔고 급증 (최신 vs 직전 5~20일 평균)
    # 당일 미정산분은 잔고 0으로 와서 제외 (truthy 필터)
    if lending:
        balances = [r["balance"] for r in lending if r["balance"]]
        if balances:
            latest = balances[0]
            base = _avg(balances[5:20])
            metrics["lending_balance"] = latest
            if base and base > 0:
                metrics["lending_surge"] = round(latest / base, 3)

    # 기관·외국인 순매매 (정산 전 None 가능 — 메트릭 첨부만)
    if instfrgn:
        if instfrgn.get("institution_net") is not None:
            metrics["institution_net"] = instfrgn["institution_net"]
        if instfrgn.get("foreign_net") is not None:
            metrics["foreign_net"] = instfrgn["foreign_net"]

    return metrics or None
