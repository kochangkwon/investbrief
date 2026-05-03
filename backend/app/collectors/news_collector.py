"""경제 뉴스 수집 (RSS + 네이버 뉴스 API)"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from email.utils import parsedate_to_datetime
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


async def _fetch_naver_news(keyword: str, display: int = 10) -> list[dict[str, Any]]:
    """네이버 뉴스 검색 API"""
    items = []
    if not settings.naver_client_id:
        return items
    try:
        headers = {
            "X-Naver-Client-Id": settings.naver_client_id,
            "X-Naver-Client-Secret": settings.naver_client_secret,
        }
        params = {"query": f'"{keyword}"', "display": display, "sort": "date"}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(NAVER_SEARCH_URL, headers=headers, params=params)
            resp.raise_for_status()
        data = resp.json()
        for item in data.get("items", []):
            title = item["title"].replace("<b>", "").replace("</b>", "")
            desc = re.sub(r"<[^>]+>", "", item.get("description", ""))
            items.append({
                "title": title,
                "description": desc[:200],
                "link": item["originallink"],
                "source": "네이버",
                "published": item.get("pubDate", ""),
            })
    except Exception:
        logger.exception("네이버 뉴스 수집 실패: %s", keyword)
    return items


def _parse_pub_date(value: str) -> date | None:
    """RFC 822 / ISO 형식의 pubDate를 date로 변환"""
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).date()
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


async def get_today_news(
    limit: int = 20, target_date: date | None = None
) -> list[dict[str, Any]]:
    """RSS + 네이버 뉴스를 합쳐서 반환

    target_date가 지정되면 해당 일자에 발행된 뉴스만 필터링 (백필용).
    네이버 검색 API 결과의 pubDate를 기준으로 클라이언트 측 필터링.
    RSS는 historical 보존이 보장되지 않아 today일 때만 사용.
    """
    all_items: list[dict[str, Any]] = []
    is_today = target_date is None or target_date == date.today()

    # RSS 수집 (today일 때만 사용)
    if is_today:
        for source, url in RSS_FEEDS.items():
            items = await _fetch_rss(source, url)
            all_items.extend(items)

    # 네이버 뉴스 수집 (백필 시에는 페이지를 더 받아서 날짜 필터링)
    display = 10 if is_today else 100
    for keyword in SEARCH_KEYWORDS:
        items = await _fetch_naver_news(keyword, display=display)
        all_items.extend(items)

    # target_date 기준 pubDate 필터링
    if target_date is not None:
        filtered: list[dict[str, Any]] = []
        for item in all_items:
            pub_date = _parse_pub_date(item.get("published", ""))
            if pub_date == target_date:
                filtered.append(item)
        all_items = filtered

    # 제목 기준 중복 제거
    seen_titles: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in all_items:
        if item["title"] not in seen_titles:
            seen_titles.add(item["title"])
            unique.append(item)

    logger.info("뉴스 수집 완료: %d건 (target=%s)", len(unique), target_date or "today")
    return unique[:limit]
