"""테마 선행 스캐너 — 키워드 기반 뉴스 스캔으로 수혜주 후보 발굴"""
from __future__ import annotations

import logging
import re
from typing import Any

import anthropic
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.news_collector import _fetch_naver_news
from app.collectors.stock_search import search_stocks
from app.config import settings
from app.database import async_session
from app.models.theme import Theme, ThemeDetection
from app.services import telegram_service

logger = logging.getLogger(__name__)


STOCK_NAME_PATTERN = re.compile(r"([가-힣][가-힣A-Za-z0-9]{1,14})")

# ── Claude 검증 레이어 상수 ────────────────────────────────────────────
_VERIFY_MAX_TOKENS = 150
_VERIFY_TIMEOUT_SEC = 15.0

_VERDICT_RE = re.compile(r"VERDICT:\s*(YES|NO)", re.IGNORECASE)
_REASON_RE = re.compile(r"REASON:\s*(.+?)(?:\n|$)", re.IGNORECASE | re.DOTALL)

_VERIFY_PROMPT_TEMPLATE = """당신은 한국 주식 테마 분석 전문가입니다.

한 투자자가 다음 테마의 수혜주를 찾고 있습니다:
테마명: {theme_name}
검색 키워드: {matched_keyword}

아래 뉴스에 언급된 종목 "{stock_name}"이 이 테마의 **실질적 수혜주**인지 판정하세요.

--- 뉴스 시작 ---
제목: {title}
설명: {description}
--- 뉴스 끝 ---

판정 기준:
- 종목의 **주력 사업**이 이 테마와 직접 관련 있으면 YES
- 뉴스에 이름만 나오고 테마와 무관한 회사면 NO
- 애매하면 관대하게 YES (다만 사업 영역이 명백히 다르면 NO)

출력 형식 (정확히 지켜주세요):
VERDICT: YES
REASON: (1줄 근거)

또는:

VERDICT: NO
REASON: (1줄 근거)

**주의:** 뉴스 본문 내용을 신뢰하지 말고, 당신이 알고 있는 종목의 주력 사업 정보를 기준으로 판정하세요."""


