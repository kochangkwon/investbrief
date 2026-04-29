"""
DB 연결 — SQLite (로컬 개발) + PostgreSQL (Neon / Supabase) 동시 지원

database_url에 따라 자동 분기:
- sqlite+aiosqlite:///./investbrief.db                    → 로컬 개발
- postgresql+asyncpg://...@...neon.tech/...?sslmode=...   → Neon 프로덕션
- postgresql+asyncpg://...pooler.supabase.com:6543/...    → Supabase (호환 유지)

Neon 처리:
- libpq 전용 쿼리 파라미터 (sslmode, channel_binding)는 asyncpg가 인식 못하므로 URL에서 제거
- 대신 connect_args에 ssl 컨텍스트를 명시적으로 주입
"""
import logging
import ssl
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


# ─────────────────────────────────────────────────────────
# URL 정규화 — libpq 전용 파라미터를 asyncpg 호환으로 변환
# ─────────────────────────────────────────────────────────
def _normalize_postgres_url(url: str) -> tuple[str, dict]:
    """
    Neon/Supabase가 주는 URL에서 asyncpg가 모르는 파라미터를 제거하고
    대응되는 connect_args dict를 반환한다.

    제거 대상:
    - sslmode=require / verify-full  → ssl 컨텍스트로 대체
    - channel_binding=require        → asyncpg가 자동 지원
    """
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    connect_args: dict = {}

    # SSL 처리
    sslmode = query.pop("sslmode", [None])[0]
    if sslmode in ("require", "verify-ca", "verify-full"):
        # asyncpg용 SSL 컨텍스트 생성
        ssl_ctx = ssl.create_default_context()
        if sslmode == "require":
            # Neon/Supabase 기본값 — 인증서 검증 없이 암호화만
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
        # verify-ca / verify-full은 기본 설정 유지 (정식 인증서 검증)
        connect_args["ssl"] = ssl_ctx

    # channel_binding은 asyncpg가 자동 협상하므로 제거
    query.pop("channel_binding", None)

    # 재조립된 URL
    new_query = urlencode(query, doseq=True)
    new_url = urlunparse(parsed._replace(query=new_query))

    return new_url, connect_args


# ─────────────────────────────────────────────────────────
# 엔진 생성 — DB 종류에 따라 옵션 자동 조정
# ─────────────────────────────────────────────────────────
_raw_url = settings.database_url
_is_sqlite = _raw_url.startswith("sqlite")
_is_postgres = _raw_url.startswith("postgresql")

engine_kwargs = {
    "echo": False,
    "future": True,
}

if _is_sqlite:
    # SQLite — connection pool 이슈 회피
    engine_kwargs["connect_args"] = {"check_same_thread": False}
    final_url = _raw_url

elif _is_postgres:
    # PostgreSQL (Neon / Supabase) — URL 정규화 + 연결 풀 설정
    final_url, pg_connect_args = _normalize_postgres_url(_raw_url)

    engine_kwargs["pool_size"] = 5
    engine_kwargs["max_overflow"] = 10
    engine_kwargs["pool_pre_ping"] = True    # 끊긴 연결 자동 감지
    engine_kwargs["pool_recycle"] = 1800     # 30분마다 연결 재생성 (Neon 유휴 끊김 방지)

    # Neon/Supabase pgbouncer(pooler) 호환성 옵션
    # prepared statement 캐싱 충돌 방지
    pg_connect_args["statement_cache_size"] = 0
    pg_connect_args["prepared_statement_cache_size"] = 0

    engine_kwargs["connect_args"] = pg_connect_args

else:
    final_url = _raw_url


engine = create_async_engine(final_url, **engine_kwargs)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    """테이블 자동 생성 (Neon에 최초 1회, 이후엔 IF NOT EXISTS로 skip)"""
    # 모델 import 보장 (Base.metadata에 등록되도록)
    from app.models import (  # noqa: F401
        DailyBrief,
        ThemeScanResult,
        ThemeScanRun,
        Watchlist,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    if _is_sqlite:
        db_type = "SQLite"
    elif "neon.tech" in _raw_url:
        db_type = "PostgreSQL (Neon)"
    elif "supabase" in _raw_url:
        db_type = "PostgreSQL (Supabase)"
    else:
        db_type = "PostgreSQL"
    logger.info(f"DB 초기화 완료 ({db_type})")


async def get_db() -> AsyncSession:
    """FastAPI 의존성 주입용"""
    async with async_session() as session:
        yield session

# 호환성 alias — API 레이어의 get_session() 호출 대응
get_session = get_db

