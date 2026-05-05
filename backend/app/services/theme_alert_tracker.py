"""테마 알림 D+N 가격 추적 (v3 Phase 3)

매일 18:05/15/25에 D+30/60/90 갱신 — 알림 발송 후 N영업일 경과한 후보의
종가/수익률을 가져와 ThemeAlertCandidate에 기록한다.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import and_, select

from app.collectors import price_collector
from app.database import async_session
from app.models.theme_alert import ThemeAlert, ThemeAlertCandidate

logger = logging.getLogger(__name__)


async def _fetch_close_on_or_before(stock_code: str, target: date) -> Optional[int]:
    """target 이전(포함)의 가장 최근 영업일 종가 (원, 정수)."""
    close = await asyncio.to_thread(
        price_collector.fetch_last_close,
        stock_code,
        on_or_before=target,
        lookback_days=7,
    )
    return int(close) if close else None


async def _fetch_kospi_on_or_before(target: date) -> Optional[float]:
    """target 이전(포함)의 코스피 종가."""
    return await asyncio.to_thread(
        price_collector.fetch_last_close,
        "KS11",
        on_or_before=target,
        lookback_days=7,
    )


def _column_names(target_n: int) -> tuple[str, str, str]:
    """N → (price_d{N}, return_{N}d, kospi_return_{N}d) 컬럼명 반환."""
    return f"price_d{target_n}", f"return_{target_n}d", f"kospi_return_{target_n}d"


async def update_alert_returns_for_target(target_n: int) -> int:
    """
    D+target_n 가격 갱신.

    조건:
    - alert.sent_at + target_n일 <= 오늘
    - candidate.{return_Nd}가 아직 NULL
    - price_at_alert가 존재 (수익률 계산 기반)

    Returns
    -------
    갱신된 후보 행 수
    """
    price_col, return_col, kospi_return_col = _column_names(target_n)

    today = date.today()
    cutoff = today - timedelta(days=target_n)
    cutoff_dt = datetime.combine(cutoff, datetime.min.time())

    updated = 0

    async with async_session() as db:
        # 갱신 대상 알림: sent_at <= cutoff_dt
        stmt = (
            select(ThemeAlertCandidate, ThemeAlert)
            .join(ThemeAlert, ThemeAlertCandidate.alert_id == ThemeAlert.id)
            .where(
                and_(
                    ThemeAlert.sent_at <= cutoff_dt,
                    getattr(ThemeAlertCandidate, return_col).is_(None),
                    ThemeAlertCandidate.price_at_alert.isnot(None),
                )
            )
        )
        rows = (await db.execute(stmt)).all()

        if not rows:
            logger.info("D+%d 갱신: 대상 없음 (cutoff=%s)", target_n, cutoff)
            return 0

        for cand, alert in rows:
            target_date = (alert.sent_at + timedelta(days=target_n)).date()
            if target_date > today:
                continue  # 안전망

            # 종목 종가
            close = await _fetch_close_on_or_before(cand.stock_code, target_date)
            if close is None:
                continue
            setattr(cand, price_col, close)
            try:
                setattr(
                    cand, return_col,
                    round((close - cand.price_at_alert) / cand.price_at_alert * 100, 2),
                )
            except (TypeError, ZeroDivisionError):
                pass

            # KOSPI 수익률 (alpha 계산용)
            if cand.kospi_at_alert:
                kospi_close = await _fetch_kospi_on_or_before(target_date)
                if kospi_close:
                    try:
                        setattr(
                            cand, kospi_return_col,
                            round((kospi_close - cand.kospi_at_alert) / cand.kospi_at_alert * 100, 2),
                        )
                    except (TypeError, ZeroDivisionError):
                        pass

            updated += 1

        try:
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("D+%d 갱신 commit 실패", target_n)
            return 0

    logger.info("D+%d 가격 갱신 완료: %d건", target_n, updated)
    return updated
