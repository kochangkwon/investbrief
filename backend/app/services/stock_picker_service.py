"""검증된 양수·robust 신호로 "오를 종목 후보"를 점수화·발송.

신호 불문(signal-agnostic): `feature_validation_service`가 찾은 양수·robust
피처(.picker_signals.json)만 사용한다. 신호 파일이 없거나 비면 아무것도
보내지 않는다(없는 신호를 지어내지 않음). 발송 후보는 **잠정·검토용**이며
매수 신호가 아니다(홀드아웃은 시점 분할 1회 — 표본 국면 다양성 미확보).

안전장치:
- 신선도 가드: 오늘 스캔(completed)의 스냅샷만 사용. 스캔 지연·실패 시
  어제 후보를 오늘 것처럼 발송하지 않는다 (no-op + 로그).
- 절대 컷: 순위 정규화만으로는 "그날 후보 전부가 나빠도 상위 N개 발송"이
  되므로, 검증 시점 히스토리 중앙값 이상인 신호 가중치가 총 가중치의 절반
  이상인 후보만 발송한다. 기준 미달이면 0건 발송.

흐름: 검증 잡이 신호를 저장 → 매일 스캔 완료 직후(체이닝) 이 서비스가
당일 통과 종목을 그 신호로 점수화 → 절대 컷 통과 상위 N개 텔레그램.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from app.database import async_session
from app.models.theme import ThemeFeatureSnapshot, ThemeScanRun
from app.services import telegram_service
from app.utils.timezone import today_kst

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parents[2] / ".picker_signals.json"
TOP_N = 5
# 절대 컷: 히스토리 중앙값 이상인 신호의 가중치 합 ≥ 총 가중치 × 이 비율
ABSOLUTE_CUT_WEIGHT_RATIO = 0.5


def save_signals(signals: list[dict[str, Any]], validated_at: str) -> None:
    """검증된 신호 저장. signals=[{feature, weight(부호=방향, 양수만), median}]."""
    CONFIG_PATH.write_text(
        json.dumps({"validated_at": validated_at, "signals": signals},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_signals() -> list[dict[str, Any]]:
    if not CONFIG_PATH.exists():
        return []
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("signals", [])
    except Exception:
        logger.exception("picker 신호 파일 읽기 실패")
        return []


def _rank_norm(values: list[float]) -> list[float]:
    """값 → [0,1] 순위 정규화 (큰 값일수록 1). 동률은 평균 순위."""
    n = len(values)
    if n == 1:
        return [0.5]
    order = sorted(range(n), key=lambda i: values[i])
    norm = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + j) / 2 / (n - 1)
        for k in range(i, j + 1):
            norm[order[k]] = avg_rank
        i = j + 1
    return norm


def _passes_absolute_cut(
    features: dict[str, Any], signals: list[dict[str, Any]]
) -> bool:
    """절대 컷: 히스토리 중앙값 이상인 신호 가중치 합 ≥ 총 가중치 × 비율.

    median이 없는 신호(레거시 신호 파일)는 통과로 간주(컷 무력) —
    새 검증 잡이 median을 저장하면 자동으로 활성화된다.
    """
    total_w = sum(abs(s["weight"]) for s in signals)
    if total_w <= 0:
        return True
    passed_w = 0.0
    for s in signals:
        median = s.get("median")
        value = features.get(s["feature"])
        if median is None or (value is not None and value >= median):
            passed_w += abs(s["weight"])
    return passed_w >= total_w * ABSOLUTE_CUT_WEIGHT_RATIO


def _score(candidates: list[dict[str, Any]], signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """양수 신호(높을수록 유리)로 후보 점수화. 모든 신호값 보유 + 절대 컷 통과만."""
    keys = [s["feature"] for s in signals]
    usable = [
        c for c in candidates
        if all(c["features"].get(k) is not None for k in keys)
        and _passes_absolute_cut(c["features"], signals)
    ]
    if not usable:
        return []
    total_w = sum(abs(s["weight"]) for s in signals) or 1.0
    norms = {
        k: _rank_norm([c["features"][k] for c in usable])
        for k in keys
    }
    scored = []
    for idx, c in enumerate(usable):
        score = sum(norms[s["feature"]][idx] * (abs(s["weight"]) / total_w) for s in signals)
        scored.append({**c, "score": round(score, 3)})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


async def run_and_send() -> bool:
    """당일 통과 종목을 검증 신호로 점수화 → 상위 후보 텔레그램. 신호 없으면 no-op.

    신선도 가드: 오늘 스캔이 completed 상태이고 오늘자 스냅샷이 있어야 발송.
    (스캔 지연·실패·부분 완료 시 어제 후보를 오늘 것처럼 발송하지 않는다)
    """
    signals = load_signals()
    if not signals:
        return False

    today = today_kst()
    async with async_session() as s:
        run = await s.scalar(
            select(ThemeScanRun).where(ThemeScanRun.scan_date == today)
        )
        if run is None or run.status != "completed":
            logger.info(
                "픽커 스킵: 오늘(%s) 스캔 미완료 (status=%s)",
                today, getattr(run, "status", None),
            )
            return False

        latest = await s.scalar(
            select(func.max(ThemeFeatureSnapshot.scan_date))
            .where(ThemeFeatureSnapshot.passed.is_(True))
        )
        if latest != today:
            logger.info("픽커 스킵: 오늘자 통과 스냅샷 없음 (latest=%s)", latest)
            return False
        rows = (await s.execute(
            select(ThemeFeatureSnapshot)
            .where(ThemeFeatureSnapshot.scan_date == latest)
            .where(ThemeFeatureSnapshot.passed.is_(True))
        )).scalars().all()

    candidates = [
        {"code": r.stock_code, "name": r.stock_name, "theme": r.theme_name,
         "features": r.features or {}}
        for r in rows
    ]
    scored = _score(candidates, signals)
    if not scored:
        logger.info("픽커: 절대 컷 통과 후보 0건 (전체 %d건) — 발송 없음", len(candidates))
        return False

    await telegram_service.send_text(_format(scored[:TOP_N], signals, latest, len(candidates)))
    logger.info("픽커 후보 발송: %d종목 (scan_date=%s)", min(TOP_N, len(scored)), latest)
    return True


def _format(
    top: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    scan_date,
    total_candidates: int,
) -> str:
    esc = telegram_service.escape_html
    sig_str = ", ".join(f"{s['feature']}(+{s['weight']:.1f}%p)" for s in signals)
    lines = [
        "🎯 <b>오를 종목 후보 (잠정 — 검토용)</b>",
        f"<i>{scan_date} 통과 {total_candidates}종목 중 절대 컷 통과분을 점수화</i>",
        f"<i>기준 신호: {esc(sig_str)}</i>",
        "",
    ]
    for i, c in enumerate(top, 1):
        lines.append(f"{i}. <b>{esc(c['name'])}</b> ({c['code']}) · "
                     f"점수 {c['score']:.2f} · {esc(c['theme'])}")
    lines += [
        "",
        "⚠️ <b>매수 신호 아님.</b> 시점분할 홀드아웃 1회 통과한 잠정 후보입니다.",
        "최종 판단은 Claude에 CSV 가져와 확인 권장.",
    ]
    return "\n".join(lines)
