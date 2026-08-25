"""FDR 종가 조회 통합 — 모든 가격 데이터 fetch 진입점.

설계:
- sync 함수만 제공. 호출 측에서 `asyncio.to_thread`로 감싸 사용.
- raw `DataFrame` 반환이 기본. 도메인 후처리(RSI/MA/round 단위 등)는 호출 측 책임.
- 흔한 후처리(target 이전 마지막 종가, 종가+변동률)만 헬퍼로 제공.

이 모듈은 `import FinanceDataReader`를 캡슐화한다 — 다른 모듈은 fdr를 직접 import하지 말고
이 모듈의 함수를 사용할 것.
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Any, Optional, Union

import FinanceDataReader as fdr
import httpx
import pandas as pd

from app.utils.timezone import today_kst

logger = logging.getLogger(__name__)

DateLike = Union[date, str]

# fetch_last_close 기본 lookback (주말/공휴일 보정)
DEFAULT_LAST_CLOSE_LOOKBACK_DAYS = 10
# fetch_close_with_change 기본 lookback (전일 종가 1건이라도 확보)
DEFAULT_CHANGE_LOOKBACK_DAYS = 14

# KRX 지수 API 차단(data.krx.co.kr 'LOGOUT') 대응 — FDR 지수 코드를 네이버 지수 API로 우회.
# 개별 종목은 FDR가 정상 동작하므로 지수 코드만 라우팅한다.
_FDR_TO_NAVER_INDEX = {"KS11": "KOSPI", "KQ11": "KOSDAQ"}
_NAVER_INDEX_PRICE_URL = "https://m.stock.naver.com/api/index/{code}/price"


def _fetch_naver_index_history(
    reuters_code: str, start: date, end: date, *, max_pages: int = 10
) -> Optional[pd.DataFrame]:
    """네이버 모바일 지수 API로 일별 종가 조회 (KRX 지수 차단 대체).

    start 이전 데이터가 나올 때까지 페이지를 넘겨 수집한 뒤 [start, end]로 자른다.
    반환: Date index + Close 컬럼 DataFrame (FDR와 동일 인터페이스) or None.
    """
    rows: list[dict[str, Any]] = []
    try:
        for page in range(1, max_pages + 1):
            resp = httpx.get(
                _NAVER_INDEX_PRICE_URL.format(code=reuters_code),
                params={"pageSize": 20, "page": page},
                headers=_NAVER_MCAP_HEADERS,
                timeout=8.0,
            )
            resp.raise_for_status()
            data = resp.json()
            if not data:
                break
            oldest: Optional[date] = None
            for item in data:
                traded = item.get("localTradedAt")
                close_raw = (item.get("closePrice") or "").replace(",", "")
                if not traded or not close_raw:
                    continue
                oldest = pd.to_datetime(traded).date()
                rows.append({"Date": traded, "Close": float(close_raw)})
            if oldest is not None and oldest <= start:
                break
    except Exception as e:
        logger.warning("네이버 지수 조회 실패 %s [%s..%s]: %s", reuters_code, start, end, e)
        return None

    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.drop_duplicates("Date").set_index("Date").sort_index()
    df = df.loc[str(start):str(end)]
    return df if not df.empty else None


def fetch_close_history(
    code: str,
    *,
    start: DateLike,
    end: Optional[DateLike] = None,
) -> Optional[pd.DataFrame]:
    """FDR로 종목/지수 OHLCV 시계열 조회.

    Args:
        code: FDR 종목/지수 코드 (e.g., "005930", "KS11")
        start: 시작일 (date or "YYYY-MM-DD")
        end: 종료일 (date or "YYYY-MM-DD"). None이면 오늘까지.

    Returns:
        DataFrame (Date index, Open/High/Low/Close/Volume) or None
        - 빈 DataFrame, 예외, 컬럼 누락 → None
    """
    reuters = _FDR_TO_NAVER_INDEX.get(code)
    if reuters is not None:
        start_d = pd.to_datetime(start).date()
        end_d = pd.to_datetime(end).date() if end is not None else today_kst()
        return _fetch_naver_index_history(reuters, start_d, end_d)

    try:
        df = (
            fdr.DataReader(code, start, end)
            if end is not None
            else fdr.DataReader(code, start)
        )
    except Exception as e:
        logger.warning("FDR 조회 실패 %s [%s..%s]: %s", code, start, end, e)
        return None
    if df is None or df.empty:
        return None
    return df


def fetch_last_close(
    code: str,
    *,
    on_or_before: Optional[date] = None,
    lookback_days: int = DEFAULT_LAST_CLOSE_LOOKBACK_DAYS,
) -> Optional[float]:
    """기준일 이전(포함) 가장 최근 영업일 종가.

    Args:
        code: FDR 종목/지수 코드
        on_or_before: 기준일 (None이면 오늘까지 조회)
        lookback_days: 주말/공휴일 보정용 lookback (기본 10일)

    Returns:
        float close (0인 경우 None 반환 — 호출 측 호환), or None
    """
    target = on_or_before or today_kst()
    start = target - timedelta(days=lookback_days)
    df = fetch_close_history(code, start=start, end=target)
    if df is None:
        return None
    if on_or_before is not None:
        df = df[df.index.date <= on_or_before]
        if df.empty:
            return None
    try:
        close = float(df["Close"].iloc[-1])
    except Exception:
        return None
    return close if close else None


def fetch_close_with_change(
    code: str,
    *,
    target_date: Optional[date] = None,
    lookback_days: int = DEFAULT_CHANGE_LOOKBACK_DAYS,
) -> Optional[dict[str, float]]:
    """기준일 종가 + 전일 대비 변동.

    Args:
        code: FDR 종목/지수 코드
        target_date: 기준일 (None이면 최근 영업일)
        lookback_days: 전일 종가 1건 확보용 lookback (기본 14일)

    Returns:
        {"close": float, "change": float, "change_pct": float} or None
        - 데이터 1건만 있으면 change=0.0
        - round 단위는 호출 측 책임
    """
    anchor = target_date or today_kst()
    start = anchor - timedelta(days=lookback_days)
    end = anchor + timedelta(days=1)
    df = fetch_close_history(code, start=start, end=end)
    if df is None:
        return None
    if target_date is not None:
        df = df[df.index.date <= target_date]
        if df.empty:
            return None

    try:
        close = float(df["Close"].iloc[-1])
    except Exception:
        return None

    if len(df) >= 2:
        try:
            prev_close = float(df["Close"].iloc[-2])
            change = close - prev_close
            change_pct = (change / prev_close) * 100 if prev_close else 0.0
        except Exception:
            change = 0.0
            change_pct = 0.0
    else:
        change = 0.0
        change_pct = 0.0

    return {"close": close, "change": change, "change_pct": change_pct}


# 모듈 레벨 캐시: (조회일, {code: marcap})
_NAVER_MCAP_URL = "https://m.stock.naver.com/api/stock/{code}/integration"
_NAVER_MCAP_HEADERS = {"User-Agent": "Mozilla/5.0"}
# 종목별 시총 캐시: code -> (조회일, 시총 or 규약값 -1)
_marcap_code_cache: dict[str, tuple[date, int]] = {}


def _parse_naver_marketvalue(raw: str) -> Optional[int]:
    """네이버 시총 문자열('1,976조 422억')을 원 단위 int로 변환."""
    if not raw:
        return None
    s = raw.replace(",", "").replace(" ", "")
    won = 0
    m = re.search(r"(\d+)조", s)
    if m:
        won += int(m.group(1)) * 10**12
    m = re.search(r"(\d+)억", s)
    if m:
        won += int(m.group(1)) * 10**8
    if won == 0 and s.isdigit():  # '조'/'억' 없이 숫자만(드묾) — 원 단위로 간주
        won = int(s)
    return won if won > 0 else None


def fetch_market_cap(stock_code: str) -> Optional[int]:
    """시총(원). 네이버 금융 종목 API 기반.

    반환 규약 (기존 유지):
    - int > 0: 정상 시총
    - -1: 응답은 정상이나 시총 정보 없음 (상장폐지/ETF 등) → 호출 측 제외 권장
    - None: 조회 실패(네트워크/HTTP) → 호출 측 정책 판단 (fail-closed)

    prefilter_service에서만 사용. KRX(FDR/pykrx) 시총 API 차단 대응으로 네이버로 전환.
    """
    today = today_kst()
    cached = _marcap_code_cache.get(stock_code)
    if cached and cached[0] == today:
        return cached[1]

    try:
        resp = httpx.get(
            _NAVER_MCAP_URL.format(code=stock_code),
            headers=_NAVER_MCAP_HEADERS,
            timeout=8.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        if 400 <= e.response.status_code < 500:  # 없는 종목(404/409 등) → 제외 규약 -1
            _marcap_code_cache[stock_code] = (today, -1)
            return -1
        logger.warning("네이버 시총 조회 실패 (%s): %s", stock_code, e)
        return None  # 5xx 등 일시 장애 — 캐시 안 함, 재시도 여지
    except Exception as e:
        logger.warning("네이버 시총 조회 실패 (%s): %s", stock_code, e)
        return None  # 네트워크/타임아웃 — 캐시 안 함, 재시도 여지

    raw = None
    for item in data.get("totalInfos", []):
        if item.get("code") == "marketValue":
            raw = item.get("value")
            break

    mcap = _parse_naver_marketvalue(raw) if raw else None
    result = mcap if mcap else -1
    _marcap_code_cache[stock_code] = (today, result)
    return result


# ── 글로벌 지표 네이버 폴백 (P2) ────────────────────────────────────
# yfinance와 FDR 해외지표는 **둘 다 query2.finance.yahoo.com**을 백엔드로 쓴다
# (실측 확인). 따라서 Yahoo가 막히면 동시에 죽는다 — 네이버가 현재 유일한
# 독립 소스다. VIX·환율은 Finnhub 무료 플랜(ETF 전용)으로도 대체 불가라
# 위험진단 2축이 통째로 사라지는 원인이었다.
#
# 엔드포인트는 격리 환경에서 실측 확정이 불가능했으므로 후보를 순차 시도하고
# 성공한 URL을 프로세스 수명 동안 기억한다. 실제 확인:
#     python3 scripts/probe_naver_global.py
_NAVER_GLOBAL_CANDIDATES: dict[str, tuple[str, ...]] = {
    "vix": (
        "https://m.stock.naver.com/api/index/.VIX/price?pageSize=5&page=1",
        "https://api.stock.naver.com/index/.VIX/price?pageSize=5&page=1",
        "https://api.stock.naver.com/index/CBOE@VIX/price?pageSize=5&page=1",
    ),
    "usdkrw": (
        "https://m.stock.naver.com/front-api/marketIndex/prices"
        "?category=exchange&reutersCode=FX_USDKRW&page=1&pageSize=5",
        "https://api.stock.naver.com/marketindex/exchange/FX_USDKRW/prices"
        "?page=1&pageSize=5",
    ),
}

# kind -> 성공한 URL (프로세스 수명 — 매번 전 후보를 훑지 않도록)
_naver_global_winner: dict[str, str] = {}

_NAVER_ROW_CONTAINERS = ("result", "datas", "priceList", "prices", "list")
_NAVER_CLOSE_FIELDS = ("closePrice", "closeprice", "nv", "price", "value")
_NAVER_DATE_FIELDS = ("localTradedAt", "localTradedAtDate", "dt", "date")


def _naver_rows(payload: Any) -> list[dict[str, Any]]:
    """네이버 응답에서 시세 행 리스트 추출 (스키마 변형 흡수, 순수 함수).

    list / {"result": [...]} / {"result": {"datas": [...]}} 등을 모두 처리한다.
    """
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for key in _NAVER_ROW_CONTAINERS:
            value = payload.get(key)
            if isinstance(value, list):
                return [r for r in value if isinstance(r, dict)]
            if isinstance(value, dict):
                for inner in _NAVER_ROW_CONTAINERS:
                    nested = value.get(inner)
                    if isinstance(nested, list):
                        return [r for r in nested if isinstance(r, dict)]
    return []


def _naver_row_close(row: dict[str, Any]) -> Optional[float]:
    """행에서 종가 추출 ('1,350.50' 같은 문자열 포함). 순수 함수."""
    for field in _NAVER_CLOSE_FIELDS:
        raw = row.get(field)
        if raw is None:
            continue
        try:
            value = float(str(raw).replace(",", "").strip())
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


def _naver_sorted_closes(rows: list[dict[str, Any]]) -> list[float]:
    """최신순 종가 리스트. 날짜 필드가 있으면 내림차순 정렬 (순수 함수)."""
    def _date_key(row: dict[str, Any]) -> str:
        for field in _NAVER_DATE_FIELDS:
            value = row.get(field)
            if value:
                return str(value)
        return ""

    if any(_date_key(r) for r in rows):
        rows = sorted(rows, key=_date_key, reverse=True)
    closes = [_naver_row_close(r) for r in rows]
    return [c for c in closes if c is not None]


def fetch_naver_global_quote(kind: str) -> Optional[dict[str, float]]:
    """네이버로 글로벌 지표 종가·등락 조회. 실패 시 None (0.0 채움 금지).

    Args:
        kind: "vix" | "usdkrw" (_NAVER_GLOBAL_CANDIDATES 키)

    Returns:
        {"close": float, "change": float, "change_pct": float} or None
    """
    candidates = _NAVER_GLOBAL_CANDIDATES.get(kind)
    if not candidates:
        return None

    winner = _naver_global_winner.get(kind)
    ordered = (
        (winner,) + tuple(c for c in candidates if c != winner)
        if winner else candidates
    )

    for url in ordered:
        try:
            resp = httpx.get(url, headers=_NAVER_MCAP_HEADERS, timeout=8.0)
            resp.raise_for_status()
            closes = _naver_sorted_closes(_naver_rows(resp.json()))
        except Exception as e:
            logger.debug("[naver-global] %s 후보 실패 (%s): %s", kind, url, e)
            continue
        if not closes:
            continue

        close = closes[0]
        if len(closes) >= 2:
            prev = closes[1]
            change = close - prev
            change_pct = (change / prev) * 100
        else:
            change = 0.0
            change_pct = 0.0

        _naver_global_winner[kind] = url
        logger.info(
            "[naver-global] %s 확보: %.2f (%+.2f%%)", kind, close, change_pct
        )
        return {
            "close": round(close, 2),
            "change": round(change, 2),
            "change_pct": round(change_pct, 2),
        }

    logger.warning("[naver-global] %s 전 후보 실패 — 폴백 불가", kind)
    return None


__all__ = [
    "fetch_close_history",
    "fetch_last_close",
    "fetch_close_with_change",
    "fetch_market_cap",
    "fetch_naver_global_quote",
]
