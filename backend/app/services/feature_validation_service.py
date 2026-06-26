"""감지 시점 피처의 예측력 자동 분석 ("오를 종목" 신호 검증 1단계).

`theme_feature_snapshots`(통과+제외 전체)를 읽어 scan_date 기준 D+5/D+10
수익률(FDR)을 결합하고, 피처별 분위 분석으로 예측력을 점검한다. 숫자 계산은
결정론적 — 최종 해석·판단은 사람(또는 Claude)이 한다.

스케줄러가 목표일 이후 호출 → 게이트 통과 시 텔레그램 리포트 발송.
수동 실행: `python3 -u -m scripts.analyze_feature_dataset`
"""
from __future__ import annotations

import asyncio
import logging
import statistics
from datetime import date, timedelta
from typing import Any, Optional

import pandas as pd
from sqlalchemy import select

from app.collectors import price_collector
from app.database import async_session
from app.models.theme import ThemeFeatureSnapshot

logger = logging.getLogger(__name__)

MIN_SAMPLES = 200          # D+10 수익률 산출 가능 표본 최소
MIN_PER_FEATURE = 30       # 피처별 분석 최소 표본
PRIMARY_HORIZON = 10
CONCURRENCY = 4

# 분석 대상 수치 피처 (단조 분위 비교)
NUMERIC_FEATURES = [
    "rsi", "ma20_ratio", "ma60_ratio", "return_5d", "market_cap",
    "short_weight_5d", "lending_surge", "institution_net", "foreign_net",
]
BOOL_FEATURES = ["short_weight_rising"]


def _fwd_return(df: Optional[pd.DataFrame], d0: date, fwd: int) -> Optional[float]:
    if df is None or "Close" not in df.columns or df.empty:
        return None
    sub = df[df.index.date >= d0]
    if len(sub) < fwd + 1:
        return None
    entry = float(sub["Close"].iloc[0])
    if entry <= 0:
        return None
    return (float(sub["Close"].iloc[fwd]) / entry - 1) * 100


async def _returns_for(code: str, d0: date, sem: asyncio.Semaphore) -> dict[str, Optional[float]]:
    async with sem:
        try:
            df = await asyncio.wait_for(
                asyncio.to_thread(
                    price_collector.fetch_close_history, code,
                    start=d0 - timedelta(days=5), end=date.today(),
                ),
                timeout=15,  # FDR 무응답 방지
            )
        except (asyncio.TimeoutError, Exception):
            df = None
    return {"ret_5d": _fwd_return(df, d0, 5), "ret_10d": _fwd_return(df, d0, PRIMARY_HORIZON)}


def _mean(xs: list[float]) -> Optional[float]:
    return round(statistics.mean(xs), 2) if xs else None


def _tercile_diff(pairs: list[tuple[float, float]]) -> Optional[dict[str, Any]]:
    """(피처값, 수익률) 쌍 → 상위3분위 - 하위3분위 평균 수익률 차이."""
    if len(pairs) < MIN_PER_FEATURE:
        return None
    pairs = sorted(pairs, key=lambda x: x[0])
    n = len(pairs)
    t = n // 3
    low = [r for _, r in pairs[:t]]
    high = [r for _, r in pairs[-t:]]
    lo, hi = _mean(low), _mean(high)
    if lo is None or hi is None:
        return None
    return {"n": n, "low_mean": lo, "high_mean": hi, "high_minus_low": round(hi - lo, 2)}


