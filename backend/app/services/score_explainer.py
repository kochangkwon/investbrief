"""점수 해석 1줄 — 룰 기반. Claude API 호출 X."""
from __future__ import annotations

from typing import Any


def explain_score_brief(score_data: dict[str, Any]) -> str:
    """4차원 점수를 1줄 해석으로.

    Args:
        score_data: {
            "theme_score": float,
            "fundamental_score": float,
            "flow_score": float,
            "chart_score": float,
            "matched_themes": str | None,
        }

    Returns: 해석 문자열 (예: "AI 반도체 강함 / 영업이익률 10%+ / 외인 매수 / 차트 양호")
    """
    parts: list[str] = []

    # 테마
    theme_score = score_data.get("theme_score", 0)
    themes = score_data.get("matched_themes", "")
    if theme_score >= 90:
        themes_short = themes.split(",")[0].strip() if themes else "테마"
        parts.append(f"{themes_short} 강세")
    elif theme_score >= 70:
        themes_short = themes.split(",")[0].strip() if themes else "테마"
        parts.append(f"{themes_short} 부상")
    elif theme_score >= 50:
        parts.append("테마 약함")

    # 펀더멘털
    fundamental = score_data.get("fundamental_score", 50)
    if fundamental >= 85:
        parts.append("영업이익률 10%+")
    elif fundamental >= 65:
        parts.append("흑자")
    elif fundamental <= 30:
        parts.append("⚠️ 적자")

    # 수급 (외인)
    flow = score_data.get("flow_score", 50)
    if flow >= 80:
        parts.append("외인 매수")
    elif flow >= 65:
        parts.append("외인 매수 약함")
    elif flow <= 30:
        parts.append("⚠️ 외인 매도")

    # 차트
    chart = score_data.get("chart_score", 50)
    if chart >= 75:
        parts.append("차트 양호")
    elif chart <= 30:
        parts.append("⚠️ 차트 약함")

    return " / ".join(parts) if parts else "특이사항 없음"


def explain_score_detail(score_data: dict[str, Any]) -> list[str]:
    """상세 해석 (여러 줄, 종목 페이지나 확장 뷰용).

    Returns: 줄 단위 리스트
    """
    lines = []

    theme_score = score_data.get("theme_score", 0)
    themes = score_data.get("matched_themes", "")
    if theme_score >= 70:
        lines.append(f"📈 테마: {theme_score:.0f}점 — {themes or '복수 테마 감지'}")
    elif theme_score > 0:
        lines.append(f"📈 테마: {theme_score:.0f}점 — 약한 매칭")

    fundamental = score_data.get("fundamental_score", 50)
    if fundamental >= 85:
        lines.append(f"💼 펀더: {fundamental:.0f}점 — 흑자 + 영업이익률 10%+ 우량")
    elif fundamental >= 65:
        lines.append(f"💼 펀더: {fundamental:.0f}점 — 흑자")
    elif fundamental <= 30:
        lines.append(f"💼 펀더: {fundamental:.0f}점 — ⚠️ 적자 (주의)")
    else:
        lines.append(f"💼 펀더: {fundamental:.0f}점 — 데이터 부족 (중립)")

    flow = score_data.get("flow_score", 50)
    if flow >= 80:
        lines.append(f"💰 수급: {flow:.0f}점 — 외인 강한 매수")
    elif flow >= 65:
        lines.append(f"💰 수급: {flow:.0f}점 — 외인 매수")
    elif flow <= 30:
        lines.append(f"💰 수급: {flow:.0f}점 — ⚠️ 외인 매도")
    else:
        lines.append(f"💰 수급: {flow:.0f}점 — 중립")

    chart = score_data.get("chart_score", 50)
    if chart >= 75:
        lines.append(f"📊 차트: {chart:.0f}점 — 추세 + 거래량 양호")
    elif chart <= 30:
        lines.append(f"📊 차트: {chart:.0f}점 — ⚠️ 추세 약함 또는 과열")
    else:
        lines.append(f"📊 차트: {chart:.0f}점 — 보통")

    return lines