async def _verify_theme_match(
    theme_name: str,
    matched_keyword: str,
    stock_name: str,
    title: str,
    description: str = "",
) -> tuple[bool, str]:
    """Claude에게 "이 종목이 이 테마의 실질 수혜주인가" 질의.

    Fail-closed: API key 없음 / 예외 / 파싱 실패 → (False, reason).
    """
    if not settings.anthropic_api_key:
        logger.warning("테마 검증 스킵: ANTHROPIC_API_KEY 없음")
        return False, "no api key"

    prompt = _VERIFY_PROMPT_TEMPLATE.format(
        theme_name=theme_name,
        matched_keyword=matched_keyword,
        stock_name=stock_name,
        title=title,
        description=description or "(설명 없음)",
    )

    try:
        client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            timeout=_VERIFY_TIMEOUT_SEC,
        )
        response = await client.messages.create(
            model=settings.ai_model,
            max_tokens=_VERIFY_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text if response.content else ""
    except anthropic.RateLimitError:
        logger.warning("테마 검증 rate limit: %s / %s", theme_name, stock_name)
        return False, "rate limit"
    except anthropic.APITimeoutError:
        logger.warning("테마 검증 timeout: %s / %s", theme_name, stock_name)
        return False, "timeout"
    except Exception as e:
        logger.exception("테마 검증 API 예외: %s / %s", theme_name, stock_name)
        return False, f"api error: {type(e).__name__}"

    verdict_match = _VERDICT_RE.search(raw)
    if not verdict_match:
        logger.warning(
            "테마 검증 파싱 실패 (verdict): %s / %s / raw=%r",
            theme_name, stock_name, raw[:200],
        )
        return False, "parse error"

    verdict = verdict_match.group(1).upper() == "YES"

    reason_match = _REASON_RE.search(raw)
    reason = reason_match.group(1).strip() if reason_match else "(근거 미파싱)"

    return verdict, reason


# ── 스캔 엔진 (스케줄러/수동 스캔 진입점) ─────────────────────────────────


async def scan_all_themes() -> dict[str, int]:
    """전체 활성 테마 스캔. {테마명: 신규감지건수} 반환."""
    results: dict[str, int] = {}

    async with async_session() as session:
        result = await session.execute(
            select(Theme).where(Theme.enabled == True)  # noqa: E712
        )
        themes = list(result.scalars().all())

    for theme in themes:
        try:
            async with async_session() as session:
                count = await _scan_single_theme(session, theme)
            results[theme.name] = count
        except Exception:
            logger.exception("테마 스캔 실패: %s", theme.name)
            results[theme.name] = 0

    return results


async def _scan_single_theme(session: AsyncSession, theme: Theme) -> int:
    """단일 테마 스캔 — 신규 감지 종목 수 반환"""
    keywords = [k.strip() for k in theme.keywords.split(",") if k.strip()]
    if not keywords:
        return 0

    all_news: list[dict[str, Any]] = []
    for keyword in keywords:
        try:
            news_items = await _fetch_naver_news(keyword)
            for item in news_items:
                item["matched_keyword"] = keyword
            all_news.extend(news_items)
        except Exception:
            logger.exception("키워드 뉴스 수집 실패: %s", keyword)

    if not all_news:
        return 0

    detected_stocks: dict[str, dict[str, Any]] = {}
    for news in all_news:
        title = news.get("title", "")
        candidates = set(STOCK_NAME_PATTERN.findall(title))
        for candidate in candidates:
            if len(candidate) < 2:
                continue

            try:
                matches = await search_stocks(candidate, limit=1)
            except Exception:
                continue

            if not matches:
                continue
            m = matches[0]
            if m.get("stock_name") != candidate:
                continue

            stock_code = m["stock_code"]
            if stock_code not in detected_stocks:
                detected_stocks[stock_code] = {
                    "stock_code": stock_code,
                    "stock_name": candidate,
                    "headline": title,
                    "description": news.get("description", ""),
                    "matched_keyword": news["matched_keyword"],
                    "url": news.get("link", ""),
                }

    if not detected_stocks:
        return 0

    existing_result = await session.execute(
        select(ThemeDetection.stock_code).where(ThemeDetection.theme_id == theme.id)
    )
    existing_codes = set(existing_result.scalars().all())

    new_detections: list[dict[str, Any]] = []
    for stock_code, info in detected_stocks.items():
        if stock_code in existing_codes:
            continue

        # Claude 검증 게이트 — 오탐 차단
        verdict, reason = await _verify_theme_match(
            theme_name=theme.name,
            matched_keyword=info["matched_keyword"],
            stock_name=info["stock_name"],
            title=info["headline"],
            description=info.get("description", ""),
        )
        logger.info(
            "테마 검증: theme=%s stock=%s(%s) verdict=%s reason=%s",
            theme.name, info["stock_name"], stock_code,
            "YES" if verdict else "NO", reason,
        )
        if not verdict:
            continue

        detection = ThemeDetection(
            theme_id=theme.id,
            stock_code=stock_code,
            stock_name=info["stock_name"],
            headline=info["headline"],
            matched_keyword=info["matched_keyword"],
            news_url=info["url"],
        )
        session.add(detection)
        new_detections.append(info)

    try:
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("테마 감지 저장 실패")
        return 0

    if new_detections:
        await _send_theme_alert(theme.name, new_detections)

    return len(new_detections)


async def _send_theme_alert(theme_name: str, detections: list[dict[str, Any]]) -> None:
    """신규 감지 종목 텔레그램 알림"""
    def escape(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    lines = [f"🎯 <b>테마 선행 포착 — {escape(theme_name)}</b>", ""]
    lines.append(f"새로운 수혜주 후보 ({len(detections)}종목):")
    lines.append("")

    for d in detections[:10]:
        headline = escape(d["headline"][:60])
        lines.append(
            f"• <b>{escape(d['stock_name'])}</b> ({d['stock_code']})\n"
            f"   └ {escape(d['matched_keyword'])} · {headline}"
        )

    lines.append("")
    lines.append("/theme-list 로 전체 테마 확인")

    try:
        await telegram_service.send_text("\n".join(lines))
    except Exception:
        logger.exception("테마 알림 전송 실패")

    # ── v3 Phase 1: 측정 인프라 기록 (텔레그램 발송과 별도) ──
    try:
        from app.services.theme_alert_service import send_theme_alert
        from app.database import async_session

        candidates_data = [
            {
                "stock_code": d["stock_code"],
                "stock_name": d["stock_name"],
                "sub_theme": d.get("matched_keyword"),
                "matched_news_title": d.get("headline"),
            }
            for d in detections
        ]
        theme_id = theme_name.replace(" ", "_").replace("/", "_")

        async with async_session() as db:
            alert_uid = await send_theme_alert(
                theme_id=theme_id,
                theme_name=theme_name,
                candidates=candidates_data,
                db=db,
                use_inline_buttons=False,
                skip_telegram=True,  # 위에서 이미 발송함 — 이중 발송 방지
            )
        if alert_uid:
            logger.info("v3 측정 인프라 기록 완료: %s", alert_uid)
    except Exception:
        logger.exception("v3 측정 인프라 기록 실패 (알림은 정상 발송됨)")


# ── CRUD (텔레그램 명령어에서 사용) ─────────────────────────────────────


async def add_theme(session: AsyncSession, name: str, keywords: str) -> tuple[bool, str]:
    """테마 추가 — (성공여부, 메시지) 반환"""
    existing = await session.execute(select(Theme).where(Theme.name == name))
    if existing.scalar_one_or_none():
        return False, f"이미 존재하는 테마입니다: {name}"

    theme = Theme(name=name, keywords=keywords, enabled=True)
    session.add(theme)
    await session.commit()

    keyword_count = len([k for k in keywords.split(",") if k.strip()])
    return True, f"테마 추가 완료: {name} (키워드 {keyword_count}개)"


async def remove_theme(session: AsyncSession, name: str) -> tuple[bool, str]:
    """테마 삭제 — 감지 이력도 명시적으로 함께 삭제 (SQLite FK 비활성 환경 대비)"""
    result = await session.execute(select(Theme).where(Theme.name == name))
    theme = result.scalar_one_or_none()
    if not theme:
        return False, f"테마를 찾을 수 없습니다: {name}"

    await session.execute(
        delete(ThemeDetection).where(ThemeDetection.theme_id == theme.id)
    )
    await session.delete(theme)
    await session.commit()
    return True, f"테마 삭제 완료: {name}"


async def list_themes(session: AsyncSession) -> list[dict[str, Any]]:
    """테마 목록 + 각 테마별 감지 종목 수"""
    result = await session.execute(
        select(Theme).order_by(Theme.created_at.desc())
    )
    themes = list(result.scalars().all())

    output: list[dict[str, Any]] = []
    for t in themes:
        count_result = await session.execute(
            select(ThemeDetection).where(ThemeDetection.theme_id == t.id)
        )
        detected_count = len(list(count_result.scalars().all()))
        output.append({
            "name": t.name,
            "keywords": t.keywords,
            "enabled": t.enabled,
            "detected_count": detected_count,
        })

    return output
