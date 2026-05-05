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
from datetime import date, timedelta
from typing import Any, Optional, Union

import FinanceDataReader as fdr
import pandas as pd

logger = logging.getLogger(__name__)

DateLike = Union[date, str]

# fetch_last_close 기본 lookback (주말/공휴일 보정)
DEFAULT_LAST_CLOSE_LOOKBACK_DAYS = 10
# fetch_close_with_change 기본 lookback (전일 종가 1건이라도 확보)
DEFAULT_CHANGE_LOOKBACK_DAYS = 14


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
    target = on_or_before or date.today()
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
    anchor = target_date or date.today()
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


def fetch_market_cap(stock_code: str) -> Optional[int]:
    """KOSPI/KOSDAQ에서 종목코드의 시총(원) 조회.

    prefilter_service에서만 사용하나 fdr 의존성을 collectors로 모으기 위해 함께 위치.
    """
    for market in ("KOSPI", "KOSDAQ"):
        try:
            df = fdr.StockListing(market)
        except Exception as e:
            logger.warning(
                "StockListing 실패 (%s, %s): %s", market, stock_code, e,
            )
            continue
        if df is None or df.empty:
            continue
        if "Code" not in df.columns or "Marcap" not in df.columns:
            continue
        row = df[df["Code"] == stock_code]
        if row.empty:
            continue
        try:
            return int(row["Marcap"].iloc[0])
        except Exception:
            return None
    return None


__all__ = [
    "fetch_close_history",
    "fetch_last_close",
    "fetch_close_with_change",
    "fetch_market_cap",
]
