"""테마 스캔 결과 사전 필터링.

`scan_single_theme`이 Claude 검증 통과한 종목 중 이미 폭등했거나 시총이
너무 작은 종목을 사전 제외해서 StockAI pipeline_agent의 즉시제외 비율을
줄인다.

InvestBrief에는 DART 재무 캐시(`FinancialStatement`) 테이블이 없으므로
F5(EPS < 0) 필터는 보수적 통과로 처리한다 (재무 캐시 추가 시 활성화).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Optional

import pandas as pd

from app.collectors import price_collector

logger = logging.getLogger(__name__)


# ── 임계값 ──────────────────────────────────────────────────────────
PREFILTER_RSI_MAX = 70.0
PREFILTER_MA20_RATIO_MAX = 1.30      # 현재가 ≤ MA20 × 1.30
PREFILTER_MA60_RATIO_MAX = 1.50
PREFILTER_5D_RETURN_MAX = 0.30       # 5일 누적 +30% 미만
PREFILTER_MIN_MARKET_CAP = 50_000_000_000  # 500억 원

PREFILTER_CONCURRENCY = 5


@dataclass
class PrefilterResult:
    """사전 필터 결과 — 통과/제외 여부와 사유, 측정값."""
    code: str
    passed: bool
    reasons: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


# ── 보조 계산 함수 ──────────────────────────────────────────────────


def _calc_rsi(closes: list[float], period: int = 14) -> Optional[float]:
    """단순 RSI. closes는 오름차순(마지막이 최신). 데이터 부족 시 None."""
    if len(closes) < period + 1:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _calc_ma(closes: list[float], period: int) -> Optional[float]:
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


# ── FDR 동기 호출을 스레드풀로 ─────────────────────────────────────


def _fetch_closes_sync(stock_code: str) -> list[float]:
    """직전 180일 종가 (오름차순). 실패/컬럼 누락 시 빈 리스트."""
    end = date.today()
    start = end - timedelta(days=180)
    df = price_collector.fetch_close_history(stock_code, start=start, end=end)
    if df is None or "Close" not in df.columns:
        return []
    return [float(c) for c in df["Close"].tolist() if pd.notna(c)]


async def _fetch_closes(stock_code: str) -> list[float]:
    return await asyncio.to_thread(_fetch_closes_sync, stock_code)


async def _fetch_market_cap(stock_code: str) -> Optional[int]:
    return await asyncio.to_thread(price_collector.fetch_market_cap, stock_code)


# ── 개별 필터 (순수 함수 — 데이터를 받아 판정) ─────────────────────


def _check_price_filters(
    closes: list[float],
) -> tuple[Optional[bool], list[str], dict[str, Any]]:
    """F1~F4: 가격/이격도/모멘텀.

    반환 (passed, reasons, metrics):
    - 데이터 부족 → (None, [reason], {}) → 호출자가 보수적 통과
    - 위반 1개 이상 → (False, [reasons], metrics)
    - 모두 정상 → (True, [], metrics)
    """
    if not closes or len(closes) < 60:
        return None, ["가격 데이터 부족 (<60일)"], {}

    current = closes[-1]
    if current <= 0:
        return None, ["현재가 무효"], {}

    metrics: dict[str, Any] = {"current": current}
    fails: list[str] = []

    rsi = _calc_rsi(closes, 14)
    if rsi is not None:
        metrics["rsi"] = round(rsi, 1)
        if rsi >= PREFILTER_RSI_MAX:
            fails.append(f"F1: RSI {rsi:.1f} ≥ {PREFILTER_RSI_MAX}")

    ma20 = _calc_ma(closes, 20)
    if ma20 and ma20 > 0:
        ratio20 = current / ma20
        metrics["ma20_ratio"] = round(ratio20, 3)
        if ratio20 > PREFILTER_MA20_RATIO_MAX:
            fails.append(
                f"F2: MA20 +{(ratio20 - 1) * 100:.0f}% > "
                f"+{(PREFILTER_MA20_RATIO_MAX - 1) * 100:.0f}%"
            )

    ma60 = _calc_ma(closes, 60)
    if ma60 and ma60 > 0:
        ratio60 = current / ma60
        metrics["ma60_ratio"] = round(ratio60, 3)
        if ratio60 > PREFILTER_MA60_RATIO_MAX:
            fails.append(
                f"F3: MA60 +{(ratio60 - 1) * 100:.0f}% > "
                f"+{(PREFILTER_MA60_RATIO_MAX - 1) * 100:.0f}%"
            )

    if len(closes) >= 6 and closes[-6] > 0:
        ret_5d = (current - closes[-6]) / closes[-6]
        metrics["return_5d"] = round(ret_5d, 3)
        if ret_5d > PREFILTER_5D_RETURN_MAX:
            fails.append(
                f"F4: 5일 +{ret_5d * 100:.1f}% > "
                f"+{PREFILTER_5D_RETURN_MAX * 100:.0f}%"
            )

    if fails:
        return False, fails, metrics
    return True, [], metrics


def _check_market_cap_filter(
    mcap: Optional[int],
) -> tuple[Optional[bool], list[str], dict[str, Any]]:
    """F6: 시총 ≥ PREFILTER_MIN_MARKET_CAP."""
    if mcap is None:
        return None, ["시총 조회 실패"], {}
    if mcap < PREFILTER_MIN_MARKET_CAP:
        return False, [
            f"F6: 시총 {mcap / 1e8:.0f}억 < "
            f"{PREFILTER_MIN_MARKET_CAP / 1e8:.0f}억"
        ], {"market_cap": mcap}
    return True, [], {"market_cap": mcap}


# ── 통합 진입점 ─────────────────────────────────────────────────────


async def prefilter_stock(stock_code: str) -> PrefilterResult:
    """단일 종목 사전 필터.

    F1~F4(가격/이격/모멘텀) + F6(시총)을 적용. F5(EPS)는 InvestBrief에
    재무 캐시 테이블이 없어 보수적 통과 처리. 명백 위반(False)이 하나라도
    있으면 제외, 조회 실패(None)는 통과.
    """
    closes_result, mcap_result = await asyncio.gather(
        _fetch_closes(stock_code),
        _fetch_market_cap(stock_code),
        return_exceptions=True,
    )

    if isinstance(closes_result, Exception):
        logger.warning("[prefilter] %s 가격 예외: %s", stock_code, closes_result)
        closes: list[float] = []
    else:
        closes = closes_result

    if isinstance(mcap_result, Exception):
        logger.warning("[prefilter] %s 시총 예외: %s", stock_code, mcap_result)
        mcap: Optional[int] = None
    else:
        mcap = mcap_result

    price_pass, price_reasons, price_metrics = _check_price_filters(closes)
    mcap_pass, mcap_reasons, mcap_metrics = _check_market_cap_filter(mcap)

    explicitly_failed = price_pass is False or mcap_pass is False
    passed = not explicitly_failed

    return PrefilterResult(
        code=stock_code,
        passed=passed,
        reasons=price_reasons + mcap_reasons,
        metrics={**price_metrics, **mcap_metrics},
    )


async def prefilter_stocks(stock_codes: list[str]) -> dict[str, PrefilterResult]:
    """여러 종목 병렬 필터링 (FDR 부하 고려 — 최대 5건 동시)."""
    if not stock_codes:
        return {}

    semaphore = asyncio.Semaphore(PREFILTER_CONCURRENCY)

    async def _bounded(code: str) -> tuple[str, PrefilterResult]:
        async with semaphore:
            return code, await prefilter_stock(code)

    pairs = await asyncio.gather(*[_bounded(c) for c in stock_codes])
    return dict(pairs)
