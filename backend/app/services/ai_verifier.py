"""Claude AI 검증 게이트 — YES/NO 판정 헬퍼.

theme_radar_service / theme_discovery_service가 공통으로 사용한다.
프롬프트는 호출 측이 만들고, 이 모듈은 API 호출 + 파싱 + 에러 처리만 담당.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

import anthropic

from app.config import settings

logger = logging.getLogger(__name__)

DEFAULT_MAX_TOKENS = 150
DEFAULT_TIMEOUT_SEC = 15.0

_VERDICT_RE = re.compile(r"VERDICT:\s*(YES|NO)", re.IGNORECASE)
_REASON_RE = re.compile(r"REASON:\s*(.+?)(?:\n|$)", re.IGNORECASE | re.DOTALL)

# 모듈 레벨 client 캐시 — 스캔 1회당 N개 종목 검증 시 connection pool 재사용.
# timeout은 호출별 with_options()로 적용하므로 client 본체에는 미지정.
_client: Optional[anthropic.AsyncAnthropic] = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


async def verify_with_claude(
    prompt: str,
    *,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: float = DEFAULT_TIMEOUT_SEC,
    log_context: str = "",
) -> tuple[Optional[bool], str]:
    """Claude에 VERDICT(YES/NO)+REASON 형식 응답을 요청하고 파싱.

    프롬프트는 다음 형식 응답을 유도해야 한다:
        VERDICT: YES|NO
        REASON: (1줄 근거)

    Returns:
        (verdict, reason)
        - verdict: True(YES) / False(NO) / None(API key 없음·예외·파싱 실패)
        - reason: 판정 근거 또는 실패 사유 ("no api key", "rate limit", "timeout", "parse error", ...)

    호출 측에서 fail-closed(False)/pass-through(None) 정책을 선택해 변환한다.
    """
    if not settings.anthropic_api_key:
        return None, "no api key"

    try:
        client = _get_client().with_options(timeout=timeout)
        response = await client.messages.create(
            model=settings.ai_model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text if response.content else ""
    except anthropic.RateLimitError:
        logger.warning("AI 검증 rate limit %s", log_context)
        return None, "rate limit"
    except anthropic.APITimeoutError:
        logger.warning("AI 검증 timeout %s", log_context)
        return None, "timeout"
    except Exception as e:
        logger.exception("AI 검증 API 예외 %s", log_context)
        return None, f"api error: {type(e).__name__}"

    verdict_match = _VERDICT_RE.search(raw)
    if not verdict_match:
        logger.warning("AI 검증 파싱 실패 %s raw=%r", log_context, raw[:200])
        return None, "parse error"

    verdict = verdict_match.group(1).upper() == "YES"
    reason_match = _REASON_RE.search(raw)
    reason = reason_match.group(1).strip() if reason_match else "(근거 미파싱)"
    return verdict, reason
