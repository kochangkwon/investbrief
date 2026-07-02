"""감지 시점 피처 스냅샷 + 사후 수익률을 CSV로 내보낸다.

`theme_feature_snapshots`(통과+제외 전체)를 읽어 scan_date 기준 D+5/10/20
수익률(FDR)을 on-demand로 결합 → "오를 종목" 신호 검증용 데이터셋.

수익률 컬럼이 비면 아직 거래일이 안 지난 것(최근 스캔). 데이터가 쌓일수록
피처별 예측력을 backtest_*.py 패턴으로 검증할 수 있다.

사용법:
    python3 -u -m scripts.export_feature_dataset                 # 요약만
    python3 -u -m scripts.export_feature_dataset --out ds.csv    # CSV 저장
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import logging
from datetime import date, timedelta
from typing import Any, Optional

import pandas as pd
from sqlalchemy import select

from app.collectors import price_collector
from app.database import async_session
from app.models.theme import ThemeFeatureSnapshot

logging.basicConfig(level=logging.WARNING)

FWD_HORIZONS = (5, 10, 20)
CONCURRENCY = 4


def _fwd_return(df: Optional[pd.DataFrame], d0: date, fwd: int) -> Optional[float]:
    if df is None or "Close" not in df.columns or df.empty:
        return None
    sub = df[df.index.date >= d0]
    if len(sub) < fwd + 1:
        return None
    entry = float(sub["Close"].iloc[0])
    if entry <= 0:
        return None
    return round((float(sub["Close"].iloc[fwd]) / entry - 1) * 100, 2)


async def _returns_for(code: str, d0: date, sem: asyncio.Semaphore) -> dict[str, Optional[float]]:
    async with sem:
        try:
            df = await asyncio.wait_for(
                asyncio.to_thread(
                    price_collector.fetch_close_history, code,
                    start=d0 - timedelta(days=5), end=date.today(),
                ),
                timeout=15,
            )
        except (asyncio.TimeoutError, Exception):
            df = None
    return {f"ret_{h}d": _fwd_return(df, d0, h) for h in FWD_HORIZONS}


async def main(out: Optional[str]) -> None:
    async with async_session() as s:
        rows = (await s.execute(
            select(ThemeFeatureSnapshot).order_by(ThemeFeatureSnapshot.scan_date)
        )).scalars().all()

    if not rows:
        print("스냅샷 0건 — 다음 08:10 테마 스캔부터 누적됩니다.")
        return

    sem = asyncio.Semaphore(CONCURRENCY)
    returns = await asyncio.gather(*[_returns_for(r.stock_code, r.scan_date, sem) for r in rows])

    feature_keys: set[str] = set()
    for r in rows:
        if r.features:
            feature_keys.update(r.features.keys())
    feature_keys = sorted(feature_keys)

    records: list[dict[str, Any]] = []
    for r, ret in zip(rows, returns):
        rec = {
            "scan_date": r.scan_date.isoformat(),
            "theme": r.theme_name,
            "code": r.stock_code,
            "name": r.stock_name,
            "passed": r.passed,
        }
        for k in feature_keys:
            rec[k] = (r.features or {}).get(k)
        rec.update(ret)
        records.append(rec)

    dates = [r.scan_date for r in rows]
    n_pass = sum(1 for r in rows if r.passed)
    n_ret = sum(1 for rec in records if rec.get("ret_10d") is not None)
    print(f"스냅샷 {len(rows)}건 | 기간 {min(dates)}~{max(dates)} "
          f"| 통과 {n_pass} / 제외 {len(rows) - n_pass} | D+10 수익률 산출 {n_ret}건")

    if out:
        cols = (["scan_date", "theme", "code", "name", "passed"]
                + feature_keys + [f"ret_{h}d" for h in FWD_HORIZONS])
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(records)
        print(f"CSV 저장: {out} ({len(records)}행 × {len(cols)}열)")
    else:
        print("(--out 지정 시 CSV 저장. 피처 컬럼:", ", ".join(feature_keys) + ")")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=str, default=None, help="CSV 출력 경로")
    args = ap.parse_args()
    asyncio.run(main(args.out))
