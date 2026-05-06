"""텔레그램 봇 명령어 처리 (polling 방식)"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date
from typing import Any

import httpx

from app.config import settings
from app.database import async_session
from app.services import brief_service, daily_report_service, theme_discovery_service, theme_radar_service, watchlist_service, telegram_service
from app.collectors import news_collector, dart_collector, stock_search

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

<b>🎯 테마 선행 스캐너</b>
/theme-add "테마명" 키워드1,키워드2 — 테마 추가
/theme-remove "테마명" — 테마 삭제
/theme-list — 테마 목록
/theme-scan — 즉시 스캔 (수동)

매주 월 08:00 자동 스캔 → 신규 수혜주 텔레그램 알림

<b>🔍 아카이브 테마 발굴</b>
/theme-discover [일수] — AI가 부상 테마 자동 발굴 (기본 30일)
/theme-trending — 언급 빈도 TOP 10 종목

매주 일요일 09:00 자동 발굴 리포트 전송

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
    # us_market 섹션 — fail-soft (실패 시 빈 문자열)
    from app.services.us_market import get_us_market_section
    us_section = await get_us_market_section()
    return telegram_service.format_brief(brief, us_market_section=us_section)


async def _handle_watch(args: str) -> str:
    """관심종목 추가"""
    if not args.strip():
        return "사용법: /watch 종목명\n예) /watch 삼성전자"

    parts = args.strip().split()
    stock_name = parts[0]
    stock_code = parts[1] if len(parts) > 1 else None

    # 종목코드 미입력 시 자동 검색
    if not stock_code:
        results = await stock_search.search_stocks(stock_name, limit=1)
        if not results:
            return f"⚠️ '{stock_name}' 종목을 찾을 수 없습니다.\n종목코드를 직접 입력해주세요.\n예) /watch {stock_name} 005930"
        stock_code = results[0]["stock_code"]
        stock_name = results[0]["stock_name"]

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


async def _handle_theme_add(args: str) -> str:
    """
    /theme-add "테마명" 키워드1,키워드2,키워드3
    예: /theme-add "AI 데이터센터 전력" 북미인증,초고압케이블,345kV
    """
    if not args.strip():
        return (
            "사용법:\n"
            '/theme-add "테마명" 키워드1,키워드2,키워드3\n\n'
            "예시:\n"
            '/theme-add "AI 데이터센터 전력" 북미인증,초고압케이블,345kV,KEMA'
        )

    match = re.match(r'^"([^"]+)"\s+(.+)$', args.strip())
    if not match:
        return '테마명은 큰따옴표로 감싸주세요: /theme-add "테마명" 키워드1,키워드2'

    theme_name = match.group(1)
    keywords = match.group(2).strip()

    if not keywords:
        return "키워드를 최소 1개 이상 입력해주세요."

    async with async_session() as session:
        success, message = await theme_radar_service.add_theme(session, theme_name, keywords)
    return ("✅ " if success else "❌ ") + message


async def _handle_theme_remove(args: str) -> str:
    """/theme-remove "테마명" """
    if not args.strip():
        return '사용법: /theme-remove "테마명"'

    match = re.match(r'^"([^"]+)"$', args.strip())
    if not match:
        return '테마명은 큰따옴표로 감싸주세요: /theme-remove "테마명"'

    theme_name = match.group(1)
    async with async_session() as session:
        success, message = await theme_radar_service.remove_theme(session, theme_name)
    return ("✅ " if success else "❌ ") + message


async def _handle_theme_list() -> str:
    """/theme-list — 등록된 테마 목록"""
    async with async_session() as session:
        themes = await theme_radar_service.list_themes(session)

    if not themes:
        return "등록된 테마가 없습니다.\n/theme-add 로 테마를 추가해보세요."

    lines = [f"🎯 <b>등록된 테마 ({len(themes)}개)</b>", ""]
    for i, t in enumerate(themes, 1):
        status = "🟢" if t["enabled"] else "🔴"
        lines.append(
            f"{i}. {status} <b>{t['name']}</b>\n"
            f"   키워드: {t['keywords']}\n"
            f"   감지 종목: {t['detected_count']}개"
        )

    return "\n".join(lines)


async def _handle_theme_scan() -> str:
    """/theme-scan — 수동 즉시 스캔"""
    await telegram_service.send_text("🔍 테마 스캔 시작... (시간이 걸릴 수 있습니다)")

    results = await theme_radar_service.scan_all_themes()
    total_new = sum(results.values())

    if total_new == 0:
        return "✅ 스캔 완료 — 새로운 수혜주 후보 없음"

    lines = [f"✅ 스캔 완료 — 총 {total_new}종목 신규 감지", ""]
    for theme_name, count in results.items():
        if count > 0:
            lines.append(f"• {theme_name}: {count}종목")

    return "\n".join(lines)


async def _handle_theme_discover(args: str) -> str:
    """
    /theme-discover [일수]
    아카이브에서 부상 테마 자동 발굴. 기본 30일.

    v3: 자동 등록 활성화 — 발굴된 테마는 Theme DB에 즉시 등록되어
    다음 월요일 08:00 theme_radar 스캔에 포함됨.
    """
    days = 30
    if args.strip():
        try:
            days = int(args.strip())
            if days < 7:
                return "최소 7일 이상 분석 가능합니다."
            if days > 180:
                return "최대 180일까지 분석 가능합니다."
        except ValueError:
            return "사용법: /theme-discover [일수]\n예: /theme-discover 30"

    await telegram_service.send_text(
        f"🔍 최근 {days}일 아카이브 분석 중... (Claude API 호출, 30초~1분 소요)"
    )

    result = await theme_discovery_service.discover_themes(days=days)

    if "error" in result:
        return f"❌ {result['error']}"

    # v3: 자동 등록 (수동 실행도 활성화)
    auto_register_summary = await theme_discovery_service.auto_register_from_analysis(
        result["analysis"]
    )

    message = (
        f"🎯 <b>테마 발굴 결과 ({days}일)</b>\n"
        f"뉴스 {result['news_count']}건 · 공시 {result['disclosure_count']}건 분석\n\n"
        f"{telegram_service.escape_html(result['analysis'])}"
        f"{auto_register_summary}"
    )

    await telegram_service.send_long_text(message)
    return ""


async def _handle_theme_trending() -> str:
    """/theme-trending — 최근 30일 언급 빈도 TOP 10 종목"""
    top_stocks = await theme_discovery_service.analyze_stock_frequency(days=30)

    if not top_stocks:
        return "최근 30일 아카이브가 없습니다."

    escape = telegram_service.escape_html

    lines = ["📊 <b>언급 빈도 TOP 10 (최근 30일)</b>", ""]
    for i, s in enumerate(top_stocks[:10], 1):
        lines.append(
            f"{i}. <b>{escape(s['stock_name'])}</b> ({s['stock_code']})\n"
            f"   └ {s['mention_count']}회 언급 · {s['unique_days']}일 노출"
        )

    lines.append("")
    lines.append("💡 /theme-discover 로 AI 테마 분석 가능")

    return "\n".join(lines)


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
    "/theme-add": _handle_theme_add,
    "/theme-remove": _handle_theme_remove,
    "/theme-list": lambda args: _handle_theme_list(),
    "/theme-scan": lambda args: _handle_theme_scan(),
    "/theme-discover": _handle_theme_discover,
    "/theme-trending": lambda args: _handle_theme_trending(),
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
