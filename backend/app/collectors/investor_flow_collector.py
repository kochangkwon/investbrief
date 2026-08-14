"""KRX 투자자별 매매 + 외인 매수/매도 TOP 종목 (pykrx).

지시서 G-2/G-3: KRX 조회를 단명 서브프로세스(_krx_flow_worker)로 격리하고,
KRX → 네이버 → 전일 캐시 3단 폴백으로 침묵 실패를 제거한다.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# 캐시 파일 (backend/runtime/investor_flow_cache.json)
_CACHE_PATH = Path(__file__).resolve().parents[2] / "runtime" / "investor_flow_cache.json"
_CACHE_MAX_AGE_DAYS = 7

# 워커 결과 단기 메모 (동일 브리프 내 중복 서브프로세스 로그인 방지). 값: (mono, (dict|None, reason))
_WORKER_MEMO_TTL_SEC = 300
_worker_memo: dict[str, tuple[float, tuple[Optional[dict], Optional[str]]]] = {}

# 네이버 시장별 투자자 순매매 (억원). KRX 로그인/정책 리스크 대비 2단 폴백.
_NAVER_TREND_URL = "https://m.stock.naver.com/api/index/{code}/trend"
_NAVER_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _fetch_market_flow_sync(target_date: date) -> Optional[dict[str, float]]:
    """전체 시장(KOSPI+KOSDAQ) 투자자별 순매수 (단위: 억원)."""
    try:
        from pykrx import stock
        date_str = target_date.strftime("%Y%m%d")

        kospi_df = stock.get_market_trading_value_by_investor(
            date_str, date_str, "KOSPI"
        )
        kosdaq_df = stock.get_market_trading_value_by_investor(
            date_str, date_str, "KOSDAQ"
        )

        def _net(df, label: str) -> float:
            try:
                return float(df.loc[label, "순매수"]) / 1e8
            except (KeyError, IndexError):
                return 0.0

        foreign = _net(kospi_df, "외국인") + _net(kosdaq_df, "외국인")
        inst = _net(kospi_df, "기관합계") + _net(kosdaq_df, "기관합계")
        retail = _net(kospi_df, "개인") + _net(kosdaq_df, "개인")

        return {
            "foreign_net_billion": round(foreign, 0),
            "institution_net_billion": round(inst, 0),
            "retail_net_billion": round(retail, 0),
            "trade_date": target_date.isoformat(),
        }
    except Exception:
        logger.exception("KRX 시장 수급 조회 실패 (%s)", target_date)
        return None


def _fetch_top_foreign_traders_sync(
    target_date: date, limit_buy: int = 10, limit_sell: int = 5
) -> list[dict[str, Any]]:
    """외국인 순매수/매도 상위 종목.

    Returns: 매수 TOP + 매도 TOP 통합 리스트
    """
    try:
        from pykrx import stock
        date_str = target_date.strftime("%Y%m%d")

        df_kospi = stock.get_market_net_purchases_of_equities(
            date_str, date_str, "KOSPI", "외국인"
        )
        df_kosdaq = stock.get_market_net_purchases_of_equities(
            date_str, date_str, "KOSDAQ", "외국인"
        )

        items: list[dict[str, Any]] = []
        for df in (df_kospi, df_kosdaq):
            if df is None or df.empty:
                continue
            value_col = None
            for c in df.columns:
                if "순매수" in c and "대금" in c:
                    value_col = c
                    break
            if value_col is None:
                continue
            for code, row in df.iterrows():
                items.append({
                    "stock_code": str(code).zfill(6),
                    "stock_name": str(row.get("종목명", "")),
                    "net_billion": round(float(row[value_col]) / 1e8, 0),
                })

        items.sort(key=lambda x: x["net_billion"], reverse=True)
        buys = items[:limit_buy]
        sells = [i for i in items if i["net_billion"] < 0]
        sells.sort(key=lambda x: x["net_billion"])
        sells = sells[:limit_sell]

        return buys + sells
    except Exception:
        logger.exception("KRX 외인 매수/매도 조회 실패 (%s)", target_date)
        return []


# ─────────────────────────────────────────────────────────
# G-2: KRX 서브프로세스 워커 실행 (토큰 만료 면역)
# ─────────────────────────────────────────────────────────
async def _run_krx_worker(target_date: date) -> tuple[Optional[dict], Optional[str]]:
    """워커 실행 (날짜별 단기 메모). resilient·get_market_flow가 공유해 이중 로그인 방지."""
    date_str = target_date.strftime("%Y%m%d")
    memo = _worker_memo.get(date_str)
    if memo and (time.monotonic() - memo[0]) < _WORKER_MEMO_TTL_SEC:
        return memo[1]
    result = await _run_krx_worker_uncached(target_date)
    _worker_memo[date_str] = (time.monotonic(), result)
    return result


async def _run_krx_worker_uncached(target_date: date) -> tuple[Optional[dict], Optional[str]]:
    """단명 워커로 KRX 조회. (결과, 실패사유) 반환.

    결과 dict: {"market_flow": {...}|None, "top_traders": [...]}.
    실패사유: None(성공) | "credentials"(로그인 실패) | "error"(타임아웃/비정상).
    실패 시 1회 재시도.
    """
    date_str = target_date.strftime("%Y%m%d")
    cmd = [sys.executable, "-m", "app.collectors._krx_flow_worker", date_str]

    last_reason = "error"
    for attempt in (1, 2):
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await asyncio.wait_for(proc.communicate(), timeout=60)
        except asyncio.TimeoutError:
            if proc is not None:
                proc.kill()
            logger.warning("KRX 워커 타임아웃 (attempt %d, %s)", attempt, date_str)
            last_reason = "error"
            continue
        except Exception:
            logger.exception("KRX 워커 실행 예외 (attempt %d, %s)", attempt, date_str)
            last_reason = "error"
            continue

        if proc.returncode == 3:
            logger.error(
                "KRX 워커 로그인 실패 — 자격증명 문제 의심 (%s): %s",
                date_str, err.decode(errors="replace")[:300],
            )
            return None, "credentials"  # 재로그인해도 동일 — 재시도 무의미
        if proc.returncode != 0:
            logger.warning(
                "KRX 워커 실패 rc=%s (attempt %d): %s",
                proc.returncode, attempt, err.decode(errors="replace")[:300],
            )
            last_reason = "error"
            continue
        try:
            return json.loads(out.decode()), None
        except json.JSONDecodeError:
            logger.warning("KRX 워커 JSON 파싱 실패 (attempt %d): %r", attempt, out[:200])
            last_reason = "error"
            continue

    return None, last_reason


# ─────────────────────────────────────────────────────────
# G-3 2단: 네이버 시장 수급 폴백
# ─────────────────────────────────────────────────────────
def _parse_naver_signed(raw: Optional[str]) -> float:
    """'+5,023' / '-8,846' → float. 파싱 불가는 예외로 승격(조용한 0 금지)."""
    if raw is None:
        raise ValueError("네이버 수급 값 누락")
    return float(raw.replace(",", "").replace("+", ""))


async def _fetch_naver_market_flow(target_date: date) -> Optional[dict[str, Any]]:
    """네이버 KOSPI+KOSDAQ 투자자 순매매 합산 (억원). 구조 변경 시 None."""
    foreign = inst = retail = 0.0
    bizdate = None
    try:
        async with httpx.AsyncClient(timeout=8, headers=_NAVER_HEADERS) as client:
            for code in ("KOSPI", "KOSDAQ"):
                resp = await client.get(_NAVER_TREND_URL.format(code=code))
                resp.raise_for_status()
                data = resp.json()
                foreign += _parse_naver_signed(data["foreignValue"])
                inst += _parse_naver_signed(data["institutionalValue"])
                retail += _parse_naver_signed(data["personalValue"])
                bizdate = data.get("bizdate") or bizdate
    except Exception:
        logger.warning("네이버 시장 수급 폴백 실패 (%s)", target_date, exc_info=True)
        return None

    trade_date = (
        f"{bizdate[0:4]}-{bizdate[4:6]}-{bizdate[6:8]}"
        if bizdate else target_date.isoformat()
    )
    return {
        "foreign_net_billion": round(foreign, 0),
        "institution_net_billion": round(inst, 0),
        "retail_net_billion": round(retail, 0),
        "trade_date": trade_date,
    }


# ─────────────────────────────────────────────────────────
# G-3 3단: 전일 캐시 (원자적 기록)
# ─────────────────────────────────────────────────────────
def _save_cache(payload: dict) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CACHE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_CACHE_PATH)
    except Exception:
        logger.warning("수급 캐시 저장 실패", exc_info=True)


def _load_fresh_cache() -> Optional[dict]:
    if not _CACHE_PATH.exists():
        return None
    try:
        payload = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        trade_date = date.fromisoformat(payload["market_flow"]["trade_date"])
    except Exception:
        logger.warning("수급 캐시 로드 실패", exc_info=True)
        return None
    if (date.today() - trade_date).days > _CACHE_MAX_AGE_DAYS:
        return None
    return payload


# ─────────────────────────────────────────────────────────
# G-3: 3단 폴백 진입점
# ─────────────────────────────────────────────────────────
async def get_market_flow_resilient(target_date: date) -> Optional[dict[str, Any]]:
    """KRX → 네이버 → 캐시 3단 폴백.

    반환: {"market_flow": {..., source, trade_date}, "top_traders": [...]} or None.
    market_flow.source ∈ {"krx","naver","cache"}. 실패 사유는 로그로.

    주의: 네이버 폴백은 '최신 거래일'만 반환하므로 이 함수는 브리프의 최신일 수급 전용이다.
    과거 특정일 조회(히스토리 루프)는 폴백이 오늘값을 과거일로 오염시키므로 get_market_flow(KRX 전용)를 쓸 것.
    """
    # 1단 KRX
    worker, reason = await _run_krx_worker(target_date)
    if worker and worker.get("market_flow"):
        mf = {**worker["market_flow"], "source": "krx"}
        result = {"market_flow": mf, "top_traders": worker.get("top_traders", [])}
        _save_cache(result)
        return result
    if reason == "credentials":
        logger.error("KRX 자격증명 문제 — 네이버 폴백으로 전환")

    # 2단 네이버
    naver = await _fetch_naver_market_flow(target_date)
    if naver:
        return {"market_flow": {**naver, "source": "naver"}, "top_traders": []}

    # 3단 전일 캐시
    cached = _load_fresh_cache()
    if cached and cached.get("market_flow"):
        cached["market_flow"]["source"] = "cache"
        return cached

    # 4단 전부 실패
    return None


async def get_market_flow(target_date: date) -> Optional[dict[str, Any]]:
    """시장 수급만 — KRX 워커 전용(폴백 없음).

    과거 특정일 조회(market_risk 히스토리 루프)에서 정확성을 지키려면 KRX 또는 None이어야 한다.
    네이버 폴백은 최신일만 주므로 여기서 쓰면 과거일 데이터를 오염시킨다(§get_market_flow_resilient 주석).
    """
    worker, _reason = await _run_krx_worker(target_date)
    if worker and worker.get("market_flow"):
        return {**worker["market_flow"], "source": "krx"}
    return None


def latest_trading_date(today: Optional[date] = None) -> date:
    """주말 회피한 직전 거래일."""
    d = today or date.today()
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d - timedelta(days=2)
    yesterday = d - timedelta(days=1)
    if yesterday.weekday() == 6:
        return yesterday - timedelta(days=2)
    if yesterday.weekday() == 5:
        return yesterday - timedelta(days=1)
    return yesterday
