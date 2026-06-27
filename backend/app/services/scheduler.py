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
from app.services import ai_summarizer, brief_service, daily_report_service, telegram_service, theme_discovery_service, theme_radar_service, watchlist_service
from app.services.theme_alert_analytics import send_monthly_alert_report
from app.services.theme_alert_tracker import update_alert_returns_for_target
from app.utils.timezone import now_kst_naive, today_kst

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
            existing = await brief_service.get_brief_by_date(session, today_kst())
            if existing:
                if existing.sent_at:
                    logger.info("스케줄: 오늘 브리프 이미 발송됨, 스킵")
                    return
                logger.info("스케줄: 오늘 브리프 존재, 미발송 → 발송 진행")
                sent = await telegram_service.send_brief(existing)
                if sent:
                    existing.sent_at = now_kst_naive()
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
                brief.sent_at = now_kst_naive()
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


DROP_THRESHOLD_PCT = -5.0  # 전일 대비 이 % 이하로 하락하면 급락 알림
_drop_alert_sent: dict[str, date] = {}  # stock_code -> 마지막 알림 발송일 (종목당 하루 1회 쿨다운)


async def _intraday_drop_check():
    """장중 30분 — 관심종목 급락 감지 + AI 이슈 분석 알림 (평일 09:00~15:30)"""
    if not _is_weekday():
        return
    logger.info("스케줄: 장중 급락 체크 시작")
    try:
        async with async_session() as session:
            drops = await watchlist_service.detect_price_drops(session, DROP_THRESHOLD_PCT)

        if not drops:
            return

        today = datetime.now(KST).date()
        for d in drops:
            code = d["stock_code"]
            # 종목당 하루 1회 쿨다운 (30분 폴링 중복 알림 방지)
            if _drop_alert_sent.get(code) == today:
                continue

            price = d["price"]
            analysis = await ai_summarizer.analyze_price_drop(
                stock_name=d["stock_name"],
                stock_code=code,
                change_pct=price["change_pct"],
                current_price=price["close"],
                news_items=d["news"],
                disclosure_items=d["disclosures"],
            )

            msg = (
                f"🚨 <b>급락 감지 — {telegram_service.escape_html(d['stock_name'])}</b>\n"
                f"현재가 {int(price['close']):,}원 ({price['change_pct']:.1f}%)\n\n"
                + telegram_service.escape_html(analysis)
            )

            # 관련 뉴스 링크 (최대 2건)
            links = [
                f'• <a href="{n["link"]}">{telegram_service.escape_html(n["title"][:40])}</a>'
                for n in d["news"][:2] if n.get("link")
            ]
            if links:
                msg += "\n\n📰 관련 뉴스\n" + "\n".join(links)

            sent = await telegram_service.send_text(msg)
            if sent:
                _drop_alert_sent[code] = today
                logger.info(
                    "스케줄: 급락 알림 발송 — %s (%.1f%%)",
                    d["stock_name"], price["change_pct"],
                )
            else:
                logger.error("스케줄: 급락 알림 발송 실패 — %s", d["stock_name"])

    except Exception:
        logger.exception("스케줄: 장중 급락 체크 실패")


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
    await telegram_service.send_text("🔍 테마 스캔 시작")
    try:
        results = await theme_radar_service.scan_all_themes()
        total_new = sum(results.values())
        logger.info("일일 테마 스캔 완료 — 신규 감지 %d건: %s", total_new, results)
        hit_lines = [
            f"• {telegram_service.escape_html(name)}: {count}건"
            for name, count in results.items() if count
        ]
        detail = "\n" + "\n".join(hit_lines) if hit_lines else ""
        await telegram_service.send_text(
            f"✅ 테마 스캔 완료 — 신규 감지 {total_new}건{detail}"
        )
    except Exception:
        logger.exception("일일 테마 스캔 실패")
        await telegram_service.send_text("⚠️ 테마 스캔 중 오류가 발생했습니다.")


async def _weekly_theme_discovery():
    """주 1회 아카이브 기반 테마 발굴 + 휴면 테마 정리 (매주 월요일 07:45)"""
    logger.info("주간 테마 발굴 시작")
    try:
        await theme_discovery_service.send_weekly_theme_report()
        logger.info("주간 테마 발굴 완료")
    except Exception:
        logger.exception("주간 테마 발굴 실패")

    # 휴면 테마 자동 비활성화 (42일 무감지 + 생성 42일 경과 — 계절성 테마 보호)
    try:
        deactivated = await theme_discovery_service.deactivate_stale_themes()
        if deactivated:
            await telegram_service.send_text(
                f"🧹 휴면 테마 {len(deactivated)}건 비활성화: "
                f"{', '.join(deactivated)} (재활성화: /theme-add 재등록)"
            )
            logger.info("휴면 테마 %d건 비활성화: %s", len(deactivated), deactivated)
    except Exception:
        logger.exception("휴면 테마 정리 실패")


from pathlib import Path

# "오를 종목" 피처 검증 자동 실행 (데이터 ~2.5개월 누적 후 1회)
FEATURE_VALIDATION_TARGET = date(2026, 9, 11)
_FEATURE_VALIDATION_MARKER = Path(__file__).resolve().parents[2] / ".feature_validation_done"


