"""감지 시점 피처의 예측력 자동 분석 ("오를 종목" 신호 검증 1단계).

`theme_feature_snapshots`(통과+제외 전체)를 읽어 scan_date 기준 D+5/D+10
수익률(FDR)을 결합하고, 피처별 분위 분석으로 예측력을 점검한다. 숫자 계산은
결정론적 — 최종 해석·판단은 사람(또는 Claude)이 한다.

통계 설계 (in-sample 스누핑 방지):
- 시점 분할 홀드아웃: scan_date 기준 전반 60%(train) / 후반 40%(val).
  픽커 신호 채택은 train에서 diff ≥ 기준 AND val에서 방향 일치일 때만.
- robust 판정: D+5(D0→5)와 **비중첩 구간** D+5→10의 방향 일치.
  (기존 D+5 vs D+10은 구간이 겹쳐 부호 일치가 거의 자동이었음)
- 표본 게이트: 총 건수 + **고유 스캔일 수** 동시 요구.
  같은 날·같은 테마 종목은 강하게 교차상관하므로 건수만으로는 과대평가.
- 생존편향 노출: 가격 조회 실패(거래정지·상폐 가능) 건수를 별도 카운트해
  리포트에 표기한다 (표본에서 조용히 사라지지 않도록).

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
MIN_UNIQUE_DATES = 60      # 고유 스캔일 최소 (일 단위 교차상관 보정)
MIN_PER_FEATURE = 30       # 피처별 분석 최소 표본 (train/val 각각)
PRIMARY_HORIZON = 10
CONCURRENCY = 4
TRAIN_RATIO = 0.6          # 시점 분할: 전반 60% train / 후반 40% val

# 분석 대상 수치 피처 (단조 분위 비교).
# 제외된 피처와 사유:
# - market_cap: 범위가 244억~1,730조(7백만 배) — 채택 시 픽커가 "매일
#   시총 1위" 출력기로 변질. 시총은 F6 하드 필터로만 사용.
# - institution_net/foreign_net: ka10009가 08:10 장중 미정산 공란이라
#   운영 데이터에 0건 수집됨 (ka10059 히스토리 배선 전까지 분석 무의미).
NUMERIC_FEATURES = [
    "rsi", "ma20_ratio", "ma60_ratio", "return_5d",
    "short_weight_5d", "lending_surge",
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


def _leg_return(
    df: Optional[pd.DataFrame], d0: date, start: int, end: int
) -> Optional[float]:
    """비중첩 구간 수익률: D+start 종가 → D+end 종가 (%)."""
    if df is None or "Close" not in df.columns or df.empty:
        return None
    sub = df[df.index.date >= d0]
    if len(sub) < end + 1:
        return None
    base = float(sub["Close"].iloc[start])
    if base <= 0:
        return None
    return (float(sub["Close"].iloc[end]) / base - 1) * 100


async def _returns_for(code: str, d0: date, sem: asyncio.Semaphore) -> dict[str, Any]:
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
    return {
        "fetch_failed": df is None,   # 거래정지·상폐 가능성 — 생존편향 카운트용
        "ret_5d": _fwd_return(df, d0, 5),
        "ret_10d": _fwd_return(df, d0, PRIMARY_HORIZON),
        "ret_5_10": _leg_return(df, d0, 5, PRIMARY_HORIZON),  # 비중첩 후반 구간
    }


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


def _pairs(
    samples: list[dict[str, Any]], key: str, ret_key: str
) -> list[tuple[float, float]]:
    return [
        (s["features"][key], s[ret_key]) for s in samples
        if s["features"].get(key) is not None and s.get(ret_key) is not None
    ]


async def analyze() -> dict[str, Any]:
    """피처 예측력 분석. 반환: ready/n/리포트 등."""
    async with async_session() as s:
        rows = (await s.execute(select(ThemeFeatureSnapshot))).scalars().all()

    if not rows:
        return {"ready": False, "n": 0, "reason": "스냅샷 0건"}

    sem = asyncio.Semaphore(CONCURRENCY)
    rets = await asyncio.gather(*[_returns_for(r.stock_code, r.scan_date, sem) for r in rows])

    samples: list[dict[str, Any]] = []
    fetch_failed = 0        # 가격 조회 자체 실패 (거래정지·상폐 가능 — 생존편향 후보)
    insufficient_fwd = 0    # 최근 스캔 — 아직 D+10 미경과
    for r, ret in zip(rows, rets):
        if ret["ret_10d"] is None:
            if ret["fetch_failed"]:
                fetch_failed += 1
            else:
                insufficient_fwd += 1
            continue
        samples.append({"features": r.features or {}, "scan_date": r.scan_date, **ret})

    n = len(samples)
    dates = [r.scan_date for r in rows]
    unique_dates = sorted({s["scan_date"] for s in samples})
    gate_info = {
        "n": n, "min": MIN_SAMPLES,
        "unique_dates": len(unique_dates), "min_unique_dates": MIN_UNIQUE_DATES,
        "fetch_failed": fetch_failed, "insufficient_fwd": insufficient_fwd,
        "date_range": f"{min(dates)}~{max(dates)}",
    }
    if n < MIN_SAMPLES or len(unique_dates) < MIN_UNIQUE_DATES:
        return {
            "ready": False, **gate_info,
            "reason": (
                f"표본 부족: D+10 산출 {n}/{MIN_SAMPLES}건, "
                f"고유 스캔일 {len(unique_dates)}/{MIN_UNIQUE_DATES}일"
            ),
        }

    # ── 시점 분할 홀드아웃: 전반 60% 스캔일 train / 후반 40% val ──
    split_idx = max(1, int(len(unique_dates) * TRAIN_RATIO))
    train_dates = set(unique_dates[:split_idx])
    train = [s for s in samples if s["scan_date"] in train_dates]
    val = [s for s in samples if s["scan_date"] not in train_dates]

    results: list[dict[str, Any]] = []
    for key in NUMERIC_FEATURES:
        d_all = _tercile_diff(_pairs(samples, key, "ret_10d"))
        if d_all is None:
            continue
        d_train = _tercile_diff(_pairs(train, key, "ret_10d"))
        d_val = _tercile_diff(_pairs(val, key, "ret_10d"))
        # robust: 비중첩 구간 방향 일치 (D0→5 vs D5→10)
        d_front = _tercile_diff(_pairs(samples, key, "ret_5d"))
        d_back = _tercile_diff(_pairs(samples, key, "ret_5_10"))
        consistent = (
            d_front is not None and d_back is not None
            and (d_front["high_minus_low"] * d_back["high_minus_low"] > 0)
        )
        results.append({
            "feature": key, "n": d_all["n"],
            "diff_10d": d_all["high_minus_low"],
            "train_diff": d_train["high_minus_low"] if d_train else None,
            "val_diff": d_val["high_minus_low"] if d_val else None,
            "diff_5d": d_front["high_minus_low"] if d_front else None,
            "diff_5_10": d_back["high_minus_low"] if d_back else None,
            "consistent": consistent,
            # 픽커 절대 컷 기준값 (전체 표본 중앙값)
            "median": round(statistics.median(
                [p[0] for p in _pairs(samples, key, "ret_10d")]
            ), 4),
        })

    for key in BOOL_FEATURES:
        t = [s["ret_10d"] for s in samples if s["features"].get(key) is True]
        f = [s["ret_10d"] for s in samples if s["features"].get(key) is False]
        if len(t) < MIN_PER_FEATURE or len(f) < MIN_PER_FEATURE:
            continue
        results.append({"feature": key, "n": len(t) + len(f),
                        "diff_10d": round((_mean(t) or 0) - (_mean(f) or 0), 2),
                        "train_diff": None, "val_diff": None,
                        "diff_5d": None, "diff_5_10": None, "consistent": None,
                        "median": None, "note": "True-False"})

    # 예측력 큰 순 (|diff_10d| 내림차순)
    results.sort(key=lambda x: abs(x["diff_10d"]), reverse=True)
    return {
        "ready": True, **gate_info,
        "train_n": len(train), "val_n": len(val),
        "train_range": f"{unique_dates[0]}~{unique_dates[split_idx - 1]}",
        "val_range": f"{unique_dates[split_idx]}~{unique_dates[-1]}",
        "features": results,
    }


PICKER_MIN_DIFF = 2.0  # 픽커 채택 최소 양수 차이(%p) — train 기준


def extract_picker_signals(result: dict[str, Any]) -> list[dict[str, Any]]:
    """분석 결과에서 픽커가 쓸 양수·robust 신호만 추출.

    채택 조건 (모두 충족):
    - train_diff ≥ PICKER_MIN_DIFF (train 구간에서 유의미한 양수)
    - val_diff > 0 (홀드아웃 구간에서 방향 유지 — in-sample 스누핑 방지)
    - consistent (비중첩 D0→5 / D5→10 방향 일치)
    weight는 train_diff를 사용한다 (전체 표본 diff를 쓰면 val 정보 누수).
    없으면 빈 리스트(픽커 작동 안 함).
    """
    signals = []
    for f in result.get("features", []):
        if f.get("feature") in BOOL_FEATURES:
            continue
        if (
            f.get("train_diff") is not None
            and f["train_diff"] >= PICKER_MIN_DIFF
            and f.get("val_diff") is not None
            and f["val_diff"] > 0
            and f.get("consistent") is True
        ):
            signals.append({
                "feature": f["feature"],
                "weight": f["train_diff"],
                "median": f.get("median"),   # 픽커 절대 컷 기준값
            })
    return signals


def format_report(result: dict[str, Any]) -> str:
    if not result.get("ready"):
        return (f"📊 피처 검증 대기 — {result.get('reason', '')} "
                f"(기간 {result.get('date_range', '?')})")
    lines = [
        "📊 <b>피처 예측력 자동 분석 (D+10)</b>",
        f"표본 {result['n']}건 · 고유 스캔일 {result['unique_dates']}일 · 기간 {result['date_range']}",
        f"train {result.get('train_n', '?')}건({result.get('train_range', '?')}) / "
        f"val {result.get('val_n', '?')}건({result.get('val_range', '?')})",
    ]
    if result.get("fetch_failed"):
        lines.append(
            f"⚠️ 가격 조회 실패 {result['fetch_failed']}건 (거래정지·상폐 가능) — "
            f"표본에서 제외됨 (생존편향 주의)"
        )
    lines += [
        "",
        "<b>상위·하위 분위 수익률 차이 (큰 순):</b>",
    ]
    for f in result["features"][:8]:
        flag = ("✅robust" if f.get("consistent")
                else "⚠️불안정" if f.get("consistent") is False else "")
        tv = ""
        if f.get("train_diff") is not None and f.get("val_diff") is not None:
            tv = f" [train {f['train_diff']:+.1f} / val {f['val_diff']:+.1f}]"
        lines.append(f"• {f['feature']}: {f['diff_10d']:+.1f}%p{tv} "
                     f"(N={f['n']}) {flag}")
    lines += [
        "",
        "※ 차이 +이면 '값 클수록 더 오름'. robust=비중첩 D0→5/D5→10 방향 일치.",
        "※ 신호 채택 = train ≥ +2.0%p AND val > 0 AND robust (홀드아웃 통과).",
        "※ 해석·추가 검증은 Claude에 CSV 가져와서: ",
        "   <code>python3 -u -m scripts.export_feature_dataset --out ds.csv</code>",
    ]
    return "\n".join(lines)
