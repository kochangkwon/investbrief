import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

_KST = ZoneInfo("Asia/Seoul")


def _now_kst() -> datetime.datetime:
    return datetime.datetime.now(_KST)


# JSONB on PostgreSQL, JSON (text) on SQLite — single column type for both
_JsonList = JSON().with_variant(JSONB(), "postgresql")


class Theme(Base):
    """테마 스캐너 — 관심 테마 및 키워드 목록"""
    __tablename__ = "theme"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    keywords: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now
    )


class ThemeDetection(Base):
    """테마 스캔으로 감지된 종목 — 14일 윈도우 내 중복 검증 방지용"""
    __tablename__ = "theme_detection"
    __table_args__ = (
        # (theme_id, detected_at) 복합 인덱스 — 윈도우 쿼리 가속용
        Index("ix_theme_detection_theme_detected", "theme_id", "detected_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    theme_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("theme.id", ondelete="CASCADE"), index=True
    )
    stock_code: Mapped[str] = mapped_column(String(6))
    stock_name: Mapped[str] = mapped_column(String(100))
    headline: Mapped[str] = mapped_column(Text)
    matched_keyword: Mapped[str] = mapped_column(String(100))
    news_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    detected_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now, index=True
    )


class ThemeScanRun(Base):
    """`/theme-scan` 실행 메타데이터 — StockAI가 완료 여부 확인용"""
    __tablename__ = "theme_scan_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    scan_date: Mapped[datetime.date] = mapped_column(
        Date, nullable=False, unique=True, index=True
    )
    started_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now_kst
    )
    completed_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="running"
    )  # running | completed | failed
    total_themes: Mapped[int] = mapped_column(Integer, default=0)
    total_stocks: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class ThemeScanResult(Base):
    """`/theme-scan` 검증 통과 종목 — StockAI가 Pull로 조회"""
    __tablename__ = "theme_scan_results"
    __table_args__ = (
        UniqueConstraint(
            "scan_date", "theme_name", "stock_code",
            name="uq_theme_scan_results_date_theme_code",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    scan_date: Mapped[datetime.date] = mapped_column(Date, nullable=False, index=True)
    theme_name: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    stock_code: Mapped[str] = mapped_column(String(6), nullable=False, index=True)
    stock_name: Mapped[str] = mapped_column(Text, nullable=False)
    detected_keywords: Mapped[list[Any]] = mapped_column(_JsonList, default=list)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    claude_validation_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now_kst
    )
