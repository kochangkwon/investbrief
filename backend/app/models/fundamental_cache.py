"""펀더멘털 최소 캐시 — 분기별 흑/적자 + 영업이익률."""
import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

_KST = ZoneInfo("Asia/Seoul")


class FundamentalSimple(Base):
    """종목별 분기 손익 캐시 (DART 직접 조회).

    매출/영업이익/당기순이익만 저장.
    PER/ROE 등은 P2-7 도입 시 별도 컬럼 추가.
    """
    __tablename__ = "fundamental_simple"
    __table_args__ = (
        UniqueConstraint("stock_code", "year", "quarter", name="uq_fs_code_year_q"),
        Index("ix_fs_stock_code", "stock_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(6), nullable=False)
    corp_code: Mapped[str] = mapped_column(String(8), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    quarter: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-4

    # 손익 (단위: 억원)
    revenue: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    operating_profit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    net_income: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 계산 지표
    operating_margin_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_profitable: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    fetched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.datetime.now(_KST)
    )


class StockCorpMap(Base):
    """stock_code ↔ corp_code 단순 매핑 캐시.

    DART 공시 응답에서 함께 오는 정보를 누적 저장.
    별도 전체 다운로드 없이 운영하며 자연스럽게 커버리지 확대.
    """
    __tablename__ = "stock_corp_map"
    __table_args__ = (
        Index("ix_stock_corp_code", "stock_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(6), unique=True, nullable=False)
    corp_code: Mapped[str] = mapped_column(String(8), nullable=False)
    corp_name: Mapped[str] = mapped_column(String(200), nullable=False)
    last_seen: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.datetime.now(_KST)
    )
