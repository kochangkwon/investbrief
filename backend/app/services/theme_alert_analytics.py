"""테마 알림 월간 리포트 (v3 Phase 4)

매월 1일 09:10 KST에 텔레그램으로 자동 발송.
- 지난달 알림 통계
- D+30 평균 수익률 / KOSPI 대비 alpha
- 테마별 성과 TOP 3
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import and_, case, func, select

from app.database import async_session
from app.models.theme_alert import ThemeAlert, ThemeAlertCandidate
from app.services import telegram_service
from app.utils.timezone import today_kst

logger = logging.getLogger(__name__)

VERSION_MIN_SAMPLES = 30  # v2 표본 30건 미만이면 판정 유보 (지시서 F-패치)


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


async def collect_version_stats() -> list[dict[str, Any]]:
    """프롬프트 버전(NULL=v1, "v2")별 전체 누적 집계 — 타율(양수 비율) 1순위.

    v1(F 이전) vs v2(엄격 검증) 효과 비교용. 기간 필터 없이 전체 누적을 본다
    (v1은 과거, v2는 최근이므로 월 단위로는 비교가 성립하지 않음).
    """
    ver = func.coalesce(ThemeAlertCandidate.prompt_version, "v1").label("ver")
    async with async_session() as db:
        rows = (
            await db.execute(
                select(
                    ver,
                    func.count(ThemeAlertCandidate.id).label("total"),
                    func.count(ThemeAlertCandidate.return_30d).label("matured"),
                    func.avg(ThemeAlertCandidate.return_30d).label("avg30"),
                    func.avg(ThemeAlertCandidate.return_60d).label("avg60"),
                    func.avg(ThemeAlertCandidate.return_90d).label("avg90"),
                    func.sum(
                        case((ThemeAlertCandidate.return_30d > 0, 1), else_=0)
                    ).label("pos30"),
                )
                .group_by(ver)
                .order_by(ver)
            )
        ).all()

    out: list[dict[str, Any]] = []
    for r in rows:
        matured = int(r.matured or 0)
        pos30 = int(r.pos30 or 0)
        out.append({
            "version": r.ver,
            "total": int(r.total or 0),
            "matured": matured,
            "avg_30d": float(r.avg30) if r.avg30 is not None else None,
            "avg_60d": float(r.avg60) if r.avg60 is not None else None,
            "avg_90d": float(r.avg90) if r.avg90 is not None else None,
            "positive_ratio": (100.0 * pos30 / matured) if matured else None,
        })
    return out


def _format_version_block(version_stats: list[dict[str, Any]]) -> list[str]:
    """v1/v2 비교 블록 렌더링. 후보 수 감소는 실패 아님 — 타율이 지표."""
    if not version_stats:
        return []
    lines = ["", "<b>[프롬프트 버전 비교] (전체 누적)</b>"]
    v2 = next((v for v in version_stats if v["version"] == "v2"), None)
    for v in version_stats:
        avg = f"{v['avg_30d']:+.1f}%" if v["avg_30d"] is not None else "N/A"
        ratio = f"{v['positive_ratio']:.0f}%" if v["positive_ratio"] is not None else "N/A"
        lines.append(
            f"  {v['version']}: {v['total']}건(성숙 {v['matured']}) | "
            f"30일 평균 {avg} | 양수 비율 {ratio}"
        )
    if v2 is None or v2["matured"] < VERSION_MIN_SAMPLES:
        have = v2["matured"] if v2 else 0
        lines.append(
            f"  ※ v2 성숙 표본 {have}/{VERSION_MIN_SAMPLES}건 — 판정 유보"
        )
    lines.append("  ※ 후보 수 감소는 실패 아님 — 양수 비율(타율)이 판정 지표")
    return lines


def _format_report(period_label: str, stats: dict[str, Any]) -> str:
    def esc(text: str) -> str:
        return telegram_service.escape_html(text or "")

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
    today = today_kst()
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
        version_stats = await collect_version_stats()
        block = _format_version_block(version_stats)
        if block:
            msg += "\n" + "\n".join(block)
    except Exception:
        logger.exception("버전 비교 블록 생성 실패 (월간 리포트는 계속)")
    try:
        ok = await telegram_service.send_text(msg)
        if ok:
            logger.info("월간 리포트 발송 완료: %s", period_label)
        return ok
    except Exception:
        logger.exception("월간 리포트 발송 실패")
        return False
