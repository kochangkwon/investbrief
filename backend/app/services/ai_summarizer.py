"""Claude API 뉴스 요약 + 업종 분류 + 전문가 브리프"""
from __future__ import annotations

import logging
from typing import Any

import anthropic

from app.config import settings
from app.services import ai_prompts

logger = logging.getLogger(__name__)

_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


async def summarize_news(news_items: list[dict[str, Any]]) -> str:
    """뉴스 → AI 요약 (업종별 분류 포함)"""
    if not news_items:
        return "수집된 뉴스가 없습니다."

    if not settings.anthropic_api_key:
        logger.warning("Anthropic API 키 미설정")
        return "AI 요약 불가 (API 키 미설정)"

    lines = []
    for n in news_items[:15]:
        line = f"- {n['title']} ({n.get('source', '')})"
        desc = n.get("description", "")
        if desc:
            line += f"\n  요약: {desc}"
        lines.append(line)
    titles = "\n".join(lines)

    prompt = (
        "아래는 오늘의 경제/증시 뉴스 제목입니다.\n\n"
        "세 가지를 작성해주세요:\n\n"
        "1. **핵심 이슈** (3~5개)\n"
        "각 이슈를 한 줄로, 투자에 미치는 영향을 간단히 덧붙여주세요.\n\n"
        "2. **업종별 동향** (해당되는 업종만)\n"
        "반도체, 자동차, 2차전지, 바이오, 금융, 건설, 에너지, IT/플랫폼 중 "
        "오늘 뉴스에서 언급된 업종만 한 줄씩 정리해주세요.\n\n"
        "3. **투자 시사점**\n"
        "오늘 뉴스 기반으로 투자자가 주목해야 할 포인트를 1~2줄로 간결하게 작성해주세요.\n\n"
        "불필요한 서론 없이 바로 본론만 작성하세요.\n\n"
        f"뉴스 제목:\n{titles}"
    )

    try:
        client = _get_client()
        response = await client.messages.create(
            model=settings.ai_model,
            max_tokens=settings.ai_max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        summary = response.content[0].text
        logger.info("AI 뉴스 요약 완료 (%d tokens)", response.usage.output_tokens)
        return summary
    except anthropic.RateLimitError:
        logger.warning("AI API rate limit — 재시도 없이 건너뜀")
        return "AI 요약 일시 불가 (API 호출 한도 초과)"
    except anthropic.APIConnectionError:
        logger.warning("AI API 연결 실패")
        return "AI 요약 일시 불가 (API 연결 오류)"
    except Exception:
        logger.exception("AI 요약 실패")
        return "AI 요약 생성 중 오류가 발생했습니다."


async def analyze_price_drop(
    stock_name: str,
    stock_code: str,
    change_pct: float,
    current_price: float,
    news_items: list[dict[str, Any]],
    disclosure_items: list[dict[str, Any]],
) -> str:
    """관심종목 급락 시 뉴스/공시 기반 원인 추정 + 종합 요약.

    뉴스/공시가 없거나 API 미설정이어도 fail-soft로 짧은 안내 문구를 반환한다.
    출력은 텔레그램 HTML 모드에서 그대로 노출되므로 마크다운 볼드(**)는 쓰지 않는다.
    """
    if not settings.anthropic_api_key:
        logger.warning("Anthropic API 키 미설정 — 급락 분석 스킵")
        return "AI 분석 불가 (API 키 미설정) — 뉴스/공시를 직접 확인하세요."

    news_lines = "\n".join(f"- {n['title']}" for n in news_items[:5]) or "- (관련 뉴스 없음)"
    disc_lines = (
        "\n".join(f"- {d.get('importance', '')} {d['title']}" for d in disclosure_items[:5])
        or "- (당일 공시 없음)"
    )

    prompt = (
        f"'{stock_name}'({stock_code}) 종목이 전일 대비 {change_pct:.1f}% 급락했습니다 "
        f"(현재가 {int(current_price):,}원).\n"
        "아래 뉴스/공시를 근거로 급락 원인을 분석해 투자자에게 보고하세요.\n\n"
        f"[관련 뉴스]\n{news_lines}\n\n"
        f"[당일 공시]\n{disc_lines}\n\n"
        "다음 3가지를 한국어로 간결하게 작성하세요:\n"
        "1. 추정 원인 — 뉴스/공시에서 드러난 하락 요인. 근거가 약하면 단정하지 말고 "
        "'가능성'으로 서술하고, 정보가 없으면 시장 전반/수급 요인일 수 있음을 언급.\n"
        "2. 핵심 이슈 — 투자자가 알아야 할 사실 1~3줄.\n"
        "3. 체크포인트 — 지금 확인하거나 주의할 점 1~2줄.\n\n"
        "마크다운 볼드(**)는 쓰지 말고, 항목은 이모지나 줄바꿈으로 구분하세요. "
        "서론 없이 본론만 작성하세요."
    )

    try:
        client = _get_client()
        response = await client.messages.create(
            model=settings.ai_model,
            max_tokens=900,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text
        logger.info(
            "급락 분석 완료: %s (%.1f%%, out=%d tokens)",
            stock_name, change_pct, response.usage.output_tokens,
        )
        return text
    except anthropic.RateLimitError:
        logger.warning("급락 분석 — API 호출 한도 초과")
        return "AI 분석 일시 불가 (API 호출 한도 초과) — 뉴스/공시를 직접 확인하세요."
    except anthropic.APIConnectionError:
        logger.warning("급락 분석 — API 연결 실패")
        return "AI 분석 일시 불가 (API 연결 오류) — 뉴스/공시를 직접 확인하세요."
    except Exception:
        logger.exception("급락 분석 실패: %s", stock_name)
        return "AI 분석 생성 중 오류가 발생했습니다 — 뉴스/공시를 직접 확인하세요."


async def generate_expert_brief(
    global_market: dict[str, Any],
    domestic_market: dict[str, Any],
    investor_flow: dict[str, Any],
    news_items: list[dict[str, Any]],
    disclosure_items: list[dict[str, Any]],
    market_risk: dict[str, Any] | None = None,
) -> str:
    """전문가용 5섹션 브리프 생성. fail-soft 폴백."""
    if not settings.anthropic_api_key:
        logger.warning("Anthropic API 키 미설정 — 구버전 요약으로 폴백")
        return await summarize_news(news_items)

    system_prompt, user_prompt = ai_prompts.build_expert_brief_prompt(
        global_market=global_market,
        domestic_market=domestic_market,
        investor_flow=investor_flow,
        news_items=news_items,
        disclosure_items=disclosure_items,
        market_risk=market_risk,
    )

    try:
        client = _get_client()
        response = await client.messages.create(
            model=settings.ai_model,
            max_tokens=2500,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = response.content[0].text
        logger.info(
            "전문가 브리프 생성 완료 (in=%d, out=%d)",
            response.usage.input_tokens, response.usage.output_tokens,
        )
        return text
    except anthropic.RateLimitError:
        logger.warning("AI Rate limit — 구버전 요약으로 폴백")
        return await summarize_news(news_items)
    except anthropic.APIConnectionError:
        logger.warning("AI API 연결 실패 — 구버전 요약으로 폴백")
        return await summarize_news(news_items)
    except Exception:
        logger.exception("전문가 브리프 생성 실패 — 구버전 요약으로 폴백")
        return await summarize_news(news_items)
