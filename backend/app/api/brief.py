"""브리프 API 라우터"""

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException

logger = logging.getLogger(__name__)
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.services import brief_service, telegram_service

router = APIRouter(prefix="/api/brief", tags=["brief"])


@router.get("/today")
async def get_today_brief(session: AsyncSession = Depends(get_session)):
    brief = await brief_service.get_brief_by_date(session, date.today())
    if not brief:
        raise HTTPException(status_code=404, detail="오늘의 브리프가 아직 생성되지 않았습니다")
    return brief


@router.get("/list")
async def list_briefs(days: int = 7, session: AsyncSession = Depends(get_session)):
    return await brief_service.get_recent_briefs(session, days)


@router.get("/{brief_date}")
async def get_brief(brief_date: date, session: AsyncSession = Depends(get_session)):
    brief = await brief_service.get_brief_by_date(session, brief_date)
    if not brief:
        raise HTTPException(status_code=404, detail="해당 날짜의 브리프가 없습니다")
    return brief


@router.post("/generate")
async def generate_brief(
    target_date: date | None = None,
    send: bool = True,
    session: AsyncSession = Depends(get_session),
):
    """수동 브리프 생성 — 기존 브리프가 있으면 삭제 후 재생성

    - target_date: 백필할 날짜 (미지정 시 오늘)
    - send: 텔레그램 발송 여부 (백필 시 false 권장)
    """
    brief_date = target_date or date.today()
    existing = await brief_service.get_brief_by_date(session, brief_date)
    if existing:
        await session.delete(existing)
        await session.commit()
        logger.info("기존 브리프 삭제 (id=%s, date=%s)", existing.id, existing.date)
    brief = await brief_service.generate_daily_brief(session, target_date=target_date)
    if send:
        await telegram_service.send_brief(brief)
    return brief
