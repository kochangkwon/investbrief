"""관심종목 API 라우터"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors import stock_search
from app.database import get_session
from app.services import watchlist_service

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


class WatchlistCreate(BaseModel):
    stock_code: str
    stock_name: str
    memo: Optional[str] = None


@router.get("")
async def list_watchlist(session: AsyncSession = Depends(get_session)):
    items = await watchlist_service.list_all(session)
    return [
        {
            "id": w.id,
            "stock_code": w.stock_code,
            "stock_name": w.stock_name,
            "memo": w.memo,
            "created_at": w.created_at.isoformat(),
        }
        for w in items
    ]


@router.post("")
async def add_watchlist(body: WatchlistCreate, session: AsyncSession = Depends(get_session)):
    try:
        item = await watchlist_service.add(session, body.stock_code, body.stock_name, body.memo)
        return {"id": item.id, "stock_code": item.stock_code, "stock_name": item.stock_name}
    except Exception:
        raise HTTPException(status_code=409, detail="이미 등록된 종목입니다")


@router.get("/search")
async def search(q: str = "", limit: int = 10):
    """종목 검색"""
    results = await stock_search.search_stocks(q, limit)
    return results


@router.delete("/{stock_code}")
async def remove_watchlist(stock_code: str, session: AsyncSession = Depends(get_session)):
    deleted = await watchlist_service.remove(session, stock_code)
    if not deleted:
        raise HTTPException(status_code=404, detail="등록되지 않은 종목입니다")
    return {"deleted": True}