async def analyze() -> dict[str, Any]:
    """피처 예측력 분석. 반환: ready/n/리포트 등."""
    async with async_session() as s:
        rows = (await s.execute(select(ThemeFeatureSnapshot))).scalars().all()

    if not rows:
        return {"ready": False, "n": 0, "reason": "스냅샷 0건"}

    sem = asyncio.Semaphore(CONCURRENCY)
    rets = await asyncio.gather(*[_returns_for(r.stock_code, r.scan_date, sem) for r in rows])

    samples: list[dict[str, Any]] = []
    for r, ret in zip(rows, rets):
        if ret["ret_10d"] is None:
            continue
        samples.append({"features": r.features or {}, **ret})

    n = len(samples)
    dates = [r.scan_date for r in rows]
    if n < MIN_SAMPLES:
        return {"ready": False, "n": n, "min": MIN_SAMPLES,
                "date_range": f"{min(dates)}~{max(dates)}",
                "reason": f"D+10 수익률 산출 {n} < {MIN_SAMPLES}"}

    # 피처별 분위 분석 (ret_10d 기준 + ret_5d 부호 일관성)
    results: list[dict[str, Any]] = []
    for key in NUMERIC_FEATURES:
        pairs10 = [(s["features"][key], s["ret_10d"]) for s in samples
                   if s["features"].get(key) is not None]
        d10 = _tercile_diff(pairs10)
        if d10 is None:
            continue
        pairs5 = [(s["features"][key], s["ret_5d"]) for s in samples
                  if s["features"].get(key) is not None and s["ret_5d"] is not None]
        d5 = _tercile_diff(pairs5)
        consistent = d5 is not None and (d5["high_minus_low"] * d10["high_minus_low"] > 0)
        results.append({"feature": key, "n": d10["n"],
                        "diff_10d": d10["high_minus_low"],
                        "diff_5d": d5["high_minus_low"] if d5 else None,
                        "consistent": consistent})

    for key in BOOL_FEATURES:
        t = [s["ret_10d"] for s in samples if s["features"].get(key) is True]
        f = [s["ret_10d"] for s in samples if s["features"].get(key) is False]
        if len(t) < MIN_PER_FEATURE or len(f) < MIN_PER_FEATURE:
            continue
        results.append({"feature": key, "n": len(t) + len(f),
                        "diff_10d": round((_mean(t) or 0) - (_mean(f) or 0), 2),
                        "diff_5d": None, "consistent": None,
                        "note": "True-False"})

    # 예측력 큰 순 (|diff_10d| 내림차순)
    results.sort(key=lambda x: abs(x["diff_10d"]), reverse=True)
    return {
        "ready": True, "n": n, "date_range": f"{min(dates)}~{max(dates)}",
        "features": results,
    }


PICKER_MIN_DIFF = 2.0  # 픽커 채택 최소 양수 차이(%p)


def extract_picker_signals(result: dict[str, Any]) -> list[dict[str, Any]]:
    """분석 결과에서 픽커가 쓸 양수·robust 신호만 추출.

    수치 피처 중 diff_10d ≥ PICKER_MIN_DIFF AND D+5와 부호 일치(robust)만.
    "값 클수록 오른다"가 검증된 신호. 없으면 빈 리스트(픽커 작동 안 함).
    """
    signals = []
    for f in result.get("features", []):
        if f.get("feature") in BOOL_FEATURES:
            continue
        if f["diff_10d"] >= PICKER_MIN_DIFF and f.get("consistent") is True:
            signals.append({"feature": f["feature"], "weight": f["diff_10d"]})
    return signals


def format_report(result: dict[str, Any]) -> str:
    if not result.get("ready"):
        return (f"📊 피처 검증 대기 — {result.get('reason', '')} "
                f"(기간 {result.get('date_range', '?')})")
    lines = [
        "📊 <b>피처 예측력 자동 분석 (D+10)</b>",
        f"표본 {result['n']}건 · 기간 {result['date_range']}",
        "",
        "<b>상위·하위 분위 수익률 차이 (큰 순):</b>",
    ]
    for f in result["features"][:8]:
        flag = ("✅robust" if f.get("consistent")
                else "⚠️불안정" if f.get("consistent") is False else "")
        d5 = f"/{f['diff_5d']:+.1f}(D+5)" if f.get("diff_5d") is not None else ""
        lines.append(f"• {f['feature']}: {f['diff_10d']:+.1f}%p{d5} "
                     f"(N={f['n']}) {flag}")
    lines += [
        "",
        "※ 차이 +이면 '값 클수록 더 오름'. robust=D+5와 방향 일치.",
        "※ 해석·홀드아웃 검증은 Claude에 CSV 가져와서: ",
        "   <code>python3 -u -m scripts.export_feature_dataset --out ds.csv</code>",
    ]
    return "\n".join(lines)
