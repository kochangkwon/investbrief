"""KRX 투자자별 매매 + 외인 매수/매도 TOP 종목 (pykrx).

지시서 G-2/G-3: KRX 조회를 단명 서브프로세스(_krx_flow_worker)로 격리하고,
KRX → 네이버 → 전일 캐시 3단 폴백으로 침묵 실패를 제거한다.
"""
from __future__ import annotations

import asyncio
import html
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
_RUNTIME_DIR = Path(__file__).resolve().parents[2] / "runtime"
_CACHE_PATH = _RUNTIME_DIR / "investor_flow_cache.json"
_CACHE_MAX_AGE_DAYS = 7
# KRX 워커 마지막 실패 진단 (서버가 launchd 없이 터미널에서 돌면 로그가 남지 않는다 —
# 2026-10-02~06 폴백 3연속 때 원인 불명이었던 재발 방지). /flow 명령·probe 스크립트가 읽음.
_KRX_LAST_ERROR_PATH = _RUNTIME_DIR / "krx_last_error.json"
last_krx_error: Optional[dict[str, Any]] = None

# 워커 결과 단기 메모 (동일 브리프 내 중복 서브프로세스 로그인 방지). 값: (mono, (dict|None, reason))
_WORKER_MEMO_TTL_SEC = 300
_WORKER_TIMEOUT_SEC = 60
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

        return market_flow_from_frames(kospi_df, kosdaq_df, target_date)
    except Exception:
        logger.exception("KRX 시장 수급 조회 실패 (%s)", target_date)
        return None


def market_flow_from_frames(kospi_df, kosdaq_df, target_date: date) -> Optional[dict[str, Any]]:
    """투자자별 매매 DataFrame 2종 → 합산 dict (순수 함수).

    휴장일·조회 불가 시 pykrx는 빈 DataFrame을 돌려주는데, 예전엔 이를 0억원으로
    보고해 "수급 0"이 실데이터처럼 브리프에 실렸다 (2026-09-25·28 추석 실측).
    두 시장 모두 데이터가 없으면 None — 호출측이 폴백/캐시로 처리한다.
    """
    def _net(df, label: str) -> Optional[float]:
        if df is None or getattr(df, "empty", True):
            return None
        try:
            return float(df.loc[label, "순매수"]) / 1e8
        except (KeyError, IndexError, TypeError, ValueError):
            return None

    rows = {
        "foreign_net_billion": ("외국인",),
        "institution_net_billion": ("기관합계",),
        "retail_net_billion": ("개인",),
    }
    out: dict[str, Any] = {}
    any_data = False
    for key, (label,) in rows.items():
        vals = [v for v in (_net(kospi_df, label), _net(kosdaq_df, label)) if v is not None]
        if vals:
            any_data = True
        out[key] = round(sum(vals), 0) if vals else 0.0
    if not any_data:
        logger.warning("KRX 투자자별 매매 데이터 없음 (%s) — 휴장일/미집계", target_date)
        return None
    out["trade_date"] = target_date.isoformat()
    return out


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
    detail = ""
    started = time.monotonic()
    for attempt in (1, 2):
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await asyncio.wait_for(proc.communicate(), timeout=_WORKER_TIMEOUT_SEC)
        except asyncio.TimeoutError:
            if proc is not None:
                proc.kill()
            logger.warning("KRX 워커 타임아웃 (attempt %d, %s)", attempt, date_str)
            last_reason, detail = "timeout", f"{_WORKER_TIMEOUT_SEC}s 초과"
            continue
        except Exception as e:
            logger.exception("KRX 워커 실행 예외 (attempt %d, %s)", attempt, date_str)
            last_reason, detail = "error", f"실행 예외 {type(e).__name__}: {e}"
            continue

        err_text = err.decode(errors="replace")
        if proc.returncode == 4:
            logger.error("KRX 비밀번호 변경 필요(CD010) (%s): %s", date_str, err_text[:300])
            _record_krx_error(date_str, "password_expired", err_text, attempt, started)
            return None, "password_expired"
        if proc.returncode == 3:
            logger.error(
                "KRX 워커 로그인 실패 — 자격증명 문제 의심 (%s): %s", date_str, err_text[:300],
            )
            _record_krx_error(date_str, "credentials", err_text, attempt, started)
            return None, "credentials"  # 재로그인해도 동일 — 재시도 무의미
        if proc.returncode != 0:
            logger.warning(
                "KRX 워커 실패 rc=%s (attempt %d): %s", proc.returncode, attempt, err_text[:300],
            )
            last_reason, detail = "error", f"rc={proc.returncode} {err_text}"
            continue
        try:
            payload = json.loads(out.decode())
        except json.JSONDecodeError:
            logger.warning("KRX 워커 JSON 파싱 실패 (attempt %d): %r", attempt, out[:200])
            last_reason, detail = "error", f"JSON 파싱 실패: {out[:200]!r}"
            continue
        if not payload.get("market_flow"):
            # 워커는 정상 종료했지만 데이터가 없음. stderr에 traceback이 있으면 조회
            # 예외(세션 없음→HTML 응답 등)이고, 없으면 휴장일·KRX 미집계다.
            if "Traceback" in err_text:
                last_reason, detail = "error", err_text
            else:
                last_reason, detail = "no_data", f"워커 정상 종료·데이터 없음 {err_text}"
            _record_krx_error(date_str, last_reason, detail, attempt, started)
            return payload, last_reason
        _clear_krx_error()
        return payload, None

    _record_krx_error(date_str, last_reason, detail, 2, started)
    return None, last_reason


