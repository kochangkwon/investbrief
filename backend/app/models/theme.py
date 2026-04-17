import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


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
    """테마 스캔으로 감지된 종목 — 중복 알림 방지용"""
    __tablename__ = "theme_detection"

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
        DateTime, default=datetime.datetime.now
    )
