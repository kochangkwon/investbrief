"""과열 필터(F1~F4: RSI·이격·급등) 예측력 백테스트.

"감지일 시점에 과열됐던 종목이 정말 더 떨어졌나?"를 검증한다.
production `prefilter_service._check_price_filters`를 감지일 d0 시점 종가로
그대로 호출 → 동일 임계값으로 위반 여부 판정 (충실도 최대).

밴드:
  - 전체: 과열(F1~F4 중 1개+ 위반) vs 정상
  - 필터별: F1(RSI) / F2(MA20) / F3(MA60) / F4(5일급등) 위반 vs 비위반
측정: 감지 후 fwd거래일 수익률(FDR).

판정: 위반(과열) 밴드가 비위반보다 유의미하게 부진하면 그 필터는 효과 있음.

사용법:
    python3 -m scripts.backtest_overheating            # D+10
    python3 -m scripts.backtest_overheating --fwd 5

한계: 표본 ~3주·소표본·하락장. N을 함께 보고 과신 금지.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import statistics
from datetime import date, timedelta
from typing import Any, Optional

import pandas as pd
from sqlalchemy import select

from app.collectors import price_collector
from app.database import async_session
from app.models.theme import ThemeDetection
from app.services.prefilter_service import (
    PREFILTER_5D_RETURN_MAX,
    PREFILTER_MA20_RATIO_MAX,
    PREFILTER_MA60_RATIO_MAX,
    PREFILTER_RSI_MAX,
    _check_price_filters,
)

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger("backtest_oh")
logger.setLevel(logging.INFO)

CONCURRENCY = 5

# 필터별 (metrics 키, 임계값, "위반" 비교 함수)
FILTERS = [
    ("F1 RSI≥70", "rsi", PREFILTER_RSI_MAX, lambda v, t: v >= t),
    ("F2 MA20 이격", "ma20_ratio", PREFILTER_MA20_RATIO_MAX, lambda v, t: v > t),
    ("F3 MA60 이격", "ma60_ratio", PREFILTER_MA60_RATIO_MAX, lambda v, t: v > t),
    ("F4 5일급등", "return_5d", PREFILTER_5D_RETURN_MAX, lambda v, t: v > t),
]


def _fwd_return(df: Optional[pd.DataFrame], d0: date, fwd_days: int) -> Optional[float]:
    if df is None or "Close" not in df.columns or df.empty:
        return None
    sub = df[df.index.date >= d0]
    if len(sub) < fwd_days + 1:
        return None
    entry = float(sub["Close"].iloc[0])
    exit_ = float(sub["Close"].iloc[fwd_days])
    if entry <= 0:
        return None
    return (exit_ / entry - 1) * 100


async def _measure_one(
    code: str, d0: date, sem: asyncio.Semaphore, fwd_days: int,
) -> Optional[dict[str, Any]]:
    async with sem:
        try:
            df = await asyncio.wait_for(
                asyncio.to_thread(
                    price_collector.fetch_close_history, code,
                    start=d0 - timedelta(days=200), end=date.today(),
                ),
                timeout=15,  # FDR 무응답 시 해당 종목 스킵 (전체 행 방지)
            )
        except (asyncio.TimeoutError, Exception):
            return None
    if df is None or "Close" not in df.columns:
        return None
    closes_upto = [
        float(c) for c in df[df.index.date <= d0]["Close"].tolist() if pd.notna(c)
    ]
    passed, _reasons, metrics = _check_price_filters(closes_upto)
    if passed is None or not metrics:  # 데이터 부족 → 제외
        return None
    ret = _fwd_return(df, d0, fwd_days)
    if ret is None:
        return None
    return {"code": code, "d0": d0.isoformat(),
            "overheated": passed is False, "metrics": metrics, "ret": ret}


def _stats(rets: list[float]) -> dict[str, Any]:
    if not rets:
        return {"n": 0, "mean": None, "median": None, "win": None}
    return {
        "n": len(rets),
        "mean": round(statistics.mean(rets), 2),
        "median": round(statistics.median(rets), 2),
        "win": round(100 * sum(1 for x in rets if x > 0) / len(rets), 0),
    }


def _print_pair(label: str, viol: list[float], ok: list[float]) -> None:
    sv, so = _stats(viol), _stats(ok)
    diff = (sv["mean"] - so["mean"]) if (sv["mean"] is not None and so["mean"] is not None) else None
    diff_s = f"{diff:+.1f}" if diff is not None else "  · "
    print(f"{label:<16}"
          f"위반 N={sv['n']:>3} 평균={_f(sv['mean']):>7} 승률={_p(sv['win']):>4} | "
          f"정상 N={so['n']:>3} 평균={_f(so['mean']):>7} 승률={_p(so['win']):>4} | "
          f"차이={diff_s}%p")


def _f(v: Optional[float]) -> str:
    return f"{v:.2f}" if v is not None else "  nan"


def _p(v: Optional[float]) -> str:
    return f"{v:.0f}%" if v is not None else "nan"


async def main(fwd_days: int) -> None:
    async with async_session() as s:
        rows = await s.execute(
            select(ThemeDetection.stock_code, ThemeDetection.detected_at)
            .order_by(ThemeDetection.detected_at.asc())
        )
        first_seen: dict[str, date] = {}
        for code, dt in rows.all():
            first_seen.setdefault(code, dt.date())

    print(f"\n대상 유니크 종목: {len(first_seen)} | 측정: D+{fwd_days}거래일\n")

    sem = asyncio.Semaphore(CONCURRENCY)
    tasks = [_measure_one(c, d, sem, fwd_days) for c, d in first_seen.items()]
    results = [r for r in await asyncio.gather(*tasks) if r is not None]

    if len(results) < 6:
        print(f"측정 성공 {len(results)}건 — 표본 부족.")
        return

    print(f"측정 성공 {len(results)}종목\n")
    print("=" * 92)

    # 전체: 과열 vs 정상
    oh = [r["ret"] for r in results if r["overheated"]]
    norm = [r["ret"] for r in results if not r["overheated"]]
    _print_pair("[전체] 과열여부", oh, norm)
    print("-" * 92)

    # 필터별
    for label, key, thr, is_viol in FILTERS:
        viol, ok = [], []
        for r in results:
            v = r["metrics"].get(key)
            if v is None:
                continue
            (viol if is_viol(v, thr) else ok).append(r["ret"])
        _print_pair(label, viol, ok)
    print("=" * 92)

    print("\n[판정] (위반 밴드가 정상보다 -2%p+ 부진 = 그 필터 효과 있음)")
    so = _stats(oh)
    sn = _stats(norm)
    if so["mean"] is not None and sn["mean"] is not None:
        d = so["mean"] - sn["mean"]
        verdict = ("과열 필터 전체 효과 있음" if d < -2 else
                   "과열이 오히려 양호 — 역방향" if d > 2 else "차이 미미 — 효과 약함")
        print(f"  전체 과열군 vs 정상군: {d:+.1f}%p → {verdict}")
    print("  ※ 필터별 차이를 함께 보고, 효과 없는 필터는 완화/제거 후보로 검토.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fwd", type=int, default=10, help="측정 거래일 수 (기본 10)")
    args = ap.parse_args()
    asyncio.run(main(args.fwd))
