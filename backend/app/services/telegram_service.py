"""텔레그램 봇 — 브리프 발송 + 명령어 처리"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}"

# 네트워크 일시 장애(ConnectTimeout 등)에 대비해 짧은 재시도 수행
_SEND_TIMEOUT_SECONDS = 30.0
_SEND_MAX_ATTEMPTS = 3
_SEND_BACKOFF_BASE_SECONDS = 2.0


async def _send_message(text: str, parse_mode: str = "HTML") -> bool:
    """텔레그램 메시지 발송 — 실패 시 지수 백오프로 재시도"""
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        logger.warning("텔레그램 설정 미완료")
        return False

    url = f"{TELEGRAM_API.format(token=settings.telegram_bot_token)}/sendMessage"
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }

    last_error: Exception | None = None
    for attempt in range(1, _SEND_MAX_ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient(timeout=_SEND_TIMEOUT_SECONDS) as client:
                resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                logger.info("텔레그램 발송 성공 (attempt=%d)", attempt)
                return True
            # 4xx는 재시도해도 실패 — 포맷/권한 문제일 가능성 → 바로 중단
            if 400 <= resp.status_code < 500:
                logger.error(
                    "텔레그램 발송 실패 (non-retryable) attempt=%d status=%d body=%s",
                    attempt, resp.status_code, resp.text[:500],
                )
                return False
            # 5xx — 재시도 대상
            logger.warning(
                "텔레그램 발송 일시 실패 attempt=%d status=%d body=%s",
                attempt, resp.status_code, resp.text[:300],
            )
            last_error = httpx.HTTPStatusError(
                f"status {resp.status_code}", request=resp.request, response=resp,
            )
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError) as e:
            last_error = e
            logger.warning("텔레그램 발송 네트워크 오류 attempt=%d: %s", attempt, type(e).__name__)
        except Exception as e:
            last_error = e
            logger.exception("텔레그램 발송 예기치 못한 오류 attempt=%d", attempt)

        if attempt < _SEND_MAX_ATTEMPTS:
            await asyncio.sleep(_SEND_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))

    logger.error("텔레그램 발송 최종 실패 (%d회 시도): %s", _SEND_MAX_ATTEMPTS, last_error)
    return False


def escape_html(text: str) -> str:
    """텔레그램 HTML 모드용 이스케이프 (& < > 만 처리, 인용부호는 유지).

    Telegram Bot API는 본문에서 `<`, `>`, `&`만 escape 요구하며 인용부호는 그대로 둬도 무방.
    `html.escape`는 quote까지 escape하므로 종목명/뉴스 제목에 사용 시 시각적으로 어색.
    """
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _format_market(data: dict[str, Any], title: str) -> str:
    """시장 데이터를 텔레그램 포맷으로"""
    if not data:
        return ""
    lines = [f"<b>{escape_html(title)}</b>"]
    for v in data.values():
        sign = "+" if v["change_pct"] > 0 else ""
        emoji = "🔴" if v["change_pct"] > 0 else "🔵" if v["change_pct"] < 0 else "⚪"
        lines.append(f"  {emoji} {escape_html(v['label'])}: {v['close']:,.2f} ({sign}{v['change_pct']:.2f}%)")
    return "\n".join(lines)


def format_brief(brief: Any) -> str:
    """DailyBrief → 텔레그램 메시지"""
    parts = []

    # 헤더
    parts.append(f"☀️ <b>투자 모닝브리프</b> ({brief.date})")
    parts.append("")

    # 글로벌 마켓
    gm = _format_market(brief.global_market, "🌍 글로벌 시장")
    if gm:
        parts.append(gm)
        parts.append("")

    # 국내 마켓
    dm = _format_market(brief.domestic_market, "📊 국내 시장")
    if dm:
        parts.append(dm)
        parts.append("")

    # AI 뉴스 요약
    parts.append("<b>📰 AI 뉴스 브리핑</b>")
    parts.append(escape_html(brief.news_summary))
    parts.append("")

    # DART 공시 (중요한 것만)
    disclosures = brief.disclosures or []
    important = [d for d in disclosures if d.get("importance") in ("🔴", "🟡", "🟢")]
    if important:
        parts.append(f"<b>📋 주요 공시</b> ({len(important)}건)")
        for d in important[:10]:
            parts.append(f"  {d['importance']} {escape_html(d['corp_name'])}: {escape_html(d['title'])}")
        parts.append("")

    # 관심종목
    watchlist = brief.watchlist_check or []
    if watchlist:
        parts.append("<b>🔍 관심종목 체크</b>")
        for w in watchlist:
            parts.append(f"  • {escape_html(w.get('stock_name', ''))}: {escape_html(w.get('summary', ''))}")

    return "\n".join(parts)


async def send_brief(brief: Any) -> bool:
    """브리프를 텔레그램으로 발송"""
    msg = format_brief(brief)

    # 텔레그램 메시지 4096자 제한
    if len(msg) > 4000:
        msg = msg[:4000] + "\n\n... (전체 내용은 웹에서 확인)"

    return await _send_message(msg)


async def send_text(text: str) -> bool:
    """단순 텍스트 발송"""
    return await _send_message(text, parse_mode="HTML")


async def send_long_text(text: str, max_length: int = 4000) -> None:
    """긴 메시지를 라인 경계로 분할해 순차 발송 (텔레그램 4096자 제한 대응)"""
    if len(text) <= max_length:
        await send_text(text)
        return

    lines = text.split("\n")
    current: list[str] = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1
        if current_len + line_len > max_length:
            if current:
                await send_text("\n".join(current))
            current = [line]
            current_len = line_len
        else:
            current.append(line)
            current_len += line_len

    if current:
        await send_text("\n".join(current))
