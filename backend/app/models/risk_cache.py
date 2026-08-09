"""DART 재무 API 응답 캐시 — 동일 종목·동일 보고서 재호출 방지."""
import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

_KST = ZoneInfo("Asia/Seoul")


class DartApiCache(Base):
    """DART Open API 원본 응답 캐시.

    cache_key 예:
      fnltt:01160363:2025:11011
      piic:01160363:20240801:20260809
    payload는 응답 JSON 문자열 그대로 (가공 전 원본 보존).
    """
    __tablename__ = "dart_api_cache"
    __table_args__ = (Index("ix_dart_cache_key", "cache_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    cache_key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.datetime.now(_KST)
    )
