"""daily_briefs.risk_flags 컬럼 추가 (재무 리스크 플래그).

create_all은 기존 테이블에 컬럼을 추가하지 않으므로 1회 실행 필요.
    python3 backend/scripts/migrate_add_risk_flags.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.database import engine  # noqa: E402


async def main() -> None:
    async with engine.begin() as conn:
        result = await conn.execute(text("SELECT * FROM daily_briefs LIMIT 0"))
        if "risk_flags" in result.keys():
            print("risk_flags 컬럼이 이미 존재합니다.")
            return
        await conn.execute(text("ALTER TABLE daily_briefs ADD COLUMN risk_flags JSON"))
        print("risk_flags 컬럼 추가 완료")


asyncio.run(main())
