"""모닝브리프 백필 스크립트

사용법:
    cd backend
    python -m scripts.backfill_brief 2026-05-01 2026-05-02

각 날짜별로 generate_daily_brief(target_date=...)를 호출.
기존 동일 날짜 레코드가 있으면 삭제 후 재생성.
텔레그램 발송은 스킵.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from datetime import date

from app.database import async_session
from app.services import brief_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("backfill")


async def backfill(targets: list[date]) -> None:
    async with async_session() as session:
        for d in targets:
            logger.info("=== 백필 시작: %s ===", d)
            existing = await brief_service.get_brief_by_date(session, d)
            if existing:
                await session.delete(existing)
                await session.commit()
                logger.info("기존 레코드 삭제: id=%s", existing.id)

            brief = await brief_service.generate_daily_brief(session, target_date=d)
            logger.info(
                "완료 id=%s date=%s news=%d disclosures=%d watchlist=%d",
                brief.id,
                brief.date,
                len(brief.news_raw or []),
                len(brief.disclosures or []),
                len(brief.watchlist_check or []),
            )


def main() -> None:
    if len(sys.argv) < 2:
        print("사용법: python -m scripts.backfill_brief YYYY-MM-DD [YYYY-MM-DD ...]")
        sys.exit(1)

    targets = [date.fromisoformat(arg) for arg in sys.argv[1:]]
    asyncio.run(backfill(targets))


if __name__ == "__main__":
    main()
