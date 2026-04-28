"""테마 알림 월간 리포트 (v3 Phase 4)

매월 1일 09:10 KST에 텔레그램으로 자동 발송.
- 지난달 알림 통계
- D+30 평균 수익률 / KOSPI 대비 alpha
- 테마별 성과 TOP 3
"""
from __future__ import annotations

import html
import logging
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, select

from app.database import async_session
from app.models.theme_alert import ThemeAlert, ThemeAlertCandidate
from app.services import telegram_service

logger = logging.getLogger(__name__)


def _last_month_range(today: date) -> tuple[datetime, datetime]:
    """오늘 기준 지난달의 [시작 datetime, 끝 datetime)."""
    first_this_month = today.replace(day=1)
    last_month_end = first_this_month - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    return (
        datetime.combine(last_month_start, datetime.min.time()),
        datetime.combine(first_this_month, datetime.min.time()),
    )


async def _collect_monthly_stats(start_dt: datetime, end_dt: datetime) -> dict[str, Any]:
    async with async_session() as db:
        # 알림 건수 / 후보 수
        alert_count = await db.scalar(
            select(func.count(ThemeAlert.id))
            .where(and_(ThemeAlert.sent_at >= start_dt, ThemeAlert.sent_at < end_dt))
        ) or 0

        candidate_count = await db.scalar(
            select(func.count(ThemeAlertCandidate.id))
            .join(ThemeAlert, ThemeAlertCandidate.alert_id == ThemeAlert.id)
            .where(and_(ThemeAlert.sent_at >= start_dt, ThemeAlert.sent_at < end_dt))
        ) or 0

        # D+30 수익률 평균
        avg_30 = await db.scalar(
            select(func.avg(ThemeAlertCandidate.return_30d))
            .join(ThemeAlert, ThemeAlertCandidate.alert_id == ThemeAlert.id)
            .where(
                and_(
                    ThemeAlert.sent_at >= start_dt,
                    ThemeAlert.sent_at < end_dt,
                    ThemeAlertCandidate.return_30d.isnot(None),
                )
            )
        )

        avg_kospi_30 = await db.scalar(
            select(func.avg(ThemeAlertCandidate.kospi_return_30d))
            .join(ThemeAlert, ThemeAlertCandidate.alert_id == ThemeAlert.id)
            .where(
                and_(
                    ThemeAlert.sent_at >= start_dt,
                    ThemeAlert.sent_at < end_dt,
                    ThemeAlertCandidate.kospi_return_30d.isnot(None),
                )
            )
        )

        # 테마별 성과 TOP 3
        theme_rows = (
            await db.execute(
                select(
                    ThemeAlert.theme_name,
                    func.count(ThemeAlertCandidate.id).label("samples"),
                    func.avg(ThemeAlertCandidate.return_30d).label("avg_return"),
                )
                .join(ThemeAlertCandidate, ThemeAlertCandidate.alert_id == ThemeAlert.id)
                .where(
                    and_(
                        ThemeAlert.sent_at >= start_dt,
                        ThemeAlert.sent_at < end_dt,
                        ThemeAlertCandidate.return_30d.isnot(None),
                    )
                )
                .group_by(ThemeAlert.theme_name)
                .having(func.count(ThemeAlertCandidate.id) >= 1)
                .order_by(func.avg(ThemeAlertCandidate.return_30d).desc())
                .limit(3)
            )
        ).all()

    return {
        "alert_count": int(alert_count),
        "candidate_count": int(candidate_count),
        "avg_return_30d": float(avg_30) if avg_30 is not None else None,
        "avg_kospi_30d": float(avg_kospi_30) if avg_kospi_30 is not None else None,
        "top_themes": [
            {
                "theme_name": r.theme_name,
                "samples": int(r.samples),
                "avg_return": float(r.avg_return) if r.avg_return is not None else 0.0,
            }
            for r in theme_rows
        ],
    }


def _format_report(period_label: str, stats: dict[str, Any]) -> str:
    def esc(text: str) -> str:
        return html.escape(text or "")

    lines = [f"📊 <b>테마 알림 월간 리포트</b> ({esc(period_label)})", ""]
    lines.append(f"• 알림 건수: <b>{stats['alert_count']}</b>건")
    lines.append(f"• 후보 종목: <b>{stats['candidate_count']}</b>개")
    lines.append("")

    if stats["avg_return_30d"] is not None:
        alpha = None
        if stats["avg_kospi_30d"] is not None:
            alpha = stats["avg_return_30d"] - stats["avg_kospi_30d"]
        lines.append("<b>D+30 성과</b>")
        lines.append(f"  평균 수익률: {stats['avg_return_30d']:+.2f}%")
        if stats["avg_kospi_30d"] is not None:
            lines.append(f"  KOSPI 대비: {stats['avg_kospi_30d']:+.2f}%")
        if alpha is not None:
            lines.append(f"  Alpha: <b>{alpha:+.2f}%</b>")
        lines.append("")
    else:
        lines.append("<i>D+30 데이터 부족 (다음달부터 본격 측정)</i>")
        lines.append("")

    if stats["top_themes"]:
        lines.append("<b>테마별 TOP 3 (D+30)</b>")
        for i, t in enumerate(stats["top_themes"], 1):
            lines.append(
                f"  {i}. {esc(t['theme_name'])} — {t['avg_return']:+.2f}% ({t['samples']}종목)"
            )

    return "\n".join(lines)


async def send_monthly_alert_report() -> bool:
    """매월 1일 09:10 호출 — 지난달 통계 텔레그램 발송."""
    today = date.today()
    start_dt, end_dt = _last_month_range(today)
    period_label = f"{start_dt.strftime('%Y-%m')}"

    try:
        stats = await _collect_monthly_stats(start_dt, end_dt)
    except Exception:
        logger.exception("월간 리포트 통계 수집 실패")
        return False

    if stats["alert_count"] == 0:
        logger.info("월간 리포트: %s 알림 없음, 발송 스킵", period_label)
        return False

    msg = _format_report(period_label, stats)
    try:
        ok = await telegram_service.send_text(msg)
        if ok:
            logger.info("월간 리포트 발송 완료: %s", period_label)
        return ok
    except Exception:
        logger.exception("월간 리포트 발송 실패")
        return False
