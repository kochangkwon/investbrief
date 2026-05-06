"""모닝브리프 텔레그램 출력 포맷.

원칙:
- 변동 작은 항목(절대값 < threshold)은 표시 생략 또는 간소화
- 빅네임은 변동 큰 순으로 정렬, ⚠️ 강조 적용
- VIX 같은 절대값 지표는 현재값 + 변동 함께 표시
"""
from __future__ import annotations

from typing import Any, Optional

# 변동 표시 임계값 (작은 변동은 생략)
ETF_DISPLAY_THRESHOLD = 0.3      # ETF는 ±0.3% 이상만 표시
MACRO_NOISE_THRESHOLD = 0.1      # 매크로는 ±0.1% 이상만 표시


def _emoji_for_change(change_pct: Optional[float], threshold: float = 0.5) -> str:
    """변동률에 따른 이모지."""
    if change_pct is None:
        return "⚪"
    if change_pct >= threshold:
        return "🟢"
    if change_pct <= -threshold:
        return "🔴"
    return "⚪"


def _format_pct(change_pct: Optional[float]) -> str:
    """+5.23% 형태."""
    if change_pct is None:
        return "N/A"
    sign = "+" if change_pct >= 0 else ""
    return f"{sign}{change_pct:.2f}%"


def format_big_names_section(big_names: list[dict[str, Any]]) -> str:
    """빅네임 섹션."""
    if not big_names:
        return ""
    lines = ["📊 <b>빅네임 (변동 큰 순)</b>"]

    for item in big_names:
        change = item["regular_change_pct"]
        prepost = item.get("prepost_change_pct")
        emoji = _emoji_for_change(change, threshold=1.0)
        change_str = _format_pct(change)

        prepost_str = ""
        if prepost is not None and abs(prepost) >= 0.5:
            prepost_str = f" (시간외 {_format_pct(prepost)})"

        alert_mark = " ⚠️" if item.get("is_alert") else ""

        lines.append(f"{emoji} {item['ticker']} {change_str}{prepost_str}{alert_mark}")

        # 변동이 클 때만 한국 종목 + 관계 표시
        if abs(change) >= 2.0 or (prepost is not None and abs(prepost) >= 2.0):
            stocks = ", ".join(item["kr_stocks"][:3])
            direction = "주목" if change >= 0 else "갭하락 주의"
            lines.append(f"   국내 {direction}: {stocks}")
            relation = item.get("relation")
            if relation:
                lines.append(f"   ({relation})")

    return "\n".join(lines)


def format_etf_section(etfs: list[dict[str, Any]]) -> str:
    """ETF 섹션."""
    if not etfs:
        return ""

    filtered = [e for e in etfs if abs(e["regular_change_pct"]) >= ETF_DISPLAY_THRESHOLD]
    if not filtered:
        return "📈 <b>섹터 ETF</b>: 큰 변동 없음"

    lines = ["📈 <b>섹터 ETF</b>"]
    for item in filtered:
        change = item["regular_change_pct"]
        emoji = _emoji_for_change(change, threshold=0.5)
        change_str = _format_pct(change)

        if change >= 1.0:
            sentiment = f"{item['category']} 강세"
        elif change <= -1.0:
            sentiment = f"{item['category']} 약세"
        else:
            sentiment = f"{item['category']} 중립"

        lines.append(f"{emoji} {item['ticker']} {change_str} → {sentiment}")

    return "\n".join(lines)


def format_macro_section(macros: list[dict[str, Any]]) -> str:
    """매크로 섹션."""
    if not macros:
        return ""
    lines = ["🌡️ <b>매크로</b>"]

    for item in macros:
        change = item["regular_change_pct"]
        if change is None:
            continue

        value = item["regular_close"]
        value_str = item["format"].format(value=value)
        change_str = _format_pct(change)

        cat_emoji = {
            "환율": "💵",
            "금리": "📈",
            "위험도": "😨" if value > 20 else "😌",
            "원자재": "🛢️",
        }.get(item["category"], "📊")

        line = f"{cat_emoji} {item['name']}: {value_str} ({change_str})"

        if item.get("warning_levels"):
            for threshold, msg in sorted(item["warning_levels"].items(), reverse=True):
                if value >= threshold:
                    line += f" — {msg}"
                    break

        lines.append(line)

    return "\n".join(lines)


def format_sp500_futures_section(fut: Optional[dict[str, Any]]) -> str:
    """S&P500 선물 (한국 갭 예측)."""
    if not fut:
        return ""

    change = fut.get("prepost_change_pct") or fut.get("regular_change_pct")
    if change is None:
        return ""

    change_str = _format_pct(change)

    if change >= 0.3:
        signal = "한국 갭상승 가능성"
    elif change <= -0.3:
        signal = "한국 갭하락 가능성"
    else:
        signal = "한국 보합 출발 예상"

    return f"📊 <b>S&amp;P500 선물</b>: {change_str} → {signal}"


def format_full_section(data: dict[str, Any]) -> str:
    """전체 미국 시장 섹션 통합 포맷.

    모든 sub-section이 비어있으면 빈 문자열 반환 (헤더만 단독 노출 방지).
    """
    big_names_text = format_big_names_section(data.get("big_names", []))
    etf_text = format_etf_section(data.get("etf", []))
    macro_text = format_macro_section(data.get("macro", []))
    fut_text = format_sp500_futures_section(data.get("sp500_futures"))

    if not (big_names_text or etf_text or macro_text or fut_text):
        return ""

    sections: list[str] = ["🌎 <b>어제 미국 시장</b> (07:40 KST 기준)", ""]

    if big_names_text:
        sections.append(big_names_text)
        sections.append("")
    if etf_text:
        sections.append(etf_text)
        sections.append("")
    if macro_text:
        sections.append(macro_text)
        sections.append("")
    if fut_text:
        sections.append(fut_text)

    return "\n".join(sections).strip()
