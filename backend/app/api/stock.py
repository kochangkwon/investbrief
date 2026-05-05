"""종목별 뉴스/공시 API"""
from __future__ import annotations

from fastapi import APIRouter

from app.collectors import dart_collector, news_collector

router = APIRouter(prefix="/api/stock", tags=["stock"])


@router.get("/{stock_code}/news")
async def get_stock_news(stock_code: str, stock_name: str = ""):
    """종목별 뉴스 검색"""
    keyword = stock_name or stock_code
    items = await news_collector._fetch_naver_news(keyword)
    return items[:10]


@router.get("/{stock_code}/dart")
async def get_stock_dart(stock_code: str):
    """종목별 당일 공시"""
    all_disclosures = await dart_collector.get_today_disclosures()
    matched = [d for d in all_disclosures if d.get("stock_code") == stock_code]
    return matched
