"""경제 뉴스 수집 (RSS + 네이버 뉴스 API)"""

import logging
from datetime import datetime
from typing import Any

import feedparser
import httpx

from app.config import settings

logger = logging.getLogger(__name__)

RSS_FEEDS = {
    "한경": "https://www.hankyung.com/feed/economy",
    "매경": "https://www.mk.co.kr/rss/30000001/",
    "서울경제": "https://www.sedaily.com/RSS/Economy",
    "연합뉴스": "https://www.yna.co.kr/rss/economy.xml",
}

NAVER_SEARCH_URL = "https://openapi.naver.com/v1/search/news.json"
SEARCH_KEYWORDS = ["증시", "코스피", "금리", "환율"]


async def _fetch_rss(source: str, url: str) -> list[dict[str, Any]]:
    """단일 RSS 피드 파싱"""
    items = []
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        feed = feedparser.parse(resp.text)
        for entry in feed.entries[:5]:
            items.append({
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "source": source,
                "published": entry.get("published", ""),
            })
    except Exception:
        logger.exception("RSS 수집 실패: %s", source)
    return items


async def _fetch_naver_news(keyword: str) -> list[dict[str, Any]]:
    """네이버 뉴스 검색 API"""
    items = []
    if not settings.naver_client_id:
        return items
    try:
        headers = {
            "X-Naver-Client-Id": settings.naver_client_id,
            "X-Naver-Client-Secret": settings.naver_client_secret,
        }
        params = {"query": keyword, "display": 5, "sort": "date"}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(NAVER_SEARCH_URL, headers=headers, params=params)
            resp.raise_for_status()
        data = resp.json()
        for item in data.get("items", []):
            title = item["title"].replace("<b>", "").replace("</b>", "")
            items.append({
                "title": title,
                "link": item["originallink"],
                "source": "네이버",
                "published": item.get("pubDate", ""),
            })
    except Exception:
        logger.exception("네이버 뉴스 수집 실패: %s", keyword)
    return items


async def get_today_news(limit: int = 20) -> list[dict[str, Any]]:
    """RSS + 네이버 뉴스를 합쳐서 반환"""
    all_items: list[dict[str, Any]] = []

    # RSS 수집
    for source, url in RSS_FEEDS.items():
        items = await _fetch_rss(source, url)
        all_items.extend(items)

    # 네이버 뉴스 수집
    for keyword in SEARCH_KEYWORDS:
        items = await _fetch_naver_news(keyword)
        all_items.extend(items)

    # 제목 기준 중복 제거
    seen_titles: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in all_items:
        if item["title"] not in seen_titles:
            seen_titles.add(item["title"])
            unique.append(item)

    logger.info("뉴스 수집 완료: %d건", len(unique))
    return unique[:limit]
