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


__all__ = [
    "fetch_close_history",
    "fetch_last_close",
    "fetch_close_with_change",
    "fetch_market_cap",
]
