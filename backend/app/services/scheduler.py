"""APScheduler — 스케줄 관리"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import delete

from app.config import settings
from app.database import async_session
from app.models.brief import DailyBrief
from app.services import brief_service, daily_report_service, telegram_service, theme_discovery_service, theme_radar_service, watchlist_service
from app.services.theme_alert_analytics import send_monthly_alert_report
from app.services.theme_alert_tracker import update_alert_returns_for_target

KST = ZoneInfo("Asia/Seoul")
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone=KST)


def _is_weekday() -> bool:
    """평일 여부 (KST 기준, 토/일 제외)"""
    return datetime.now(KST).weekday() < 5

async def _generate_and_send():
    """매일 아침 브리프 생성 + 텔레그램 발송"""
    if not _is_weekday():
        logger.info("스케줄: 주말 — 모닝브리프 스킵")
        return
    logger.info("스케줄: 모닝브리프 생성 시작")
    try:
        async with async_session() as session:
            existing = await brief_service.get_brief_by_date(session, date.today())
            if existing:
                if existing.sent_at:
                    logger.info("스케줄: 오늘 브리프 이미 발송됨, 스킵")
                    return
                logger.info("스케줄: 오늘 브리프 존재, 미발송 → 발송 진행")
                sent = await telegram_service.send_brief(existing)
                if sent:
                    existing.sent_at = datetime.now()
                    await session.commit()
                    logger.info("스케줄: 기존 브리프 재발송 성공")
                else:
                    logger.error("스케줄: 기존 브리프 재발송 실패 — sent_at 기록 보류")
                    await telegram_service.send_text(
                        "⚠️ 모닝브리프 발송에 실패했습니다. 다음 스케줄에 재시도합니다."
                    )
                return

            brief = await brief_service.generate_daily_brief(session)
            sent = await telegram_service.send_brief(brief)
            if sent:
                brief.sent_at = datetime.now()
                await session.commit()
                logger.info("스케줄: 모닝브리프 완료")
            else:
                logger.error(
                    "스케줄: 모닝브리프 발송 실패 (id=%s) — sent_at 기록 보류, 다음 스케줄에 재시도",
                    brief.id,
                )
                await telegram_service.send_text(
                    "⚠️ 모닝브리프 발송에 실패했습니다. 다음 스케줄에 재시도합니다."
                )
    except Exception:
        logger.exception("스케줄: 모닝브리프 생성 실패")
        await telegram_service.send_text("⚠️ 모닝브리프 생성 중 오류가 발생했습니다.")


async def _send_us_market():
    """평일 미국 시장 동향 발송 (모닝브리프와 분리)"""
    if not _is_weekday():
        logger.info("스케줄: 주말 — 미국 시장 발송 스킵")
        return
    logger.info("스케줄: 미국 시장 동향 발송 시작")
    try:
        sent = await telegram_service.send_us_market_brief()
        if sent:
            logger.info("스케줄: 미국 시장 발송 완료")
        else:
            logger.info("스케줄: 미국 시장 데이터 없음 — 발송 스킵")
    except Exception:
        logger.exception("스케줄: 미국 시장 발송 실패")


async def _midday_watchlist_check():
    """12:00 점심 — 관심종목 변동 알림"""
    if not _is_weekday():
        logger.info("스케줄: 주말 — 점심 체크 스킵")
        return
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
        await telegram_service.send_text("⚠️ 점심 관심종목 체크 중 오류가 발생했습니다.")


async def _daily_report():
    """16:30 장 마감 후 관심종목 일일 리포트"""
    logger.info("스케줄: 일일 리포트 시작")
    try:
        await daily_report_service.send_daily_report()
    except Exception:
        logger.exception("스케줄: 일일 리포트 실패")
        await telegram_service.send_text("⚠️ 일일 리포트 생성 중 오류가 발생했습니다.")


async def _daily_theme_scan():
    """평일 매일 테마 선행 스캐너 (08:10 KST)"""
    logger.info("일일 테마 스캔 시작")
    try:
        results = await theme_radar_service.scan_all_themes()
        total_new = sum(results.values())
        logger.info("일일 테마 스캔 완료 — 신규 감지 %d건: %s", total_new, results)
    except Exception:
        logger.exception("일일 테마 스캔 실패")


async def _weekly_theme_discovery():
    """주 1회 아카이브 기반 테마 발굴 (매주 일요일 09:00)"""
    logger.info("주간 테마 발굴 시작")
    try:
        await theme_discovery_service.send_weekly_theme_report()
        logger.info("주간 테마 발굴 완료")
    except Exception:
        logger.exception("주간 테마 발굴 실패")


async def _track_alert_returns_30d():
    try:
        await update_alert_returns_for_target(30)
    except Exception:
        logger.exception("스케줄: D+30 알림 가격 추적 실패")


async def _track_alert_returns_60d():
    try:
        await update_alert_returns_for_target(60)
    except Exception:
        logger.exception("스케줄: D+60 알림 가격 추적 실패")


async def _track_alert_returns_90d():
    try:
        await update_alert_returns_for_target(90)
    except Exception:
        logger.exception("스케줄: D+90 알림 가격 추적 실패")


async def _monthly_alert_report():
    try:
        await send_monthly_alert_report()
    except Exception:
        logger.exception("스케줄: 월간 테마 알림 리포트 실패")


async def _cleanup_old_data():
    """180일 이전 데이터 삭제 — 테마 발굴용 누적 데이터 확보"""
    try:
        cutoff = date.today() - timedelta(days=180)
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
    # 구버전 job ID 잔재 정리 (영속 jobstore 사용 시 안전장치 — 1회용)
    try:
        scheduler.remove_job("weekly_theme_scan")
        logger.info("구 job 'weekly_theme_scan' 제거")
    except Exception:
        pass  # 없으면 정상

    hour = settings.brief_send_hour

    scheduler.add_job(_generate_and_send, "cron", hour=hour, minute=settings.brief_send_minute, id="morning_brief")
    scheduler.add_job(
        _send_us_market, "cron",
        day_of_week="mon-fri",
        hour=settings.us_market_send_hour, minute=settings.us_market_send_minute,
        id="us_market_brief", replace_existing=True, misfire_grace_time=300,
    )
    scheduler.add_job(_midday_watchlist_check, "cron", hour=12, minute=0, id="midday_check")
    scheduler.add_job(
        _daily_report, "cron", hour=16, minute=30,
        id="daily_report", day_of_week="mon-fri",
    )
    scheduler.add_job(
        _daily_theme_scan, "cron",
        day_of_week="mon-fri",  # 평일 매일 (주말 한국 증시 휴장)
        hour=8, minute=10,
        id="daily_theme_scan",
        replace_existing=True,
        misfire_grace_time=300,  # 서버 재시작 등으로 5분 내 늦어져도 재시도 허용
    )
    scheduler.add_job(
        _weekly_theme_discovery, "cron",
        day_of_week="sun", hour=9, minute=0,
        id="weekly_theme_discovery",
    )
    scheduler.add_job(_cleanup_old_data, "cron", hour=18, minute=0, id="cleanup")

    # ── v3 Phase 3: 테마 알림 D+30/60/90 가격 추적 (매일 18:05/15/25) ──
    scheduler.add_job(
        _track_alert_returns_30d, "cron", hour=18, minute=5,
        id="theme_alert_returns_30d", replace_existing=True, misfire_grace_time=3600,
    )
    scheduler.add_job(
        _track_alert_returns_60d, "cron", hour=18, minute=15,
        id="theme_alert_returns_60d", replace_existing=True, misfire_grace_time=3600,
    )
    scheduler.add_job(
        _track_alert_returns_90d, "cron", hour=18, minute=25,
        id="theme_alert_returns_90d", replace_existing=True, misfire_grace_time=3600,
    )
    # ── v3 Phase 4: 월간 리포트 (매월 1일 09:10) ──
    scheduler.add_job(
        _monthly_alert_report, "cron", day=1, hour=9, minute=10,
        id="theme_alert_monthly_report", replace_existing=True, misfire_grace_time=3600 * 24,
    )

    scheduler.start()
    logger.info(
        "스케줄러 시작: %02d:%02d 브리프 | 평일 %02d:%02d 미국시장 | 12:00 점심체크 | 16:30 일일리포트 | 평일 08:10 일일테마스캔 | 일 09:00 테마발굴 | 18:00 정리",
        hour, settings.brief_send_minute,
        settings.us_market_send_hour, settings.us_market_send_minute,
    )


def stop_scheduler():
    """스케줄러 종료"""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("스케줄러 종료")
