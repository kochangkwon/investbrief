"""APScheduler — 스케줄 관리"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import delete

from app.config import settings
from app.database import async_session
from app.models.brief import DailyBrief
from app.services import brief_service, daily_report_service, telegram_service, watchlist_service

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def _generate_and_send():
    """매일 아침 브리프 생성 + 텔레그램 발송"""
    logger.info("스케줄: 모닝브리프 생성 시작")
    try:
        async with async_session() as session:
            existing = await brief_service.get_brief_by_date(session, date.today())
            if existing:
                logger.info("스케줄: 오늘 브리프 이미 존재, 발송만 진행")
                await telegram_service.send_brief(existing)
                return

            brief = await brief_service.generate_daily_brief(session)
            await telegram_service.send_brief(brief)
        logger.info("스케줄: 모닝브리프 완료")
    except Exception:
        logger.exception("스케줄: 모닝브리프 생성 실패")
        await telegram_service.send_text("⚠️ 모닝브리프 생성 중 오류가 발생했습니다.")


async def _midday_watchlist_check():
    """12:00 점심 — 관심종목 변동 알림"""
    logger.info("스케줄: 점심 관심종목 체크 시작")
    try:
        async with async_session() as session:
            items = await watchlist_service.check_watchlist(session)

        if not items:
            logger.info("스케줄: 관심종목 없음, 알림 건너뜀")
            return

        # 주목할 만한 변동이 있는 종목만 필터
        alerts: list[str] = []
        for w in items:
            parts: list[str] = []

            # 가격 변동 ±2% 이상
            price = w.get("price")
            if price and abs(price["change_pct"]) >= 2.0:
                sign = "+" if price["change_pct"] > 0 else ""
                parts.append(f"주가 {sign}{price['change_pct']:.1f}%")

            # 뉴스 있음
            if w.get("news"):
                parts.append(f"뉴스 {len(w['news'])}건")

            # 공시 있음
            if w.get("disclosures"):
                parts.append(f"공시 {len(w['disclosures'])}건")

            if parts:
                alerts.append(f"• <b>{w['stock_name']}</b>: {' | '.join(parts)}")

        if not alerts:
            logger.info("스케줄: 주목할 변동 없음")
            return

        msg = "🔔 <b>점심 관심종목 알림</b>\n\n" + "\n".join(alerts)
        await telegram_service.send_text(msg)
        logger.info("스케줄: 점심 알림 발송 (%d종목)", len(alerts))

    except Exception:
        logger.exception("스케줄: 점심 체크 실패")


async def _daily_report():
    """16:30 장 마감 후 관심종목 일일 리포트"""
    logger.info("스케줄: 일일 리포트 시작")
    try:
        await daily_report_service.send_daily_report()
    except Exception:
        logger.exception("스케줄: 일일 리포트 실패")


async def _cleanup_old_data():
    """90일 이전 데이터 삭제"""
    try:
        cutoff = date.today() - timedelta(days=90)
        async with async_session() as session:
            result = await session.execute(
                delete(DailyBrief).where(DailyBrief.date < cutoff)
            )
            await session.commit()
            if result.rowcount > 0:
                logger.info("스케줄: %d건 오래된 브리프 삭제", result.rowcount)
    except Exception:
        logger.exception("스케줄: 데이터 정리 실패")


def start_scheduler():
    """스케줄러 시작"""
    hour = settings.brief_send_hour

    scheduler.add_job(_generate_and_send, "cron", hour=hour, minute=settings.brief_send_minute, id="morning_brief")
    scheduler.add_job(_midday_watchlist_check, "cron", hour=12, minute=0, id="midday_check")
    scheduler.add_job(
        _daily_report, "cron", hour=16, minute=30,
        id="daily_report", day_of_week="mon-fri",
    )
    scheduler.add_job(_cleanup_old_data, "cron", hour=18, minute=0, id="cleanup")

    scheduler.start()
    logger.info(
        "스케줄러 시작: %02d:00 브리프 | 12:00 점심체크 | 16:30 일일리포트 | 18:00 정리", hour
    )


def stop_scheduler():
    """스케줄러 종료"""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("스케줄러 종료")
