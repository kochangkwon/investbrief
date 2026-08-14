"""재무 리스크 플래그 API"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import verify_admin_api_key
from app.database import get_db
from app.services import risk_flags

router = APIRouter(
    prefix="/api/risk-flags",
    tags=["risk-flags"],
    dependencies=[Depends(verify_admin_api_key)],
)


@router.get("/{stock_code}")
async def get_risk_flags(stock_code: str, session: AsyncSession = Depends(get_db)):
    """종목 재무 리스크 플래그 (DART 공시 재무데이터 기반)"""
    return await risk_flags.get_risk_flags(session, stock_code)
