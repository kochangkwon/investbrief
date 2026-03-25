"""텔레그램 봇 — 브리프 발송 + 명령어 처리"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}"


async def _send_message(text: str, parse_mode: str = "HTML") -> bool:
    """텔레그램 메시지 발송"""
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        logger.warning("텔레그램 설정 미완료")
        return False

    url = f"{TELEGRAM_API.format(token=settings.telegram_bot_token)}/sendMessage"
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
        logger.info("텔레그램 발송 성공")
        return True
    except Exception:
        logger.exception("텔레그램 발송 실패")
        return False


def _format_market(data: dict[str, Any], title: str) -> str:
    """시장 데이터를 텔레그램 포맷으로"""
    if not data:
        return ""
    lines = [f"<b>{title}</b>"]
    for v in data.values():
        sign = "+" if v["change_pct"] > 0 else ""
        emoji = "🔴" if v["change_pct"] > 0 else "🔵" if v["change_pct"] < 0 else "⚪"
        lines.append(f"  {emoji} {v['label']}: {v['close']:,.2f} ({sign}{v['change_pct']:.2f}%)")
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
    parts.append("<b>📰 AI 뉴스 요약</b>")
    parts.append(brief.news_summary)
    parts.append("")

    # DART 공시 (중요한 것만)
    disclosures = brief.disclosures or []
    important = [d for d in disclosures if d.get("importance") in ("🔴", "🟡", "🟢")]
    if important:
        parts.append(f"<b>📋 주요 공시</b> ({len(important)}건)")
        for d in important[:10]:
            parts.append(f"  {d['importance']} {d['corp_name']}: {d['title']}")
        parts.append("")

    # 관심종목
    watchlist = brief.watchlist_check or []
    if watchlist:
        parts.append("<b>🔍 관심종목 체크</b>")
        for w in watchlist:
            parts.append(f"  • {w.get('stock_name', '')}: {w.get('summary', '')}")

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
