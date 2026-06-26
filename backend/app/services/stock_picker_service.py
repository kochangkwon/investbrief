"""검증된 양수·robust 신호로 "오를 종목 후보"를 점수화·발송.

신호 불문(signal-agnostic): `feature_validation_service`가 찾은 양수·robust
피처(.picker_signals.json)만 사용한다. 신호 파일이 없거나 비면 아무것도
보내지 않는다(없는 신호를 지어내지 않음). 발송 후보는 **잠정·검토용**이며
매수 신호가 아니다(홀드아웃 미검증).

흐름: 검증 잡이 신호를 저장 → 매일 스캔 후 이 서비스가 당일 통과 종목을
그 신호로 점수화 → 상위 N개 텔레그램.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from app.database import async_session
from app.models.theme import ThemeFeatureSnapshot
from app.services import telegram_service

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parents[2] / ".picker_signals.json"
TOP_N = 5


def save_signals(signals: list[dict[str, Any]], validated_at: str) -> None:
    """검증된 신호 저장. signals=[{feature, weight(부호=방향, 양수만)}]."""
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


def _score(candidates: list[dict[str, Any]], signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """양수 신호(높을수록 유리)로 후보 점수화. 모든 신호값 보유 후보만."""
    keys = [s["feature"] for s in signals]
    usable = [c for c in candidates if all(c["features"].get(k) is not None for k in keys)]
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
    """당일 통과 종목을 검증 신호로 점수화 → 상위 후보 텔레그램. 신호 없으면 no-op."""
    signals = load_signals()
    if not signals:
        return False

    async with async_session() as s:
        latest = await s.scalar(
            select(func.max(ThemeFeatureSnapshot.scan_date))
            .where(ThemeFeatureSnapshot.passed.is_(True))
        )
        if latest is None:
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
        return False

    await telegram_service.send_text(_format(scored[:TOP_N], signals, latest))
    logger.info("픽커 후보 발송: %d종목 (scan_date=%s)", min(TOP_N, len(scored)), latest)
    return True


def _format(top: list[dict[str, Any]], signals: list[dict[str, Any]], scan_date) -> str:
    esc = telegram_service.escape_html
    sig_str = ", ".join(f"{s['feature']}(+{s['weight']:.1f}%p)" for s in signals)
    lines = [
        "🎯 <b>오를 종목 후보 (잠정 — 검토용)</b>",
        f"<i>{scan_date} 통과 종목을 검증 신호로 점수화</i>",
        f"<i>기준 신호: {esc(sig_str)}</i>",
        "",
    ]
    for i, c in enumerate(top, 1):
        lines.append(f"{i}. <b>{esc(c['name'])}</b> ({c['code']}) · "
                     f"점수 {c['score']:.2f} · {esc(c['theme'])}")
    lines += [
        "",
        "⚠️ <b>매수 신호 아님.</b> 홀드아웃 미검증 잠정 후보입니다.",
        "최종 판단은 Claude에 CSV 가져와 확인 권장.",
    ]
    return "\n".join(lines)
