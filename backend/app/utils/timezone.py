"""KST 시각 헬퍼 — 서버 TZ(UTC 가능)와 무관하게 한국 시간 보장"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def now_kst() -> datetime:
    return datetime.now(KST)


def today_kst() -> date:
    return datetime.now(KST).date()
