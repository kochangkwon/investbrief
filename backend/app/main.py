import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.brief import router as brief_router
from app.api.health import router as health_router
from app.api.internal.theme_scan import router as internal_theme_scan_router
from app.api.risk_flags import router as risk_flags_router
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

    # KRX 자격증명을 os.environ에 주입 — pykrx 서브프로세스 워커가 상속해 로그인.
    # launchd 기동 프로세스는 셸 환경을 상속하지 않으므로 이 연결이 없으면 수급이 죽는다.
    for _k, _v in (("KRX_ID", settings.krx_id), ("KRX_PW", settings.krx_pw)):
        if _v and not os.getenv(_k):
            os.environ[_k] = _v
    logger.info(
        "KRX 자격증명: %s",
        "설정됨" if settings.krx_id and settings.krx_pw else "누락",
    )
    # 비밀번호 수명 추적 — data.krx.co.kr 는 90일마다 변경 강제(CD010). 2026-10-01 만료로
    # 수급이 5거래일 네이버 폴백에 빠졌던 재발 방지: 80일째부터 브리프 후 알림.
    try:
        from app.collectors.investor_flow_collector import record_krx_password_fingerprint
        record_krx_password_fingerprint(settings.krx_pw)
    except Exception:
        logger.warning("KRX 비밀번호 지문 기록 실패", exc_info=True)

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
app.include_router(risk_flags_router)
app.include_router(internal_theme_scan_router)


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", settings.backend_port))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)