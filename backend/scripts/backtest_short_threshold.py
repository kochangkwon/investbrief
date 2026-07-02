"""공매도 비중 임계값(F7) 12% vs 15% 백테스트.

테마 감지 종목의 **감지일 시점** 공매도 비중을 ka10014로 복원하고, 감지 후
N거래일 실현 수익률(FDR)을 측정해 다음 밴드를 비교한다:

  A) short ≥15% & 상승   — 12·15 둘 다 제외
  B) 12% ≤ short <15% & 상승 — 12면 제외 / 15면 통과  ← 12 vs 15 결정 밴드
  C) 그 외 (통과)         — 12·15 둘 다 통과

판정: B가 C보다 유의미하게 부진하면 12% 인하가 정당화된다.

사용법:
    python3 -m scripts.backtest_short_threshold            # D+10 기본
    python3 -m scripts.backtest_short_threshold --fwd 5    # 측정 구간 변경

한계: 표본은 최근 ~3주 감지분으로 작다. N을 함께 보고 과신 금지.
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

from app.collectors import kiwoom_collector, price_collector
from app.database import async_session
from app.models.theme import ThemeDetection

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger("backtest")
logger.setLevel(logging.INFO)

SHORT_HISTORY_DAYS = 90
CONCURRENCY = 4


def _as_of_short(short_rows: list[dict[str, Any]], d0: date) -> Optional[dict[str, Any]]:
    """감지일 d0 시점(포함, 이전)의 공매도 5일 비중 + 상승 여부 복원."""
    weights = [
        r["short_weight"]
        for r in short_rows
        if r["short_weight"] is not None
        and r["date"]
        and r["date"] <= d0.strftime("%Y%m%d")
    ]  # short_rows는 최신순 → 이미 내림차순
    if len(weights) < 5:
        return None
    recent5 = sum(weights[:5]) / 5
    prev5 = sum(weights[5:10]) / len(weights[5:10]) if len(weights) >= 6 else None
    rising = (prev5 is not None) and (recent5 > prev5)
    return {"short_weight_5d": round(recent5, 2), "rising": rising}


def _bucket(sw5: float, rising: bool) -> str:
    if rising and sw5 >= 15.0:
        return "A"  # ≥15 상승
    if rising and sw5 >= 12.0:
        return "B"  # 12~15 상승 (결정 밴드)
    return "C"      # 통과


def _fwd_return(df: pd.DataFrame, d0: date, fwd_days: int) -> Optional[dict[str, Any]]:
    """d0 이상 첫 거래일 종가 대비 +fwd_days 거래일 종가 수익률(%)."""
    if df is None or "Close" not in df.columns or df.empty:
        return None
    sub = df[df.index.date >= d0]
    if len(sub) < fwd_days + 1:
        return None
    entry = float(sub["Close"].iloc[0])
    exit_ = float(sub["Close"].iloc[fwd_days])
    if entry <= 0:
        return None
    return {
        "entry_date": sub.index[0].date().isoformat(),
        "ret": (exit_ / entry - 1) * 100,
    }


async def _measure_one(
    code: str, d0: date, sem: asyncio.Semaphore, fwd_days: int,
    kospi_df: Optional[pd.DataFrame],
) -> Optional[dict[str, Any]]:
    async with sem:
        short_rows = await kiwoom_collector.get_short_selling(code, days=SHORT_HISTORY_DAYS)
        price_df = await asyncio.to_thread(
            price_collector.fetch_close_history, code,
            start=d0 - timedelta(days=10), end=date.today(),
        )
    asof = _as_of_short(short_rows, d0)
    if asof is None:
        return None
    fwd = _fwd_return(price_df, d0, fwd_days)
    if fwd is None:
        return None
    bucket = _bucket(asof["short_weight_5d"], asof["rising"])
    # KOSPI 대비 alpha (같은 entry_date 기준)
    alpha = None
    kfwd = _fwd_return(kospi_df, date.fromisoformat(fwd["entry_date"]), fwd_days)
    if kfwd is not None:
        alpha = fwd["ret"] - kfwd["ret"]
    return {
        "code": code, "d0": d0.isoformat(), "bucket": bucket,
        "short_5d": asof["short_weight_5d"], "rising": asof["rising"],
        "ret": fwd["ret"], "alpha": alpha,
    }


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rets = [r["ret"] for r in rows]
    alphas = [r["alpha"] for r in rows if r["alpha"] is not None]
    return {
        "n": len(rows),
        "mean": round(statistics.mean(rets), 2) if rets else None,
        "median": round(statistics.median(rets), 2) if rets else None,
        "mean_alpha": round(statistics.mean(alphas), 2) if alphas else None,
        "win_rate": round(100 * sum(1 for x in rets if x > 0) / len(rets), 0) if rets else None,
    }


async def main(fwd_days: int) -> None:
    if not kiwoom_collector._enabled():
        print("키움 키 미설정 — 백테스트 불가")
        return

    # 종목별 최초 감지일 (중복 감지 더블카운트 방지)
    async with async_session() as s:
        rows = await s.execute(
            select(ThemeDetection.stock_code, ThemeDetection.detected_at)
            .order_by(ThemeDetection.detected_at.asc())
        )
        first_seen: dict[str, date] = {}
        for code, dt in rows.all():
            first_seen.setdefault(code, dt.date())

    print(f"\n대상 유니크 종목: {len(first_seen)} | 측정 구간: D+{fwd_days} 거래일\n")

    kospi_df = await asyncio.to_thread(
        price_collector.fetch_close_history, "KS11",
        start=date(2026, 5, 20), end=date.today(),
    )

    sem = asyncio.Semaphore(CONCURRENCY)
    tasks = [_measure_one(c, d, sem, fwd_days, kospi_df) for c, d in first_seen.items()]
    results = [r for r in await asyncio.gather(*tasks) if r is not None]

    by_bucket: dict[str, list[dict[str, Any]]] = {"A": [], "B": [], "C": []}
    for r in results:
        by_bucket[r["bucket"]].append(r)

    labels = {
        "A": "≥15% 상승 (12·15 둘 다 제외)",
        "B": "12~15% 상승 (12면 제외/15면 통과) ★결정밴드",
        "C": "통과 (12·15 둘 다 통과)",
    }
    print("=" * 64)
    print(f"{'밴드':<32}{'N':>4}{'평균%':>8}{'중앙%':>8}{'α평균':>8}{'승률':>6}")
    print("-" * 64)
    for b in ("A", "B", "C"):
        st = _stats(by_bucket[b])
        print(f"{labels[b]:<30}{st['n']:>4}"
              f"{(st['mean'] if st['mean'] is not None else float('nan')):>8.2f}"
              f"{(st['median'] if st['median'] is not None else float('nan')):>8.2f}"
              f"{(st['mean_alpha'] if st['mean_alpha'] is not None else float('nan')):>8.2f}"
              f"{(st['win_rate'] if st['win_rate'] is not None else float('nan')):>5.0f}%")
    print("=" * 64)

    # 결정 밴드(B) 구성 종목 공개 (소표본이라 개별 확인)
    print("\n[B 밴드 구성 — 12~15% 상승 종목]")
    for r in sorted(by_bucket["B"], key=lambda x: x["ret"]):
        print(f"  {r['code']} d0={r['d0']} short={r['short_5d']}% ret={r['ret']:+.1f}% "
              f"alpha={r['alpha']:+.1f}%" if r["alpha"] is not None
              else f"  {r['code']} d0={r['d0']} short={r['short_5d']}% ret={r['ret']:+.1f}%")

    # 정량 판정
    sb, sc = _stats(by_bucket["B"]), _stats(by_bucket["C"])
    print("\n[판정]")
    if sb["n"] < 3:
        print(f"  B밴드 표본 {sb['n']}건 — 통계적 판단 불가. 데이터 더 쌓고 재실행 권장.")
    elif sb["mean"] is not None and sc["mean"] is not None:
        diff = sb["mean"] - sc["mean"]
        if diff < -2.0:
            print(f"  B가 C보다 평균 {diff:.1f}%p 부진 → 12% 인하에 근거 있음 (단 N={sb['n']} 유의).")
        elif diff > 2.0:
            print(f"  B가 C보다 평균 {diff:+.1f}%p 양호 → 12% 인하는 좋은 종목 제거 위험. 15% 유지 권장.")
        else:
            print(f"  B와 C 차이 {diff:+.1f}%p로 미미 → 12% 인하 근거 약함. 15% 유지 권장.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fwd", type=int, default=10, help="측정 거래일 수 (기본 10)")
    args = ap.parse_args()
    asyncio.run(main(args.fwd))
