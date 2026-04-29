import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.brief import router as brief_router
from app.api.health import router as health_router
from app.api.internal.theme_scan import router as internal_theme_scan_router
from app.api.stock import router as stock_router
from app.api.watchlist import router as watchlist_router
from app.config import settings
from app.database import init_db
from app.models import (  # noqa: F401
    DailyBrief,
    ThemeScanResult,
    ThemeScanRun,
    Watchlist,
)
from app.services.scheduler import start_scheduler, stop_scheduler
from app.services.telegram_bot import start_polling

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    port = int(os.getenv("PORT", settings.backend_port))
    logger.info("InvestBrief 서버 시작 (port %d)", port)
    await init_db()
    logger.info("DB 초기화 완료")
    start_scheduler()
    bot_task = asyncio.create_task(start_polling())
    yield
    bot_task.cancel()
    stop_scheduler()
    logger.info("InvestBrief 서버 종료")


app = FastAPI(title="InvestBrief", version="0.1.0", lifespan=lifespan)

# CORS — 로컬 + Vercel 프론트엔드 허용
allowed_origins = [
    f"http://localhost:{settings.frontend_port}",
    "http://localhost:3001",
    "http://localhost:3000",
]

# FRONTEND_URL 환경변수로 추가 허용 도메인 주입 (Vercel URL 등)
frontend_url = os.getenv("FRONTEND_URL", "").strip()
if frontend_url:
    allowed_origins.append(frontend_url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(brief_router)
app.include_router(watchlist_router)
app.include_router(stock_router)
app.include_router(internal_theme_scan_router)


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", settings.backend_port))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)