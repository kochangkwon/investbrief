"""텔레그램 봇 — 브리프 발송 + 명령어 처리"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

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


def _format_risk_header(market_risk: dict[str, Any]) -> str:
    """P0-5 위험 모드 헤더 (1줄)."""
    if not market_risk:
        return ""
    level = market_risk.get("level", "정상")
    factors = market_risk.get("factors", [])

    emoji_map = {"정상": "🟢", "주의": "🟠", "위험": "🔴"}
    emoji = emoji_map.get(level, "⚪")

    if level == "정상":
        return f"{emoji} <b>시장 위험 모드: 정상</b>"

    factor_str = "; ".join(factors[:2])
    return (
        f"{emoji} <b>시장 위험 모드: {level}</b>\n"
        f"<i>{escape_html(factor_str)}</i>"
    )


def _format_flow_section(flow: dict[str, Any]) -> str:
    """수급 데이터 텔레그램 포맷."""
    if not flow:
        return ""

    lines = ["<b>💰 수급 (전일)</b>"]

    foreign = flow.get("foreign_net_billion")
    inst = flow.get("institution_net_billion")
    retail = flow.get("retail_net_billion")

    def _fmt(label: str, val: Optional[float]) -> str:
        if val is None:
            return f"  {label}: 데이터 없음"
        emoji = "🟢" if val > 0 else "🔴" if val < 0 else "⚪"
        sign = "+" if val > 0 else ""
        return f"  {emoji} {label}: {sign}{val:,.0f}억"

    lines.append(_fmt("외국인", foreign))
    lines.append(_fmt("기관", inst))
    if retail is not None:
        lines.append(_fmt("개인", retail))

    buy_sectors = flow.get("top_buy_sectors", [])
    sell_sectors = flow.get("top_sell_sectors", [])
    if buy_sectors:
        lines.append(f"  외인 매수 우위: {', '.join(buy_sectors[:3])}")
    if sell_sectors:
        lines.append(f"  외인 매도 우위: {', '.join(sell_sectors[:3])}")

    # 외인 매수 TOP 5
    top_traders = flow.get("top_foreign_traders", [])
    buys = [t for t in top_traders if t["net_billion"] > 0][:5]
    if buys:
        lines.append("")
        lines.append("  <b>외인 매수 TOP 5</b>")
        for b in buys:
            net = b["net_billion"]
            lines.append(
                f"    • {escape_html(b['stock_name'])} ({b['stock_code']}) "
                f"+{net:,.0f}억"
            )

    # 외인 매도 TOP 3
    sells = [t for t in top_traders if t["net_billion"] < 0][:3]
    if sells:
        lines.append("")
        lines.append("  <b>외인 매도 TOP 3</b>")
        for s in sells:
            net = s["net_billion"]
            lines.append(
                f"    • {escape_html(s['stock_name'])} ({s['stock_code']}) "
                f"{net:,.0f}억"
            )

    return "\n".join(lines)


def format_brief(brief: Any) -> str:
    """DailyBrief → 텔레그램 메시지."""
    parts = []

    # 헤더
    parts.append(f"☀️ <b>투자 모닝브리프</b> ({brief.date})")
    parts.append("")

    # 시장 위험 모드 (P0-5)
    risk = getattr(brief, "market_risk", None) or {}
    risk_section = _format_risk_header(risk)
    if risk_section:
        parts.append(risk_section)
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

    # 수급 (P0-2)
    flow = getattr(brief, "investor_flow", None) or {}
    flow_section = _format_flow_section(flow)
    if flow_section:
        parts.append(flow_section)
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


async def send_us_market_brief() -> bool:
    """미국 시장 동향 별도 발송 (모닝브리프와 분리).

    빈 데이터(yfinance 실패 등) 시 발송 스킵 — 빈 메시지 발송 방지.
    """
    from app.services.us_market import get_us_market_section
    section = await get_us_market_section()
    if not section:
        logger.info("미국 시장 섹션 비어있음 — 발송 스킵")
        return False
    return await _send_message(section)


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
