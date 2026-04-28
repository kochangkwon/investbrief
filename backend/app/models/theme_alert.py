"""테마 알림 측정 인프라 (v3 Phase 1)

InvestBrief가 자체 DB에 측정 데이터를 누적해 1-2개월 후 KPI 기반 의사결정 가능.

ThemeAlert            : 알림 1건 (theme_name + sent_at)
ThemeAlertCandidate   : 알림 내 종목 후보 (price_at_alert / D+30/60/90 수익률)
"""
from __future__ import annotations

import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime.datetime:
    return datetime.datetime.utcnow()


class ThemeAlert(Base):
    """알림 1건 — 테마 단위로 발송된 묶음"""
    __tablename__ = "theme_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_uid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    theme_id: Mapped[str] = mapped_column(String(120), index=True)
    theme_name: Mapped[str] = mapped_column(String(200))
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    sent_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=utcnow, index=True
    )

    candidates: Mapped[list["ThemeAlertCandidate"]] = relationship(
        back_populates="alert",
        cascade="all, delete-orphan",
    )


class ThemeAlertCandidate(Base):
    """알림 내 종목 후보 — 가격 스냅샷 + D+N 수익률 추적"""
    __tablename__ = "theme_alert_candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("theme_alerts.id", ondelete="CASCADE"), index=True
    )
    stock_code: Mapped[str] = mapped_column(String(10), index=True)
    stock_name: Mapped[str] = mapped_column(String(100))
    sub_theme: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    matched_news_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 가격 스냅샷 (알림 발송 시점 종가)
    price_at_alert: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # D+N 가격 / 수익률 (Phase 3 자동 갱신)
    price_d30: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    price_d60: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    price_d90: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    return_30d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    return_60d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    return_90d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 코스피 대비 alpha 비교용
    kospi_at_alert: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    kospi_return_30d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    kospi_return_60d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    kospi_return_90d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=utcnow
    )

    alert: Mapped["ThemeAlert"] = relationship(back_populates="candidates")
