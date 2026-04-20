"""
SQLite → Neon PostgreSQL 1회성 마이그레이션 스크립트

실행 전 확인사항:
1. Neon에 테이블이 이미 생성되어 있어야 함 (init_db로 자동 생성 완료 상태)
2. backend/investbrief.db 파일 존재 확인
3. .env의 DATABASE_URL이 Neon URL이어야 함

실행:
    cd backend
    python3 scripts/migrate_sqlite_to_neon.py
"""
import asyncio
import os
import ssl
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

# backend/ 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.models import DailyBrief, Watchlist


# ─────────────────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────────────────
SQLITE_URL = "sqlite+aiosqlite:///./investbrief.db"
NEON_URL = settings.database_url

if not NEON_URL.startswith("postgresql"):
    print(f"❌ .env의 DATABASE_URL이 PostgreSQL이 아닙니다: {NEON_URL[:30]}...")
    print("   Neon URL로 설정된 상태에서 이 스크립트를 실행하세요.")
    sys.exit(1)

# SQLite 파일 존재 확인
sqlite_file = Path("investbrief.db")
if not sqlite_file.exists():
    print(f"❌ SQLite 파일이 없습니다: {sqlite_file.absolute()}")
    sys.exit(1)

print(f"📂 Source: {SQLITE_URL}")
print(f"🎯 Target: Neon (ap-southeast-1)")
print()


# ─────────────────────────────────────────────────────────
# Neon용 SSL 설정
# ─────────────────────────────────────────────────────────
def _normalize_pg_url(url: str):
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    connect_args = {}
    sslmode = query.pop("sslmode", [None])[0]
    if sslmode in ("require", "verify-ca", "verify-full"):
        ssl_ctx = ssl.create_default_context()
        if sslmode == "require":
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
        connect_args["ssl"] = ssl_ctx
    query.pop("channel_binding", None)
    new_query = urlencode(query, doseq=True)
    new_url = urlunparse(parsed._replace(query=new_query))
    connect_args["statement_cache_size"] = 0
    connect_args["prepared_statement_cache_size"] = 0
    return new_url, connect_args


# ─────────────────────────────────────────────────────────
# 마이그레이션 대상 모델
# ─────────────────────────────────────────────────────────
MIGRATION_MODELS = [
    Watchlist,
    DailyBrief,
]


async def migrate():
    """SQLite → Neon 데이터 복사"""
    # 양쪽 엔진 생성
    src_engine = create_async_engine(SQLITE_URL, echo=False)

    neon_url, neon_connect_args = _normalize_pg_url(NEON_URL)
    dst_engine = create_async_engine(
        neon_url,
        echo=False,
        connect_args=neon_connect_args,
    )

    src_session = async_sessionmaker(src_engine, class_=AsyncSession, expire_on_commit=False)
    dst_session = async_sessionmaker(dst_engine, class_=AsyncSession, expire_on_commit=False)

    try:
        for model in MIGRATION_MODELS:
            table_name = model.__tablename__
            print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            print(f"📋 Table: {table_name}")

            # 1. SQLite에서 조회
            async with src_session() as src_db:
                result = await src_db.execute(select(model))
                rows = result.scalars().all()
                print(f"   SQLite에서 {len(rows)}개 행 조회됨")

            if not rows:
                print(f"   ⏭  스킵 (데이터 없음)")
                continue

            # 2. Neon 테이블 비우기 (중복 방지)
            async with dst_session() as dst_db:
                await dst_db.execute(
                    text(f"TRUNCATE TABLE {table_name} RESTART IDENTITY CASCADE")
                )
                await dst_db.commit()
                print(f"   🧹 Neon 테이블 비움")

            # 3. Neon에 삽입
            async with dst_session() as dst_db:
                for row in rows:
                    row_dict = {
                        c.name: getattr(row, c.name)
                        for c in model.__table__.columns
                    }
                    new_row = model(**row_dict)
                    dst_db.add(new_row)

                await dst_db.commit()
                print(f"   ✅ Neon에 {len(rows)}개 행 삽입 완료")

            # 4. Sequence 재조정 (auto-increment ID 보정)
            async with dst_session() as dst_db:
                try:
                    pk_col = list(model.__table__.primary_key.columns.values())[0].name
                    seq_name = f"{table_name}_{pk_col}_seq"
                    await dst_db.execute(
                        text(
                            f"SELECT setval('{seq_name}', "
                            f"COALESCE((SELECT MAX({pk_col}) FROM {table_name}), 1))"
                        )
                    )
                    await dst_db.commit()
                    print(f"   🔧 Sequence 재조정 완료")
                except Exception as e:
                    print(f"   ⚠️  Sequence 재조정 실패 (수동 확인 필요): {e}")

        print()
        print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"🎉 마이그레이션 완료!")

    finally:
        await src_engine.dispose()
        await dst_engine.dispose()


if __name__ == "__main__":
    asyncio.run(migrate())
