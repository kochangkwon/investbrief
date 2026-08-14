"""테마 선행 스캐너 — 키워드 기반 뉴스 스캔으로 수혜주 후보 발굴"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.news_collector import _fetch_naver_news, _parse_pub_datetime
from app.collectors.stock_search import search_stocks
from app.config import settings
from app.database import async_session
from app.models.theme import (
    Theme,
    ThemeDetection,
    ThemeFeatureSnapshot,
    ThemeScanResult,
    ThemeScanRun,
)
from app.services import ai_verifier, telegram_service
from app.services.prefilter_service import PrefilterResult, prefilter_stocks
from app.services.stock_name_rules import GROUP_PREFIX_NAMES, STOPWORDS
from app.services.verify_prompts import build_theme_verify_prompt
from app.utils.timezone import now_kst, now_kst_naive

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")


# 종목명 추출 정규식
# - 영문/한글 시작 모두 허용 (LG, SK, HD, KT&G, POSCO 등 대형주 매칭)
# - 후속 글자: 영문/한글/숫자/& (KT&G, F&F 등)
# - 길이 2~15자 (한 글자 단어 후속 처리에서 제외)
STOCK_NAME_PATTERN = re.compile(r"([A-Za-z가-힣][A-Za-z가-힣0-9&]{1,14})")

# 한글 조사 — 토큰 끝에 붙으면 종목명이 아닐 가능성 높음
_JOSA_SUFFIXES = (
    "으로", "에서", "에게", "에는", "에도", "이라", "라고", "하며", "하면서",
    "지만", "보다", "처럼", "까지", "부터", "이라는", "라는", "하는", "되는",
)

# 한 글자 조사 — 오탐 위험 커서 len >= 4 에서만 차단 (짧은 종목명 보호)
_JOSA_SINGLE = ("에", "은", "는", "이", "가", "을", "를", "의", "와", "과", "도", "로")

# HTML 엔티티 잔재
_HTML_JUNK = {"quot", "amp", "lt", "gt", "nbsp", "apos"}


def _is_noise_token(token: str) -> bool:
    """네이버 AC 호출 전 명백한 노이즈를 쳐낸다.

    True면 후보에서 제외(네이버 호출 안 함). 보수적 — 애매하면 False(통과).
    정확일치 필터가 뒤에 있으므로 약간 새도 최종 결과는 안전.
    목적은 "최종 판정"이 아니라 "불필요한 네이버 호출 절약".
    """
    if token.lower() in _HTML_JUNK:                       # HTML 잔재
        return True
    if any(ch.isdigit() for ch in token):                 # 숫자 포함 (금액/수치)
        return True
    if token.endswith(("원", "원으로", "억원", "달러", "달러를", "퍼센트")):  # 금액 단위
        return True
    if len(token) >= 3 and token.endswith(_JOSA_SUFFIXES):  # 조사로 끝남 (3자 이상만)
        return True
    if len(token) >= 4 and token.endswith(_JOSA_SINGLE):    # 한 글자 조사 (4자+)
        return True
    return False


_ac_cache: dict[str, list] = {}   # 종목명 → search_stocks 결과 (스캔 1회 수명)

# 상장사명 화이트리스트 (stock_corp_map corp_name — 스캔 시작 시 로드).
# _is_noise_token의 조사/숫자/금액단위 규칙이 실제 상장사(에코프로·쎄트렉아이·
# LG디스플레이·대원 등 64+개)를 영구 차단하던 문제를 해소한다:
# 화이트리스트에 있는 토큰은 노이즈 규칙을 건너뛴다 (STOPWORDS/GROUP은 별도).
_listed_names: set[str] = set()


async def _load_listed_names() -> None:
    """stock_corp_map에서 상장사명 집합을 로드 (스캔 1회 수명)."""
    global _listed_names
    try:
        from app.models.fundamental_cache import StockCorpMap
        async with async_session() as session:
            result = await session.execute(select(StockCorpMap.corp_name))
            _listed_names = {n for n in result.scalars().all() if n}
        logger.info("[radar] 상장사명 화이트리스트 로드: %d건", len(_listed_names))
    except Exception:
        logger.exception("[radar] 상장사명 로드 실패 — 화이트리스트 없이 진행")
        _listed_names = set()


def _dynamic_freshness_hours(base_hours: int, gap_days: Optional[int], weekday: int) -> int:
    """신선도 시간 계산 (순수 함수, P3-3).

    직전 스캔일과의 갭이 있으면 gap_days×24h까지 확장 — 주말(월요일 gap=3
    →72h)뿐 아니라 화요일 공휴일 뒤 수요일 등 연휴도 자동 커버.
    갭 정보가 없으면(DB 실패 등) 기존 월요일 72h 규칙으로 폴백.
    """
    if base_hours <= 0:
        return base_hours
    if gap_days is not None and gap_days >= 1:
        return max(base_hours, min(gap_days, 7) * 24)
    if weekday == 0:   # 폴백: 월요일 주말분
        return max(base_hours, 72)
    return base_hours


async def _days_since_last_scan_run() -> Optional[int]:
    """오늘 이전 마지막 completed 스캔일과의 갭(일). 조회 실패 시 None."""
    try:
        from sqlalchemy import func as sa_func
        today = now_kst().date()
        async with async_session() as session:
            last = await session.scalar(
                select(sa_func.max(ThemeScanRun.scan_date))
                .where(ThemeScanRun.scan_date < today)
                .where(ThemeScanRun.status == "completed")
            )
        return (today - last).days if last else None
    except Exception:
        logger.warning("[radar] 직전 스캔일 조회 실패 — 신선도 폴백", exc_info=True)
        return None


def _group_prefix_is_noise(candidate: str, text: str) -> bool:
    """그룹명 단독 토큰이 지주사 오탐인지 판정 (순수 함수).

    같은 뉴스 텍스트에 그 그룹명으로 시작하는 더 긴 토큰(계열사명)이
    함께 등장하면 — 예: "한화에어로스페이스 수주 ... 한화" — 그룹명 단독
    토큰은 계열사 언급의 잘린 조각일 가능성이 높으므로 차단(True).
    계열사 동반 없이 단독 등장하면 통과시켜 Claude 검증(지주사 NO 조건)에
    위임한다 — 신세계·오리온·대상 등 사업회사 본체 복구 목적.
    """
    for token in STOCK_NAME_PATTERN.findall(text):
        if token != candidate and token.startswith(candidate):
            return True
    return False


async def _cached_search_stocks(name: str):
    if name in _ac_cache:
        return _ac_cache[name]
    result = await search_stocks(name, limit=1)
    _ac_cache[name] = result
    return result

# ThemeDetection 중복 검증 윈도우 (일).
# 같은 종목을 이 기간 이내 다시 검증하지 않는다 (Claude API 비용 절약).
# 윈도우가 지나면 다시 검증 → 폭등 후 정상화된 종목을 매수 적기에 재검출.
DETECTION_WINDOW_DAYS = 14

# NO 판정 재검증 윈도우 (일) — YES(14일)보다 짧게. 같은 이슈로 매일
# 재검증하던 비용을 줄이되, 새 재료가 나오면 빠르게 재평가한다.
NO_VERDICT_WINDOW_DAYS = 3

# 스캔 1회 실행 통계 (스케줄러가 완료 메시지에 표기).
# verify_failed: rate limit/timeout/파싱 실패로 "미판정" 처리된 후보 수.
last_scan_stats: dict[str, int] = {"verify_failed": 0}

# 본문 추출 도입 시 candidate 폭증 방지 (Claude 검증 비용 통제). 헤드라인 매칭 우선.
MAX_CANDIDATES_PER_THEME = 30

# ── Claude 검증 레이어 ─────────────────────────────────────────────────
# 프롬프트는 verify_prompts.build_theme_verify_prompt(빌더)로 통합, 호출/파싱은
# ai_verifier.verify_theme_with_claude로 위임 (VERDICT+MATERIALITY+REASON).

PROMPT_VERSION = "v2"  # 지시서 F: 신선도+materiality 적용 버전 태그


async def _verify_theme_match(
    theme_name: str,
    matched_keyword: str,
    stock_name: str,
    title: str,
    description: str = "",
    pub_date_str: Optional[str] = None,
) -> tuple[Optional[bool], Optional[str], str]:
    """Claude에게 "이 종목이 이 테마의 실질 수혜주인가 + 재료 중요도" 질의.

    Returns (verdict, materiality, reason):
    - verdict True/False: 정상 판정
    - verdict None: 검증 실패(API key 없음/rate limit/timeout/파싱 실패).
      호출측이 "미판정"으로 처리한다 — NO로 강등하면 일시 장애가 그날
      감지 전체를 조용히 소거하므로, 기록하지 않고 다음 스캔에서 재시도.
    """
    prompt = build_theme_verify_prompt(
        theme_name=theme_name,
        matched_keyword=matched_keyword,
        stock_name=stock_name,
        title=title,
        description=description,
        pub_date_str=pub_date_str,
    )
    return await ai_verifier.verify_theme_with_claude(
        prompt,
        log_context=f"theme={theme_name} stock={stock_name}",
    )


def _order_articles(info: dict[str, Any]) -> list[dict[str, Any]]:
    """종목의 기사들을 검증 우선순위로 정렬 (순수 함수, P3-2).

    우선순위: ① 제목에 종목명 포함 ② pub_date 최신 ("YYYY-MM-DD HH:MM"
    문자열 비교, None은 최후). 첫 원소가 대표 기사.
    """
    main = {
        "headline": info.get("headline", ""),
        "description": info.get("description", ""),
        "matched_keyword": info.get("matched_keyword", ""),
        "url": info.get("url", ""),
        "pub_date": info.get("pub_date"),
    }
    articles = [main] + list(info.get("alt_news") or [])
    name = info.get("stock_name", "")
    # 안정 정렬 2단계: pub_date 내림차순 → 종목명 포함 우선
    articles.sort(key=lambda a: a.get("pub_date") or "", reverse=True)
    articles.sort(key=lambda a: 0 if (name and name in (a.get("headline") or "")) else 1)
    return articles


# ── 스캔 엔진 (스케줄러/수동 스캔 진입점) ─────────────────────────────────


def _find_multi_theme_titles(theme_title_map: dict[Any, set[str]]) -> set[str]:
    """복수 테마에 동시 매칭된 뉴스 제목 집합을 반환 (순수 함수)."""
    counts: dict[str, int] = {}
    for titles in theme_title_map.values():
        for title in titles:           # 테마별 set → 같은 테마 내 중복은 이미 1회
            if not title:
                continue
            counts[title] = counts.get(title, 0) + 1
    return {title for title, c in counts.items() if c >= 2}


# P3-1: 광범위 기사 마커 — 복수 테마 매칭 + 이 마커 포함이면 전 테마 차단.
# (기존 "복수 매칭 = 전량 차단"은 HBM 대형 수주처럼 강한 재료일수록 여러
#  테마에 걸려 버려지는 역선택이었다 — 마커 없는 복수 매칭은 대표 테마 배정)
_BROAD_ARTICLE_MARKERS = (
    "관련주", "수혜주", "대장주", "테마주", "목표주가",
    "추천주", "유망주", "정리", "총정리", "리포트",
)


def _find_banned_broad_titles(theme_title_map: dict[Any, set[str]]) -> set[str]:
    """복수 테마 매칭 AND 광범위 마커 포함 제목 → 전 테마 차단 (순수 함수)."""
    multi = _find_multi_theme_titles(theme_title_map)
    return {
        t for t in multi
        if any(marker in t for marker in _BROAD_ARTICLE_MARKERS)
    }


def _assign_primary_theme(
    title_kw_counts: dict[str, dict[Any, int]],
    banned_titles: set[str],
) -> dict[str, Any]:
    """마커 없는 복수 테마 매칭 제목 → 대표 테마 1개 배정 (순수 함수).

    대표 = 그 제목이 매칭한 키워드 수가 가장 많은 테마. 동률이면 theme_id
    낮은 쪽 (결정론적). 단일 테마 제목·차단 제목은 배정하지 않는다.
    """
    primary: dict[str, Any] = {}
    for title, per_theme in title_kw_counts.items():
        if not title or title in banned_titles or len(per_theme) < 2:
            continue
        best = max(per_theme.items(), key=lambda kv: (kv[1], -_orderable(kv[0])))
        primary[title] = best[0]
    return primary


def _orderable(theme_id: Any) -> int:
    """theme_id를 동률 비교용 정수로 (int가 아니면 hash 폴백)."""
    try:
        return int(theme_id)
    except (TypeError, ValueError):
        return hash(theme_id)


def _build_title_kw_counts(
    theme_news_map: dict[Any, list[dict[str, Any]]],
) -> dict[str, dict[Any, int]]:
    """제목 → {theme_id: 매칭된 고유 키워드 수} (순수 함수)."""
    out: dict[str, dict[Any, set]] = {}
    for tid, news in theme_news_map.items():
        for n in news:
            title = n.get("title") or ""
            kw = n.get("matched_keyword")
            if not title or not kw:
                continue
            out.setdefault(title, {}).setdefault(tid, set()).add(kw)
    return {
        title: {tid: len(kws) for tid, kws in per.items()}
        for title, per in out.items()
    }


async def _gather_theme_news(theme: Theme) -> list[dict[str, Any]]:
    """테마 키워드로 신선한 뉴스만 수집 (검증 전 단계 — 교차 테마 가드 입력).

    _scan_single_theme의 뉴스 수집부를 분리한 것. 반환 리스트는 그대로
    _scan_single_theme에 재사용되므로 스캔 1회당 중복 fetch가 없다.
    """
    keywords = [k.strip() for k in theme.keywords.split(",") if k.strip()]
    if not keywords:
        return []

    # 신선도 기준: 직전 스캔일 갭 기반 동적 확장 (P3-3 — 연휴 자동 커버).
    # 0이면 필터 무효. DB 조회 실패 시 월요일 72h 규칙 폴백.
    freshness_hours = settings.theme_news_freshness_hours
    if freshness_hours > 0:
        gap_days = await _days_since_last_scan_run()
        freshness_hours = _dynamic_freshness_hours(
            freshness_hours, gap_days, now_kst().weekday(),
        )
    now = now_kst()

    all_news: list[dict[str, Any]] = []
    fresh_count = 0
    stale_dropped = 0
    for keyword in keywords:
        try:
            # display=30: 기본 10건이면 활발한 키워드(HBM 등)는 최신 몇 시간치만
            # 커버되어 전일 장중 재료가 유실됨 — 신선도 필터(24h)를 채울 만큼 수집.
            news_items = await _fetch_naver_news(keyword, display=30)
        except Exception:
            logger.exception("키워드 뉴스 수집 실패: %s", keyword)
            continue
        for item in news_items:
            item["matched_keyword"] = keyword
            pub = _parse_pub_datetime(item.get("published", ""))
            # fail-open: pubDate 파싱 실패 시 정상 뉴스 유실 방지 (keep)
            if (
                freshness_hours > 0
                and pub is not None
                and (now - pub) > timedelta(hours=freshness_hours)
            ):
                stale_dropped += 1
                continue
            item["pub_date"] = pub.strftime("%Y-%m-%d %H:%M") if pub else None
            fresh_count += 1
            all_news.append(item)

    logger.info(
        "[scan_single_theme] %s 뉴스: fresh=%d stale_dropped=%d (기준 %dh)",
        theme.name, fresh_count, stale_dropped, freshness_hours,
    )
    return all_news


async def scan_all_themes() -> dict[str, int]:
    """전체 활성 테마 스캔. {테마명: 신규감지건수} 반환.

    동시에 `theme_scan_runs` / `theme_scan_results` 테이블에 실행 메타데이터와
    검증 통과 종목을 저장한다 (StockAI Pull 조회용).
    """
    scan_date = datetime.now(KST).date()
    results: dict[str, int] = {}
    _ac_cache.clear()   # 스캔 1회 수명 캐시 초기화 (상장/상폐 반영)
    last_scan_stats["verify_failed"] = 0
    await _load_listed_names()   # 노이즈 규칙 화이트리스트 (상장사명)

    try:
        await _start_scan_run(scan_date)
    except Exception:
        logger.exception("스캔 run 레코드 시작 실패 (스캔은 계속 진행)")

    try:
        async with async_session() as session:
            result = await session.execute(
                select(Theme).where(Theme.enabled == True)  # noqa: E712
            )
            themes = list(result.scalars().all())

        # ── 교차 테마 가드 ────────────────────────────────────────────
        # 전 테마 뉴스를 먼저 수집해 복수 테마에 동시 매칭된 제목을 산출하고,
        # 해당 제목은 모든 테마에서 검증 대상에서 제외한다(광범위 시황/리포트 오탐 차단).
        theme_news_map: dict[int, list[dict[str, Any]]] = {}
        for theme in themes:
            try:
                theme_news_map[theme.id] = await _gather_theme_news(theme)
            except Exception:
                logger.exception("테마 뉴스 수집 실패: %s", theme.name)
                theme_news_map[theme.id] = []
        theme_title_map = {
            tid: {n.get("title", "") for n in news if n.get("title")}
            for tid, news in theme_news_map.items()
        }
        # P3-1: 광범위 마커 기사만 전 테마 차단, 나머지 복수 매칭은 대표 테마 배정
        banned_titles = _find_banned_broad_titles(theme_title_map)
        primary_theme_by_title = _assign_primary_theme(
            _build_title_kw_counts(theme_news_map), banned_titles,
        )
        if banned_titles or primary_theme_by_title:
            logger.info(
                "[cross_theme_guard] 광범위 기사 차단 %d건 · 대표 테마 배정 %d건",
                len(banned_titles), len(primary_theme_by_title),
            )

        total_stocks = 0
        for theme in themes:
            try:
                async with async_session() as session:
                    count = await _scan_single_theme(
                        session, theme, scan_date=scan_date,
                        all_news=theme_news_map.get(theme.id),
                        banned_titles=banned_titles,
                        primary_theme_by_title=primary_theme_by_title,
                    )
                results[theme.name] = count
                total_stocks += count
            except Exception:
                logger.exception("테마 스캔 실패: %s", theme.name)
                results[theme.name] = 0

        try:
            await _complete_scan_run(scan_date, total_themes=len(themes), total_stocks=total_stocks)
        except Exception:
            logger.exception("스캔 run 완료 마킹 실패")

    except Exception as e:
        try:
            await _fail_scan_run(scan_date, str(e))
        except Exception:
            logger.exception("스캔 run 실패 마킹 실패")
        raise

    return results


async def _verify_and_persist_detections(
    session: AsyncSession,
    theme: Theme,
    detected_stocks: dict[str, dict[str, Any]],
    existing_codes: set[str],
) -> list[dict[str, Any]]:
    """Claude 검증 결과를 ThemeDetection으로 저장하고 통과분(YES) 반환.

    - existing_codes에 이미 있는 종목은 검증 스킵 (중복 윈도우)
    - NO 판정도 verdict="NO"로 기록 → NO_VERDICT_WINDOW_DAYS간 재검증 스킵
      (기존에는 NO 미기록 → 지속 이슈 종목을 매일 재검증 + 판정 플립 측정 불가)
    - 검증 실패(None)는 "미판정" — 기록하지 않고 카운트만 (다음 스캔 재시도)
    - DB commit 실패 시 rollback 후 빈 리스트 반환
    """
    new_detections: list[dict[str, Any]] = []
    rejected_no = 0
    rejected_low = 0
    verify_failed = 0
    retry_yes = 0   # P3-2: 대체 기사 재검증으로 YES 전환된 건수
    for stock_code, info in detected_stocks.items():
        if stock_code in existing_codes:
            continue

        # P3-2: 대표 기사 선정 → 판정. NO이고 대체 기사가 있으면 **1회만** 재검증
        # (약한 스침 기사가 먼저 잡혀 강한 재료가 NO 되는 첫 기사 편향 해소).
        articles = _order_articles(info)
        chosen = articles[0]
        verdict, materiality, reason = await _verify_theme_match(
            theme_name=theme.name,
            matched_keyword=chosen["matched_keyword"],
            stock_name=info["stock_name"],
            title=chosen["headline"],
            description=chosen.get("description", ""),
            pub_date_str=chosen.get("pub_date"),
        )
        if verdict is False and len(articles) > 1:
            v2, m2, r2 = await _verify_theme_match(
                theme_name=theme.name,
                matched_keyword=articles[1]["matched_keyword"],
                stock_name=info["stock_name"],
                title=articles[1]["headline"],
                description=articles[1].get("description", ""),
                pub_date_str=articles[1].get("pub_date"),
            )
            if v2 is True:
                verdict, materiality, reason = v2, m2, r2
                chosen = articles[1]
                retry_yes += 1
        # 채택 기사를 대표로 반영 (기록·알림 일관성)
        info["headline"] = chosen["headline"]
        info["matched_keyword"] = chosen["matched_keyword"]
        info["url"] = chosen.get("url", info.get("url", ""))
        info["pub_date"] = chosen.get("pub_date")
        logger.info(
            "테마 검증: theme=%s stock=%s(%s) verdict=%s materiality=%s reason=%s",
            theme.name, info["stock_name"], stock_code,
            "YES" if verdict is True else ("NO" if verdict is False else "미판정"),
            materiality, reason,
        )
        if verdict is None:
            # 일시 장애/파싱 실패 — NO로 강등하지 않는다 (조용한 전멸 방지).
            verify_failed += 1
            continue

        # 중요도 판정: strict 모드에서 LOW는 탈락. 파싱 실패(None)는 통과(보수적 신규 축).
        is_low_reject = (
            verdict and settings.theme_verify_strict and materiality == "LOW"
        )
        if is_low_reject:
            rejected_low += 1
            logger.info(
                "[materiality] LOW 탈락: theme=%s stock=%s reason=%s",
                theme.name, info["stock_name"], reason,
            )
        elif not verdict:
            rejected_no += 1

        final_verdict = "YES" if (verdict and not is_low_reject) else "NO"
        detection = ThemeDetection(
            theme_id=theme.id,
            stock_code=stock_code,
            stock_name=info["stock_name"],
            headline=info["headline"],
            matched_keyword=info["matched_keyword"],
            news_url=info["url"],
            prompt_version=PROMPT_VERSION,
            verdict=final_verdict,
        )
        session.add(detection)
        if final_verdict == "YES":
            info["materiality"] = materiality
            new_detections.append(info)

    if rejected_no or rejected_low or verify_failed or retry_yes:
        logger.info(
            "[verify] %s 탈락 분포: NO=%d, materiality_LOW=%d, 미판정=%d, retry_yes=%d",
            theme.name, rejected_no, rejected_low, verify_failed, retry_yes,
        )
    last_scan_stats["verify_failed"] += verify_failed

    try:
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("테마 감지 저장 실패")
        return []

    return new_detections


async def _scan_single_theme(
    session: AsyncSession,
    theme: Theme,
    scan_date: Optional[date] = None,
    all_news: Optional[list[dict[str, Any]]] = None,
    banned_titles: Optional[set[str]] = None,
    primary_theme_by_title: Optional[dict[str, Any]] = None,
) -> int:
    """단일 테마 스캔 — 신규 감지 종목 수 반환.

    all_news가 주어지면 재사용(교차 테마 가드 경로), 없으면 자체 수집.
    banned_titles(광범위 마커 + 복수 테마 매칭 제목)는 전 테마 검증 제외.
    primary_theme_by_title에 배정된 제목은 대표 테마가 아니면 skip (P3-1).
    """
    if all_news is None:
        all_news = await _gather_theme_news(theme)
    banned_titles = banned_titles or set()
    primary_theme_by_title = primary_theme_by_title or {}

    if not all_news:
        return 0

    detected_stocks: dict[str, dict[str, Any]] = {}
    banned_skipped = 0
    reassigned_skipped = 0
    for news in all_news:
        title = news.get("title", "")
        if title in banned_titles:   # 광범위 기사 → 전 테마 검증 제외
            banned_skipped += 1
            continue
        # P3-1: 다른 테마에 대표 배정된 제목은 이 테마에서 skip
        if primary_theme_by_title.get(title, theme.id) != theme.id:
            reassigned_skipped += 1
            continue
        description = news.get("description", "")
        combined_text = f"{title} {description[:200]}"
        candidates = set(STOCK_NAME_PATTERN.findall(combined_text))
        for candidate in candidates:
            if len(candidate) < 2:
                continue
            if candidate in STOPWORDS:            # 불용어 차단 (호출 전)
                continue
            # 그룹명 단독: 계열사명이 같은 뉴스에 동반될 때만 차단.
            # 단독 등장(신세계·오리온·대상 등 사업회사 본체)은 Claude 검증에 위임.
            if candidate in GROUP_PREFIX_NAMES and _group_prefix_is_noise(
                candidate, combined_text
            ):
                continue
            # 숫자/금액/조사/HTML잔재 차단 — 단, 상장사명 화이트리스트는 예외
            # (에코프로·쎄트렉아이·LG디스플레이·대원 등 조사·단위 규칙 오차단 복구)
            if candidate not in _listed_names and _is_noise_token(candidate):
                continue

            try:
                matches = await _cached_search_stocks(candidate)
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
                    "pub_date": news.get("pub_date"),
                    "alt_news": [],
                }
            else:
                # P3-2: 다른 제목의 기사면 대체 기사로 축적 (첫 기사 편향 해소)
                info = detected_stocks[stock_code]
                existing_titles = {info["headline"]} | {
                    a["headline"] for a in info.get("alt_news", [])
                }
                if title not in existing_titles and len(info.get("alt_news", [])) < 2:
                    info.setdefault("alt_news", []).append({
                        "headline": title,
                        "description": news.get("description", ""),
                        "matched_keyword": news["matched_keyword"],
                        "url": news.get("link", ""),
                        "pub_date": news.get("pub_date"),
                    })

    if banned_skipped or reassigned_skipped:
        logger.info(
            "[cross_theme_guard] %s: 광범위 차단 %d건 · 타 테마 배정 skip %d건",
            theme.name, banned_skipped, reassigned_skipped,
        )

    # ── DART 🟢 호재 공시 추출 (테마 키워드가 공시 제목에 포함된 것만) ──
    # DART는 stock_code를 직접 제공 → 네이버 AC 역추적·정확일치 필터 불필요(이미 정확).
    # 단, 이후 Claude 검증 + prefilter는 뉴스 추출분과 동일하게 통과한다.
    keywords = [k.strip() for k in theme.keywords.split(",") if k.strip()]
    try:
        from app.collectors import dart_collector
        disclosures = await dart_collector.get_today_disclosures(
            target_date=scan_date, include_previous_day=True,  # P2-1: 08:10엔 당일 공시 거의 없음
        )
    except Exception:
        logger.exception(
            "[scan_single_theme] DART 수집 실패 — 뉴스만으로 진행: %s", theme.name
        )
        disclosures = []

    for disc in disclosures:
        if disc.get("importance") != "🟢":   # 호재 공시만
            continue
        stock_code = (disc.get("stock_code") or "").strip()
        if not stock_code or len(stock_code) != 6:
            continue   # 비상장/코드 없는 공시 제외

        disc_title = disc.get("title", "")
        # 이 테마의 키워드가 공시 제목에 포함되는지
        matched_kw = next((k for k in keywords if k and k in disc_title), None)
        if not matched_kw:
            continue

        if stock_code not in detected_stocks:   # 같은 코드면 뉴스 추출분 선점
            rcept_no = disc.get("rcept_no", "")
            detected_stocks[stock_code] = {
                "stock_code": stock_code,
                "stock_name": disc.get("corp_name", ""),
                "headline": f"[공시] {disc_title}",   # 출처 표시 (알림 가독성)
                "description": "",
                "matched_keyword": matched_kw,
                "url": (
                    f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
                    if rcept_no else ""
                ),
                "source_type": "dart",   # 출처별 성적 측정용 태그
            }

    if not detected_stocks:
        return 0

    # 본문 추출로 candidate 폭증 시 헤드라인 매칭 우선 30개 제한
    if len(detected_stocks) > MAX_CANDIDATES_PER_THEME:
        headline_first = {
            k: v for k, v in detected_stocks.items()
            if v["stock_name"] in v.get("headline", "")
        }
        body_only = {
            k: v for k, v in detected_stocks.items()
            if k not in headline_first
        }
        limited: dict[str, dict[str, Any]] = dict(headline_first)
        for k, v in body_only.items():
            if len(limited) >= MAX_CANDIDATES_PER_THEME:
                break
            limited[k] = v
        detected_stocks = limited
        logger.info(
            "테마 %s: candidate 초과 → %d개로 제한",
            theme.name, MAX_CANDIDATES_PER_THEME,
        )

    # 중복 검증 윈도우 — YES(NULL 포함 레거시)는 DETECTION_WINDOW_DAYS,
    # NO는 NO_VERDICT_WINDOW_DAYS(짧게)만 재검증을 스킵.
    # 그 이전 레코드는 무시 → 폭등 후 RSI 정상화된 종목을 매수 적기에 재검증.
    cutoff = now_kst_naive() - timedelta(days=DETECTION_WINDOW_DAYS)
    no_cutoff = now_kst_naive() - timedelta(days=NO_VERDICT_WINDOW_DAYS)
    existing_result = await session.execute(
        select(ThemeDetection.stock_code, ThemeDetection.verdict, ThemeDetection.detected_at)
        .where(ThemeDetection.theme_id == theme.id)
        .where(ThemeDetection.detected_at >= cutoff)
        .where(ThemeDetection.is_active.is_(True))
    )
    existing_codes = set()
    for code, verdict, detected_at in existing_result.all():
        if verdict == "NO":
            if detected_at is not None and detected_at >= no_cutoff:
                existing_codes.add(code)
        else:  # "YES" 또는 NULL(레거시 = YES)
            existing_codes.add(code)

    new_detections = await _verify_and_persist_detections(
        session, theme, detected_stocks, existing_codes,
    )
    if not new_detections:
        return 0

    # ── 사전 필터 ───────────────────────────────────────────────
    # Claude 검증 통과 종목 중 이미 폭등한/시총 작은 종목을 제외.
    # ThemeDetection은 verified 전체로 유지 (다음 스캔의 중복 검증 방지).
    # ThemeScanResult / 텔레그램 알림은 filtered만 노출.
    codes = [d["stock_code"] for d in new_detections]
    try:
        prefilter_map: dict[str, PrefilterResult] = await prefilter_stocks(codes)
    except Exception:
        logger.exception("[prefilter] 호출 실패 — 보수적 통과: %s", theme.name)
        prefilter_map = {}

    filtered: list[dict[str, Any]] = []
    rejected: list[tuple[dict[str, Any], list[str]]] = []
    for d in new_detections:
        result = prefilter_map.get(d["stock_code"])
        if result is None or result.passed:
            if result is not None:
                d["supply_demand"] = _supply_demand_subset(result.metrics)
            filtered.append(d)
        else:
            rejected.append((d, result.reasons))
            logger.info(
                "[prefilter] reject %s %s: %s",
                d["stock_code"], d["stock_name"], result.reasons,
            )

    logger.info(
        "[scan_single_theme] %s: verified=%d → filtered=%d (rejected=%d)",
        theme.name, len(new_detections), len(filtered), len(rejected),
    )

    # 피처 스냅샷 기록 (통과+제외 전체 — "오를 종목" 검증 데이터셋 누적)
    try:
        await _record_feature_snapshots(
            scan_date, theme.name, new_detections, prefilter_map,
        )
    except Exception:
        logger.exception("[feature_snapshot] 기록 실패: %s", theme.name)

    if filtered or rejected:
        await _send_theme_alert(theme.name, filtered, rejected=rejected)

    if scan_date is not None and filtered:
        try:
            await save_scan_results(scan_date, theme.name, filtered)
        except Exception:
            logger.exception("스캔 결과 DB 저장 실패: %s", theme.name)

    return len(filtered)


# ── 스캔 run / 결과 저장 헬퍼 (StockAI Pull API용) ─────────────────────


async def _start_scan_run(scan_date: date) -> None:
    """스캔 시작 — run 레코드 생성 또는 재시작 (idempotent).

    같은 날짜 재실행 시 기존 레코드 상태를 'running'으로 리셋한다.
    """
    now = datetime.now(KST)
    async with async_session() as session:
        existing = await session.execute(
            select(ThemeScanRun).where(ThemeScanRun.scan_date == scan_date)
        )
        run = existing.scalar_one_or_none()
        if run:
            run.status = "running"
            run.started_at = now
            run.completed_at = None
            run.error_message = None
            run.total_themes = 0
            run.total_stocks = 0
        else:
            session.add(
                ThemeScanRun(
                    scan_date=scan_date,
                    started_at=now,
                    status="running",
                )
            )
        await session.commit()


async def _complete_scan_run(
    scan_date: date,
    total_themes: int,
    total_stocks: int,
) -> None:
    async with async_session() as session:
        await session.execute(
            update(ThemeScanRun)
            .where(ThemeScanRun.scan_date == scan_date)
            .values(
                status="completed",
                completed_at=datetime.now(KST),
                total_themes=total_themes,
                total_stocks=total_stocks,
            )
        )
        await session.commit()


async def _fail_scan_run(scan_date: date, error: str) -> None:
    async with async_session() as session:
        await session.execute(
            update(ThemeScanRun)
            .where(ThemeScanRun.scan_date == scan_date)
            .values(
                status="failed",
                completed_at=datetime.now(KST),
                error_message=error[:1000],
            )
        )
        await session.commit()


_SUPPLY_DEMAND_KEYS = (
    "short_weight_5d", "short_weight_prev5", "short_weight_rising",
    "lending_balance", "lending_surge", "institution_net", "foreign_net",
    "institution_net_5d", "foreign_net_5d",   # P2-2: ka10059 히스토리 합계
)


def _supply_demand_subset(metrics: dict[str, Any]) -> Optional[dict[str, Any]]:
    """prefilter metrics에서 수급(공매도/대차/기관·외국인) 키만 추출. 없으면 None."""
    sd = {k: metrics[k] for k in _SUPPLY_DEMAND_KEYS if k in metrics}
    return sd or None


async def _record_feature_snapshots(
    scan_date: Optional[date],
    theme_name: str,
    detections: list[dict[str, Any]],
    prefilter_map: dict[str, "PrefilterResult"],
) -> None:
    """감지 시점 피처 스냅샷 기록 (통과+제외 전체).

    prefilter가 이미 계산한 전체 metrics를 저장만 한다. scan_date가 없으면
    (수동 호출 등) 앵커가 없어 스킵. UNIQUE 충돌은 사전 SELECT로 회피.
    """
    if scan_date is None:
        return
    async with async_session() as session:
        for d in detections:
            code = d.get("stock_code")
            name = d.get("stock_name")
            result = prefilter_map.get(code) if code else None
            if not code or not name or result is None:
                continue
            existing = await session.execute(
                select(ThemeFeatureSnapshot.id).where(
                    ThemeFeatureSnapshot.scan_date == scan_date,
                    ThemeFeatureSnapshot.theme_name == theme_name,
                    ThemeFeatureSnapshot.stock_code == code,
                )
            )
            if existing.scalar_one_or_none():
                continue
            session.add(
                ThemeFeatureSnapshot(
                    scan_date=scan_date,
                    theme_name=theme_name,
                    stock_code=code,
                    stock_name=name,
                    passed=bool(result.passed),
                    reject_reasons=(result.reasons or None) if not result.passed else None,
                    features=result.metrics or None,
                )
            )
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("피처 스냅샷 commit 실패: %s", theme_name)


async def save_scan_results(
    scan_date: date,
    theme_name: str,
    new_detections: list[dict[str, Any]],
) -> None:
    """검증 통과된 종목들을 `theme_scan_results`에 저장.

    UNIQUE(scan_date, theme_name, stock_code) 충돌 시 SELECT로 사전 확인 후 skip
    (SQLite/Postgres 양쪽 호환).
    """
    if not new_detections:
        return

    async with async_session() as session:
        for d in new_detections:
            stock_code = d.get("stock_code")
            stock_name = d.get("stock_name")
            if not stock_code or not stock_name:
                continue

            existing = await session.execute(
                select(ThemeScanResult.id).where(
                    ThemeScanResult.scan_date == scan_date,
                    ThemeScanResult.theme_name == theme_name,
                    ThemeScanResult.stock_code == stock_code,
                )
            )
            if existing.scalar_one_or_none():
                continue

            keyword = d.get("matched_keyword")
            keywords_list = [keyword] if keyword else []

            session.add(
                ThemeScanResult(
                    scan_date=scan_date,
                    theme_name=theme_name,
                    stock_code=stock_code,
                    stock_name=stock_name,
                    detected_keywords=keywords_list,
                    source_url=d.get("url"),
                    claude_validation_passed=True,
                    supply_demand=d.get("supply_demand"),
                )
            )
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("테마 스캔 결과 commit 실패: %s", theme_name)


async def _send_theme_alert(
    theme_name: str,
    detections: list[dict[str, Any]],
    rejected: Optional[list[tuple[dict[str, Any], list[str]]]] = None,
) -> None:
    """신규 감지 종목 텔레그램 알림.

    `rejected`는 사전 필터에서 제외된 종목 (종목정보, 사유) 리스트.
    제공 시 메시지 하단에 최대 3건 + "외 N건" 표시.
    """
    escape = telegram_service.escape_html

    lines = [f"🎯 <b>테마 선행 포착 — {escape(theme_name)}</b>", ""]

    if detections:
        lines.append(f"새로운 수혜주 후보 ({len(detections)}종목):")
        lines.append("")
        for d in detections[:10]:
            headline = escape(d["headline"][:60])
            lines.append(
                f"• <b>{escape(d['stock_name'])}</b> ({d['stock_code']})\n"
                f"   └ {escape(d['matched_keyword'])} · {headline}"
            )
    else:
        lines.append("새로운 수혜주 후보 0종목 (사전 필터로 모두 제외)")

    if rejected:
        lines.append("")
        lines.append(f"<i>사전 필터 제외: {len(rejected)}건</i>")
        for d, reasons in rejected[:3]:
            first = reasons[0] if reasons else "(사유 미상)"
            lines.append(
                f"  ⊘ {escape(d['stock_name'])} ({d['stock_code']}): {escape(first)}"
            )
        if len(rejected) > 3:
            lines.append(f"  ⊘ … 외 {len(rejected) - 3}건")

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
                prompt_version=PROMPT_VERSION,  # 지시서 F-패치: 버전 태깅
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
            select(ThemeDetection)
            .where(ThemeDetection.theme_id == t.id)
            .where(ThemeDetection.is_active.is_(True))
            # NO 판정 기록은 감지 수에서 제외 (NULL=레거시 YES)
            .where(
                (ThemeDetection.verdict.is_(None))
                | (ThemeDetection.verdict != "NO")
            )
        )
        detected_count = len(list(count_result.scalars().all()))
        output.append({
            "name": t.name,
            "keywords": t.keywords,
            "enabled": t.enabled,
            "detected_count": detected_count,
        })

    return output
