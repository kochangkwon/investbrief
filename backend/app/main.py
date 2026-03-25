import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.brief import router as brief_router
from app.api.health import router as health_router
from app.api.stock import router as stock_router
from app.api.watchlist import router as watchlist_router
from app.config import settings
from app.database import init_db
from app.models import DailyBrief, Watchlist  # noqa: F401
from app.services.scheduler import start_scheduler, stop_scheduler
from app.services.telegram_bot import start_polling

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("InvestBrief 서버 시작 (port %d)", settings.backend_port)
    await init_db()
    logger.info("DB 초기화 완료")
    start_scheduler()
    bot_task = asyncio.create_task(start_polling())
    yield
    bot_task.cancel()
    stop_scheduler()
    logger.info("InvestBrief 서버 종료")


app = FastAPI(title="InvestBrief", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[f"http://localhost:{settings.frontend_port}"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(brief_router)
app.include_router(watchlist_router)
app.include_router(stock_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.backend_port, reload=True)
