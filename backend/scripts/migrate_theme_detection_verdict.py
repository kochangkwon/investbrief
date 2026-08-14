"""theme_detection.verdict 컬럼 추가 (NO 판정 기록용).

create_all은 기존 테이블에 컬럼을 추가하지 않으므로 1회 실행 필요.
    cd backend && python3 scripts/migrate_theme_detection_verdict.py

기존 행은 NULL 유지 — NULL은 레거시 YES로 해석된다 (theme_radar_service).
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.database import engine  # noqa: E402


async def main() -> None:
    async with engine.begin() as conn:
        result = await conn.execute(text("SELECT * FROM theme_detection LIMIT 0"))
        if "verdict" in result.keys():
            print("verdict 컬럼이 이미 존재합니다.")
            return
        await conn.execute(
            text("ALTER TABLE theme_detection ADD COLUMN verdict VARCHAR(8)")
        )
        print("theme_detection.verdict 컬럼 추가 완료 (기존 행 NULL = 레거시 YES)")


asyncio.run(main())
