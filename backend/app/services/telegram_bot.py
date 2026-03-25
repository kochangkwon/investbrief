"""텔레그램 봇 명령어 처리 (polling 방식)"""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any

import httpx

from app.config import settings
from app.database import async_session
from app.services import brief_service, daily_report_service, watchlist_service, telegram_service
from app.collectors import news_collector, dart_collector

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}"

HELP_TEXT = """<b>📋 InvestBrief 명령어</b>

/today — 오늘 브리프 다시 보기
/watch 종목명 — 관심종목 추가
/unwatch 종목코드 — 관심종목 제거
/list — 관심종목 목록
/news 키워드 — 종목/키워드 뉴스 검색
/dart 종목명 — 종목 공시 검색
/report — 관심종목 일일 리포트
/help — 도움말"""


async def _get_updates(offset: int) -> list[dict[str, Any]]:
    """Telegram getUpdates"""
    url = f"{TELEGRAM_API.format(token=settings.telegram_bot_token)}/getUpdates"
    params = {"offset": offset, "timeout": 30, "allowed_updates": ["message"]}
    try:
        async with httpx.AsyncClient(timeout=35) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
        data = resp.json()
        return data.get("result", [])
    except Exception:
        logger.exception("getUpdates 실패")
        return []


async def _handle_today() -> str:
    """오늘 브리프 조회"""
    async with async_session() as session:
        brief = await brief_service.get_brief_by_date(session, date.today())
    if not brief:
        return "오늘의 브리프가 아직 생성되지 않았습니다.\n07:00에 자동 생성됩니다."
    return telegram_service.format_brief(brief)


async def _handle_watch(args: str) -> str:
    """관심종목 추가"""
    if not args.strip():
        return "사용법: /watch 종목명 종목코드\n예) /watch 삼성전자 005930"

    parts = args.strip().split()
    if len(parts) == 1:
        # 종목명만 입력 — 코드를 종목명으로 대체 (수동 입력 유도)
        return f"종목코드도 함께 입력해주세요.\n예) /watch {parts[0]} 005930"

    stock_name = parts[0]
    stock_code = parts[1]

    if not stock_code.isdigit() or len(stock_code) != 6:
        return f"종목코드는 6자리 숫자입니다.\n예) /watch {stock_name} 005930"

    try:
        async with async_session() as session:
            await watchlist_service.add(session, stock_code, stock_name)
        return f"✅ 관심종목 추가: {stock_name} ({stock_code})"
    except Exception:
        return f"⚠️ 이미 등록된 종목이거나 추가에 실패했습니다."


async def _handle_unwatch(args: str) -> str:
    """관심종목 제거"""
    stock_code = args.strip()
    if not stock_code:
        return "사용법: /unwatch 종목코드\n예) /unwatch 005930"

    async with async_session() as session:
        deleted = await watchlist_service.remove(session, stock_code)
    if deleted:
        return f"✅ 관심종목 제거: {stock_code}"
    return f"⚠️ 등록되지 않은 종목: {stock_code}"


async def _handle_list() -> str:
    """관심종목 목록"""
    async with async_session() as session:
        items = await watchlist_service.list_all(session)
    if not items:
        return "등록된 관심종목이 없습니다.\n/watch 종목명 종목코드 로 추가하세요."

    lines = ["<b>🔍 관심종목 목록</b>", ""]
    for w in items:
        memo = f" — {w.memo}" if w.memo else ""
        lines.append(f"  • {w.stock_name} ({w.stock_code}){memo}")
    return "\n".join(lines)


async def _handle_news(args: str) -> str:
    """종목/키워드 뉴스 검색"""
    keyword = args.strip()
    if not keyword:
        return "사용법: /news 키워드\n예) /news 삼성전자"

    items = await news_collector._fetch_naver_news(keyword)
    if not items:
        return f"'{keyword}' 관련 뉴스가 없습니다."

    lines = [f"<b>📰 '{keyword}' 뉴스</b>", ""]
    for n in items[:10]:
        lines.append(f"• {n['title']}")
    return "\n".join(lines)


async def _handle_dart(args: str) -> str:
    """종목 공시 검색"""
    keyword = args.strip()
    if not keyword:
        return "사용법: /dart 종목명\n예) /dart 삼성전자"

    disclosures = await dart_collector.get_today_disclosures()
    matched = [d for d in disclosures if keyword in d.get("corp_name", "")]

    if not matched:
        return f"오늘 '{keyword}' 관련 공시가 없습니다."

    lines = [f"<b>📋 '{keyword}' 공시</b> ({len(matched)}건)", ""]
    for d in matched[:15]:
        lines.append(f"  {d['importance']} {d['corp_name']}: {d['title']}")
    return "\n".join(lines)


async def _handle_report(_: str) -> str:
    """관심종목 일일 리포트"""
    msg = await daily_report_service.generate_daily_report()
    if not msg:
        return "관심종목이 없습니다.\n/watch 종목명 종목코드 로 추가하세요."
    return msg


async def _handle_help(_: str) -> str:
    return HELP_TEXT


COMMAND_HANDLERS = {
    "/today": lambda args: _handle_today(),
    "/watch": _handle_watch,
    "/unwatch": _handle_unwatch,
    "/list": lambda args: _handle_list(),
    "/news": _handle_news,
    "/dart": _handle_dart,
    "/report": _handle_report,
    "/help": _handle_help,
    "/start": _handle_help,
}


async def _process_message(message: dict[str, Any]) -> None:
    """메시지 처리"""
    chat_id = str(message.get("chat", {}).get("id", ""))
    text = message.get("text", "").strip()

    if not text or not text.startswith("/"):
        return

    # 본인 chat_id만 허용
    if chat_id != settings.telegram_chat_id:
        logger.warning("허용되지 않은 chat_id: %s", chat_id)
        return

    # 명령어 파싱
    parts = text.split(maxsplit=1)
    cmd = parts[0].split("@")[0].lower()  # /today@BotName 형태 대응
    args = parts[1] if len(parts) > 1 else ""

    handler = COMMAND_HANDLERS.get(cmd)
    if not handler:
        return

    try:
        response = await handler(args)
        if response:
            await telegram_service.send_text(response)
    except Exception:
        logger.exception("명령어 처리 실패: %s", cmd)
        await telegram_service.send_text("⚠️ 명령어 처리 중 오류가 발생했습니다.")


async def start_polling() -> None:
    """텔레그램 봇 polling 루프"""
    if not settings.telegram_bot_token:
        logger.warning("텔레그램 봇 토큰 미설정, polling 비활성화")
        return

    logger.info("텔레그램 봇 polling 시작")
    offset = 0

    while True:
        try:
            updates = await _get_updates(offset)
            for update in updates:
                offset = update["update_id"] + 1
                message = update.get("message")
                if message:
                    await _process_message(message)
        except asyncio.CancelledError:
            logger.info("텔레그램 봇 polling 종료")
            break
        except Exception:
            logger.exception("polling 루프 오류")
            await asyncio.sleep(5)
