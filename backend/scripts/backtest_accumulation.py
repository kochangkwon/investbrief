"""기관·외국인 순매수(누적수급) 신호의 예측력 백테스트.

"감지일 직전 스마트머니(기관+외국인)가 사 모은 종목이 정말 더 올랐나?"를 검증한다.

신호: ka10059로 감지일 d0 직전 N거래일의 (기관+외국인) 순매수를 거래대금으로
정규화한 **수급 강도**(unit-free, 종목 간 비교 가능).
밴드: 수급 강도 3분위 — 상위(유입강) / 중립 / 하위(유출강).
측정: 감지 후 fwd거래일 수익률(FDR).

판정: 상위(유입) 밴드가 하위(유출) 밴드보다 유의미하게 높으면 → 누적수급은
앞으로 오를 종목 선정에 쓸 가치가 있다 (점수화 구현 정당화).

사용법:
    python3 -m scripts.backtest_accumulation            # D+10, 직전 5거래일 누적
    python3 -m scripts.backtest_accumulation --fwd 5 --win 5

한계: 표본 ~3주·소표본. N을 함께 보고 과신 금지.
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
logger = logging.getLogger("backtest_acc")
logger.setLevel(logging.INFO)

CONCURRENCY = 4


def _as_of_accumulation(
    rows: list[dict[str, Any]], d0: date, win: int
) -> Optional[float]:
    """d0 직전(포함) win거래일의 (기관+외국인) 순매수 / 거래대금 → 수급 강도(%)."""
    upto = [
        r for r in rows
        if r["date"] and r["date"] <= d0.strftime("%Y%m%d")
    ]  # 최신순 가정
    upto = upto[:win]
    if len(upto) < win:
        return None
    net = sum(
        (r["institution_net"] or 0) + (r["foreign_net"] or 0) for r in upto
    )
    val = sum((r["trade_value"] or 0) for r in upto)
    if val <= 0:
        return None
    return net / val * 100


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
    code: str, d0: date, sem: asyncio.Semaphore, fwd_days: int, win: int,
) -> Optional[dict[str, Any]]:
    async with sem:
        inv_rows = await kiwoom_collector.get_investor_history(code)
        price_df = await asyncio.to_thread(
            price_collector.fetch_close_history, code,
            start=d0 - timedelta(days=10), end=date.today(),
        )
    intensity = _as_of_accumulation(inv_rows, d0, win)
    if intensity is None:
        return None
    ret = _fwd_return(price_df, d0, fwd_days)
    if ret is None:
        return None
    return {"code": code, "d0": d0.isoformat(), "intensity": intensity, "ret": ret}


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rets = [r["ret"] for r in rows]
    return {
        "n": len(rows),
        "mean": round(statistics.mean(rets), 2) if rets else None,
        "median": round(statistics.median(rets), 2) if rets else None,
        "win_rate": round(100 * sum(1 for x in rets if x > 0) / len(rets), 0) if rets else None,
    }


async def main(fwd_days: int, win: int) -> None:
    if not kiwoom_collector._enabled():
        print("키움 키 미설정 — 백테스트 불가")
        return

    async with async_session() as s:
        rows = await s.execute(
            select(ThemeDetection.stock_code, ThemeDetection.detected_at)
            .order_by(ThemeDetection.detected_at.asc())
        )
        first_seen: dict[str, date] = {}
        for code, dt in rows.all():
            first_seen.setdefault(code, dt.date())

    print(f"\n대상 유니크 종목: {len(first_seen)} | 수급 윈도우: 직전 {win}거래일 "
          f"| 측정: D+{fwd_days}거래일\n")

    sem = asyncio.Semaphore(CONCURRENCY)
    tasks = [_measure_one(c, d, sem, fwd_days, win) for c, d in first_seen.items()]
    results = [r for r in await asyncio.gather(*tasks) if r is not None]

    if len(results) < 6:
        print(f"측정 성공 {len(results)}건 — 표본 부족. 데이터 더 쌓고 재실행 권장.")
        return

    # 수급 강도 3분위
    results.sort(key=lambda x: x["intensity"])
    n = len(results)
    t1, t2 = n // 3, 2 * n // 3
    low, mid, high = results[:t1], results[t1:t2], results[t2:]

    bands = [
        ("하위 (유출강 — 기관·외국인 순매도)", low),
        ("중립", mid),
        ("상위 (유입강 — 기관·외국인 순매수)", high),
    ]
    print("=" * 70)
    print(f"{'수급 강도 밴드':<38}{'N':>4}{'평균%':>8}{'중앙%':>8}{'승률':>7}{'강도%':>7}")
    print("-" * 70)
    for label, band in bands:
        st = _stats(band)
        avg_int = round(statistics.mean([r["intensity"] for r in band]), 2) if band else 0
        print(f"{label:<36}{st['n']:>4}"
              f"{(st['mean'] if st['mean'] is not None else float('nan')):>8.2f}"
              f"{(st['median'] if st['median'] is not None else float('nan')):>8.2f}"
              f"{(st['win_rate'] if st['win_rate'] is not None else float('nan')):>6.0f}%"
              f"{avg_int:>7.2f}")
    print("=" * 70)

    sl, sh = _stats(low), _stats(high)
    print("\n[판정]")
    if sl["mean"] is None or sh["mean"] is None:
        print("  표본 부족.")
        return
    diff = sh["mean"] - sl["mean"]
    if diff > 2.0:
        print(f"  유입(상위)이 유출(하위)보다 평균 {diff:+.1f}%p 양호 "
              f"→ 누적수급 예측력 있음. 점수화 구현 검토 가치 (N상위={sh['n']}).")
    elif diff < -2.0:
        print(f"  유입이 오히려 {diff:.1f}%p 부진 → 역방향. 점수화 보류.")
    else:
        print(f"  유입-유출 차이 {diff:+.1f}%p로 미미 → 예측력 약함. 점수화 보류, "
              f"데이터 더 쌓고 재검증.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fwd", type=int, default=10, help="측정 거래일 수 (기본 10)")
    ap.add_argument("--win", type=int, default=5, help="감지 직전 수급 누적 거래일 (기본 5)")
    args = ap.parse_args()
    asyncio.run(main(args.fwd, args.win))
