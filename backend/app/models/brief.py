import datetime
from typing import Optional

from sqlalchemy import JSON, Date, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DailyBrief(Base):
    __tablename__ = "daily_briefs"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[datetime.date] = mapped_column(Date, unique=True, index=True)
    global_market: Mapped[dict] = mapped_column(JSON)
    domestic_market: Mapped[dict] = mapped_column(JSON)
    news_summary: Mapped[str] = mapped_column(Text)
    news_raw: Mapped[list] = mapped_column(JSON)
    disclosures: Mapped[list] = mapped_column(JSON)
    watchlist_check: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now
    )
    sent_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime, nullable=True, default=None
    )
