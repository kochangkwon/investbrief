"""AI 프롬프트 정의 — 전문가용 브리프 출력 구조 통일."""
from __future__ import annotations

from typing import Any


EXPERT_BRIEF_SYSTEM = """당신은 한국 주식 시장 분석 전문가이며, 매일 아침 기관 투자자에게 모닝브리프를 작성합니다.
독자는 이미 시장의 기본 흐름을 알고 있는 프로페셔널입니다. 일반 뉴스 요약이 아니라,
의사결정에 직접 쓸 수 있는 인사이트만 제공하세요. 어휘는 간결·정확·실무적으로.

특별 지시: "시장 위험 모드"가 제공되면 섹션 1(시장 컨텍스트) 첫 줄에서 모드를 명시하고,
섹션 5(리스크 시그널)에서 위험 요인을 활용하세요."""


EXPERT_BRIEF_USER_TEMPLATE = """다음은 오늘의 시장 데이터와 뉴스입니다.

━━━━━━━━━━━━━━━━━━━━━━━━━
🚦 시장 위험 모드
{market_risk_text}

━━━━━━━━━━━━━━━━━━━━━━━━━
🌍 글로벌 시장 (전일)
{global_market_text}

📊 국내 시장 (전일)
{domestic_market_text}

💰 수급 (전일 종가 기준)
{flow_text}

📰 주요 뉴스 ({news_count}건)
{news_text}

📋 주요 공시 ({disclosure_count}건)
{disclosure_text}
━━━━━━━━━━━━━━━━━━━━━━━━━

다음 **5개 섹션**으로 정확히 작성하세요. 각 섹션 헤더는 그대로 사용.

## 🎯 1. 시장 컨텍스트
- 전일 시장을 한 줄로 요약 (지수 + 외인 수급 + 주도 섹터)
- 오늘 시장 기대 한 줄
- **반드시** 외인/기관 net flow 수치 언급

## 💥 2. 오늘의 카탈리스트 (3~5개)
각 항목 형식 (단 한 줄):
- **[종목명/섹터]** — 사건/뉴스 (수치 명시) → 예상 영향
예시: "한미반도체 — 2분기 매출 가이던스 +30% 상회 → HBM 후공정 비중 확대 모멘텀 강화"
**규칙:**
- 수주 공시 → 매출 대비 비중 추정
- 임상 → 단계와 발표 일정 명시
- 실적 → 컨센서스 대비 +/-
- 추측 금지, 데이터에 명시된 것만

## 🔄 3. 섹터 로테이션 시그널
- 강한 섹터 (3개 이내) + 약한 섹터 (2개 이내)
- 미국 섹터 ETF 동향과 한국 매칭 (예: SOXX +3% → 반도체 동조 예상)
- 외인/기관 매수 상위 섹터 명시

## 📅 4. 이번주 주요 일정
입력 데이터에 명시된 일정 위주, 최대 5개:
- **MM/DD** — 이벤트명 [영향 섹터/종목]
없으면 "특이 일정 없음"

## ⚠️ 5. 리스크 시그널
다음 항목 중 **현재 발현된 것만** (없으면 "특이 시그널 없음"):
- VIX > 20 또는 5일 변동
- 미국 10년물 4.5% 이상 또는 급변
- 환율 1380원 이상 또는 5일 +1% 이상
- 외인 5일 연속 순매도
- 미국 시장과 한국 디커플링 (전일 나스닥 +1% 인데 코스피 약세 등)

━━━━━━━━━━━━━━━━━━━━━━━━━
**원칙**:
- 추측·일반론 금지. 데이터·뉴스에 근거한 것만.
- 종목명 언급 시 종목코드 함께 (예: "한미반도체(042700)")
- 한 섹션이 비어있어도 헤더는 유지, 본문에 "특이 사항 없음" 표기."""


def build_expert_brief_prompt(
    global_market: dict[str, Any],
    domestic_market: dict[str, Any],
    investor_flow: dict[str, Any],
    news_items: list[dict[str, Any]],
    disclosure_items: list[dict[str, Any]],
    market_risk: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """(system_prompt, user_prompt) 튜플 반환."""
    global_text = _format_market_for_prompt(global_market) or "데이터 없음"
    domestic_text = _format_market_for_prompt(domestic_market) or "데이터 없음"
    flow_text = _format_flow_for_prompt(investor_flow) or "수급 데이터 없음"
    news_text = _format_news_for_prompt(news_items) or "뉴스 없음"
    disc_text = _format_disclosure_for_prompt(disclosure_items) or "주요 공시 없음"
    risk_text = _format_market_risk_for_prompt(market_risk)

    user_prompt = EXPERT_BRIEF_USER_TEMPLATE.format(
        market_risk_text=risk_text,
        global_market_text=global_text,
        domestic_market_text=domestic_text,
        flow_text=flow_text,
        news_count=len(news_items),
        news_text=news_text,
        disclosure_count=len(disclosure_items),
        disclosure_text=disc_text,
    )
    return EXPERT_BRIEF_SYSTEM, user_prompt


def _format_market_risk_for_prompt(market_risk: dict[str, Any] | None) -> str:
    if not market_risk:
        return "정상 모드 (특이 시그널 없음)"
    level = market_risk.get("level", "정상")
    factors = market_risk.get("factors", [])
    if factors and level != "정상":
        return f"{level} — {'; '.join(factors[:3])}"
    return f"{level} 모드"


def _format_market_for_prompt(data: dict[str, Any]) -> str:
    if not data:
        return ""
    lines = []
    for v in data.values():
        if not isinstance(v, dict):
            continue
        sign = "+" if v.get("change_pct", 0) > 0 else ""
        lines.append(
            f"- {v.get('label', '?')}: {v.get('close', 0):,.2f} ({sign}{v.get('change_pct', 0):.2f}%)"
        )
    return "\n".join(lines)


def _format_flow_for_prompt(flow: dict[str, Any]) -> str:
    if not flow:
        return ""
    parts = []
    foreign = flow.get("foreign_net_billion")
    inst = flow.get("institution_net_billion")
    if foreign is not None:
        sign = "+" if foreign >= 0 else ""
        parts.append(f"외국인 순매수: {sign}{foreign:,.0f}억원")
    if inst is not None:
        sign = "+" if inst >= 0 else ""
        parts.append(f"기관 순매수: {sign}{inst:,.0f}억원")

    buy_sectors = flow.get("top_buy_sectors", [])
    sell_sectors = flow.get("top_sell_sectors", [])
    if buy_sectors:
        parts.append(f"외인 매수 상위 섹터: {', '.join(buy_sectors[:3])}")
    if sell_sectors:
        parts.append(f"외인 매도 상위 섹터: {', '.join(sell_sectors[:3])}")

    return "\n".join(f"- {p}" for p in parts)


def _format_news_for_prompt(news: list[dict[str, Any]]) -> str:
    if not news:
        return ""
    lines = []
    for n in news[:20]:
        title = n.get("title", "")
        desc = n.get("description", "")
        if desc:
            lines.append(f"- {title}\n  ({desc[:150]})")
        else:
            lines.append(f"- {title}")
    return "\n".join(lines)


def _format_disclosure_for_prompt(disc: list[dict[str, Any]]) -> str:
    if not disc:
        return ""
    important = [d for d in disc if d.get("importance") in ("🔴", "🟡", "🟢")]
    if not important:
        return ""
    lines = []
    for d in important[:15]:
        lines.append(
            f"- {d.get('importance', '')} [{d.get('corp_name', '?')}] {d.get('title', '?')}"
        )
    return "\n".join(lines)