def _record_krx_error(date_str: str, reason: str, detail: str, attempt: int, started: float) -> None:
    """마지막 KRX 실패를 모듈 변수 + runtime 파일에 남긴다 (로그 파일 부재 보완)."""
    global last_krx_error
    last_krx_error = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "date": date_str,
        "reason": reason,
        "attempts": attempt,
        "elapsed_sec": round(time.monotonic() - started, 1),
        "detail": (detail or "").strip()[-1500:],
    }
    try:
        _RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        _KRX_LAST_ERROR_PATH.write_text(
            json.dumps(last_krx_error, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    except Exception:
        logger.debug("krx_last_error 기록 실패", exc_info=True)


def _clear_krx_error() -> None:
    global last_krx_error
    last_krx_error = None


def load_last_krx_error() -> Optional[dict[str, Any]]:
    if last_krx_error:
        return last_krx_error
    try:
        if _KRX_LAST_ERROR_PATH.exists():
            return json.loads(_KRX_LAST_ERROR_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


# ── KRX 비밀번호 수명 추적 (90일 강제 변경 — 만료 전 선제 알림) ─────────
_KRX_PW_META_PATH = _RUNTIME_DIR / "krx_pw_meta.json"
KRX_PASSWORD_MAX_AGE_DAYS = 90
KRX_PASSWORD_WARN_DAYS = 80


def record_krx_password_fingerprint(password: Optional[str]) -> Optional[dict[str, Any]]:
    """비밀번호 해시 지문과 최초 관측일을 기록. 값이 바뀌면 관측일을 리셋 (서버 시작 시 호출).

    비밀번호 원문은 어디에도 남기지 않는다 (sha256 앞 12자리만).
    """
    if not password:
        return None
    import hashlib
    fp = hashlib.sha256(password.encode("utf-8")).hexdigest()[:12]
    meta: dict[str, Any] = {}
    try:
        if _KRX_PW_META_PATH.exists():
            meta = json.loads(_KRX_PW_META_PATH.read_text(encoding="utf-8"))
    except Exception:
        meta = {}
    if meta.get("fingerprint") != fp:
        meta = {"fingerprint": fp, "first_seen": date.today().isoformat()}
        try:
            _RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
            _KRX_PW_META_PATH.write_text(json.dumps(meta), encoding="utf-8")
        except Exception:
            logger.debug("krx_pw_meta 기록 실패", exc_info=True)
    return meta


def krx_password_age_days() -> Optional[int]:
    """현재 비밀번호가 처음 관측된 날로부터 경과일. 기록 없으면 None."""
    try:
        meta = json.loads(_KRX_PW_META_PATH.read_text(encoding="utf-8"))
        return (date.today() - date.fromisoformat(meta["first_seen"])).days
    except Exception:
        return None


def krx_password_expiry_notice() -> Optional[str]:
    """만료 임박/초과 시 안내 문구, 아니면 None."""
    age = krx_password_age_days()
    if age is None or age < KRX_PASSWORD_WARN_DAYS:
        return None
    left = KRX_PASSWORD_MAX_AGE_DAYS - age
    if left > 0:
        return (
            f"🔐 KRX 비밀번호 사용 {age}일째 — 약 {left}일 후 만료(90일 강제 변경). "
            "data.krx.co.kr 에서 미리 변경하고 .env KRX_PW 갱신 후 재시작하세요."
        )
    return (
        f"🔐 KRX 비밀번호 사용 {age}일째 — 만료 추정(90일 초과). "
        "data.krx.co.kr 에서 변경하고 .env KRX_PW 갱신 후 재시작하세요."
    )


def krx_reason_text(reason: Optional[str]) -> str:
    """경보 문구용 실패 사유 1줄."""
    base = {
        "password_expired": (
            "KRX 비밀번호 만료(CD010, 90일 주기) — data.krx.co.kr 로그인해 비밀번호 변경 → "
            ".env KRX_PW 갱신 → 서버 재시작"
        ),
        "credentials": "KRX 로그인 실패(자격증명 오류 또는 비밀번호 만료)",
        "timeout": f"KRX 응답 없음({_WORKER_TIMEOUT_SEC}s×2)",
        "no_data": "KRX 응답은 왔으나 데이터 없음(휴장일/미집계/구조 변경)",
        "error": "KRX 워커 오류",
    }.get(reason or "", "KRX 조회 실패")
    err = load_last_krx_error()
    if err and err.get("detail") and err.get("reason") == reason:
        lines = [ln.strip() for ln in err["detail"].splitlines() if ln.strip()]
        # traceback이면 마지막 줄(예외 종류·메시지)이 핵심, 아니면 첫 줄
        pick = ""
        if lines:
            pick = lines[-1] if "Traceback" in err["detail"] else lines[0]
        if pick:
            base += f" — {pick[:120]}"
    return base


# ─────────────────────────────────────────────────────────
# G-3 2단: 네이버 시장 수급 폴백
# ─────────────────────────────────────────────────────────
def _parse_naver_signed(raw: Optional[str]) -> float:
    """'+5,023' / '-8,846' → float. 파싱 불가는 예외로 승격(조용한 0 금지)."""
    if raw is None:
        raise ValueError("네이버 수급 값 누락")
    return float(raw.replace(",", "").replace("+", ""))


_last_naver_note: Optional[str] = None  # 마지막 거부/실패 사유 (/flow 진단 표시용)


def naver_trend_to_flow(
    payloads: dict[str, dict[str, Any]], target_date: date
) -> Optional[dict[str, Any]]:
    """네이버 trend 응답(시장코드→JSON) → 합산 dict (순수 함수).

    trend API는 "최신 거래일" 1건만 주며, 장 시작 전에는 **당일 레코드가 0으로**
    먼저 생성된다. 2026-10-02·10-06 08:31 브리프가 bizdate=당일·전부 0인 응답을
    실데이터처럼 실었던 실사고 재발 방지:
    - bizdate ≠ 기준일 → 거부 (당일 미개장 레코드 또는 다른 날짜)
    - 세 값 모두 0 → 거부 (미집계)
    """
    foreign = inst = retail = 0.0
    bizdates: set[str] = set()
    for code, data in payloads.items():
        foreign += _parse_naver_signed(data.get("foreignValue"))
        inst += _parse_naver_signed(data.get("institutionalValue"))
        retail += _parse_naver_signed(data.get("personalValue"))
        if data.get("bizdate"):
            bizdates.add(str(data["bizdate"]))

    global _last_naver_note
    expected = target_date.strftime("%Y%m%d")
    if bizdates != {expected}:
        got = ",".join(sorted(bizdates)) or "없음"
        _last_naver_note = (
            f"bizdate {got} ≠ 기준일 {expected}"
            + (" (네이버는 최신 거래일 1건만 제공 — 당일 레코드가 이미 생성됨)" if got > expected else "")
        )
        logger.warning("네이버 수급 폴백 거부: %s", _last_naver_note)
        return None
    if foreign == 0 and inst == 0 and retail == 0:
        _last_naver_note = f"bizdate {expected} 일치하나 외인·기관·개인 전부 0 (미집계)"
        logger.warning("네이버 수급 폴백 거부: %s", _last_naver_note)
        return None
    _last_naver_note = None
    return {
        "foreign_net_billion": round(foreign, 0),
        "institution_net_billion": round(inst, 0),
        "retail_net_billion": round(retail, 0),
        "trade_date": target_date.isoformat(),
    }


async def _fetch_naver_market_flow(target_date: date) -> Optional[dict[str, Any]]:
    """네이버 KOSPI+KOSDAQ 투자자 순매매 합산 (억원). 구조 변경·날짜 불일치 시 None."""
    payloads: dict[str, dict[str, Any]] = {}
    try:
        async with httpx.AsyncClient(timeout=8, headers=_NAVER_HEADERS) as client:
            for code in ("KOSPI", "KOSDAQ"):
                resp = await client.get(_NAVER_TREND_URL.format(code=code))
                resp.raise_for_status()
                payloads[code] = resp.json()
        return naver_trend_to_flow(payloads, target_date)
    except Exception as e:
        global _last_naver_note
        _last_naver_note = f"호출 실패 {type(e).__name__}: {str(e)[:80]}"
        logger.warning("네이버 시장 수급 폴백 실패 (%s)", target_date, exc_info=True)
        return None


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
    if reason in ("credentials", "password_expired"):
        logger.error("KRX 자격증명 문제(%s) — 네이버 폴백으로 전환", reason)
    krx_reason = krx_reason_text(reason)

    # 2단 네이버
    naver = await _fetch_naver_market_flow(target_date)
    if naver:
        return {
            "market_flow": {**naver, "source": "naver", "krx_reason": krx_reason},
            "top_traders": [],
        }

    # 3단 전일 캐시
    cached = _load_fresh_cache()
    if cached and cached.get("market_flow"):
        cached["market_flow"]["source"] = "cache"
        cached["market_flow"]["krx_reason"] = krx_reason
        return cached

    # 4단 전부 실패
    logger.error("수급 전 소스 실패 (%s): %s", target_date, krx_reason)
    return None


async def diagnose_flow_sources(target_date: date) -> str:
    """/flow 진단 — 각 소스를 지금 직접 호출해 상태를 1화면으로 (텔레그램 HTML)."""
    import os
    try:
        from pykrx import __version__ as pykrx_ver  # type: ignore
    except Exception:
        pykrx_ver = "미설치?"
    cred = "설정됨" if (os.environ.get("KRX_ID") and os.environ.get("KRX_PW")) else "누락"
    age = krx_password_age_days()
    age_txt = f" · 비밀번호 {age}일째(90일 만료)" if age is not None else ""
    lines = [
        f"🔎 <b>수급 소스 진단</b> (기준일 {target_date.isoformat()})",
        f"pykrx {pykrx_ver} · KRX 자격증명 {cred}{age_txt}",
    ]
    t0 = time.monotonic()
    worker, reason = await _run_krx_worker_uncached(target_date)
    took = round(time.monotonic() - t0, 1)
    if worker and worker.get("market_flow"):
        mf = worker["market_flow"]
        lines.append(
            f"1) KRX ✅ {took}s — 외인 {mf['foreign_net_billion']:+,.0f} · "
            f"기관 {mf['institution_net_billion']:+,.0f} · 개인 {mf['retail_net_billion']:+,.0f}억 · "
            f"TOP {len(worker.get('top_traders') or [])}종목"
        )
    else:
        lines.append(f"1) KRX ❌ {took}s — {krx_reason_text(reason)}")
        err = load_last_krx_error()
        if err and err.get("detail"):
            tail = "\n".join(err["detail"].splitlines()[-4:])
            lines.append(f"<pre>{html.escape(tail[:600])}</pre>")
    naver = await _fetch_naver_market_flow(target_date)
    if naver:
        lines.append(
            f"2) 네이버 ✅ — 외인 {naver['foreign_net_billion']:+,.0f} · "
            f"기관 {naver['institution_net_billion']:+,.0f} · 개인 {naver['retail_net_billion']:+,.0f}억"
        )
    else:
        lines.append(f"2) 네이버 ❌ — {html.escape(_last_naver_note or '사유 미기록')}")
    cached = _load_fresh_cache()
    if cached and cached.get("market_flow"):
        lines.append(f"3) 캐시 ✅ — 기준일 {cached['market_flow'].get('trade_date')}")
    else:
        lines.append("3) 캐시 ❌ — 없음/7일 초과")
    return "\n".join(lines)


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