async def _feature_validation_check():
    """목표일 이후 매일 게이트 체크 → 데이터 충분하면 1회 분석·발송 후 마커."""
    if _FEATURE_VALIDATION_MARKER.exists():
        return
    if today_kst() < FEATURE_VALIDATION_TARGET:
        return
    try:
        from app.services import feature_validation_service as fv
        from app.services import stock_picker_service as sp
        result = await fv.analyze()
        if not result.get("ready"):
            logger.info("피처 검증 대기: %s", result.get("reason"))
            return
        # 양수·robust 신호를 픽커 설정으로 저장 (없으면 빈 리스트 → 픽커 무동작)
        signals = fv.extract_picker_signals(result)
        sp.save_signals(signals, validated_at=today_kst().isoformat())
        await telegram_service.send_text(fv.format_report(result))
        if signals:
            await telegram_service.send_text(
                f"✅ 양수·robust 신호 {len(signals)}개 발견 → 내일부터 '오를 종목 후보' 자동 발송."
            )
        else:
            await telegram_service.send_text(
                "ℹ️ 양수·robust 신호 없음 → '오를 종목 후보'는 보류(방어 필터는 유지)."
            )
        _FEATURE_VALIDATION_MARKER.write_text(today_kst().isoformat())
        logger.info("피처 검증 자동 분석 발송 완료 (N=%d, 신호=%d)", result["n"], len(signals))
    except Exception:
        logger.exception("피처 검증 자동 분석 실패")


async def _stock_picker_run():
    """매일 스캔 후 — 검증 신호가 있으면 당일 통과 종목 점수화·후보 발송 (없으면 no-op)."""
    try:
        from app.services import stock_picker_service as sp
        await sp.run_and_send()
    except Exception:
        logger.exception("스케줄: 오를 종목 후보 픽커 실패")


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
        cutoff = today_kst() - timedelta(days=180)
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

    scheduler.add_job(_generate_and_send, "cron", day_of_week="mon-fri", hour=hour, minute=settings.brief_send_minute, id="morning_brief", replace_existing=True)
    scheduler.add_job(
        _send_us_market, "cron",
        day_of_week="mon-fri",
        hour=settings.us_market_send_hour, minute=settings.us_market_send_minute,
        id="us_market_brief", replace_existing=True, misfire_grace_time=300,
    )
    scheduler.add_job(_midday_watchlist_check, "cron", day_of_week="mon-fri", hour=12, minute=0, id="midday_check", replace_existing=True)
    scheduler.add_job(
        _intraday_drop_check, "cron",
        day_of_week="mon-fri", hour="9-15", minute="0,30",  # 09:00~15:30 30분 간격
        id="intraday_drop_check", replace_existing=True, misfire_grace_time=120,
    )
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
        day_of_week="mon", hour=7, minute=45,
        id="weekly_theme_discovery",
        replace_existing=True,
        misfire_grace_time=3600,  # 서버 부팅 지연 대비 (일요일 서버 중지 환경)
    )
    scheduler.add_job(_cleanup_old_data, "cron", day_of_week="mon-fri", hour=18, minute=0, id="cleanup", replace_existing=True)

    # "오를 종목" 피처 검증 — 목표일 이후 매일 체크, 충분하면 1회 자동 분석·발송
    scheduler.add_job(
        _feature_validation_check, "cron", day_of_week="mon-fri", hour=18, minute=35,
        id="feature_validation_check", replace_existing=True, misfire_grace_time=3600,
    )
    # 오를 종목 후보 픽커 — 평일 스캔(08:10) 후 검증 신호 있으면 자동 발송
    scheduler.add_job(
        _stock_picker_run, "cron", day_of_week="mon-fri", hour=8, minute=25,
        id="stock_picker_run", replace_existing=True, misfire_grace_time=600,
    )

    # ── v3 Phase 3: 테마 알림 D+30/60/90 가격 추적 (평일 18:05/15/25) ──
    scheduler.add_job(
        _track_alert_returns_30d, "cron", day_of_week="mon-fri", hour=18, minute=5,
        id="theme_alert_returns_30d", replace_existing=True, misfire_grace_time=3600,
    )
    scheduler.add_job(
        _track_alert_returns_60d, "cron", day_of_week="mon-fri", hour=18, minute=15,
        id="theme_alert_returns_60d", replace_existing=True, misfire_grace_time=3600,
    )
    scheduler.add_job(
        _track_alert_returns_90d, "cron", day_of_week="mon-fri", hour=18, minute=25,
        id="theme_alert_returns_90d", replace_existing=True, misfire_grace_time=3600,
    )
    # ── v3 Phase 4: 월간 리포트 (매월 1일 09:10) ──
    scheduler.add_job(
        _monthly_alert_report, "cron", day=1, hour=9, minute=10,
        id="theme_alert_monthly_report", replace_existing=True, misfire_grace_time=3600 * 24,
    )

    scheduler.start()
    logger.info(
        "스케줄러 시작: %02d:%02d 브리프 | 평일 %02d:%02d 미국시장 | 12:00 점심체크 | 평일 09:00~15:30 급락체크(30분) | 16:30 일일리포트 | 평일 08:10 일일테마스캔 | 일 09:00 테마발굴 | 18:00 정리",
        hour, settings.brief_send_minute,
        settings.us_market_send_hour, settings.us_market_send_minute,
    )


def stop_scheduler():
    """스케줄러 종료"""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("스케줄러 종료")
