"""KST 시각 헬퍼 — 서버 TZ(UTC 가능)와 무관하게 한국 시간 보장"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def now_kst() -> datetime:
    return datetime.now(KST)


def today_kst() -> date:
    return datetime.now(KST).date()


def now_kst_naive() -> datetime:
    """naive DateTime 컬럼 저장용 — KST 벽시계 값을 tzinfo 없이 반환.

    naive 컬럼(예: ThemeDetection.detected_at)에 들어가는 값과,
    그 컬럼과 비교하는 cutoff를 **동일하게 이 함수로** 생성해야 페어가 깨지지 않는다.
    """
    return datetime.now(KST).replace(tzinfo=None)
