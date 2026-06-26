"""테마 선행 스캐너 — 키워드 기반 뉴스 스캔으로 수혜주 후보 발굴"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.news_collector import _fetch_naver_news
from app.collectors.stock_search import search_stocks
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
from app.utils.timezone import now_kst_naive

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

# 본문 추출 도입 시 candidate 폭증 방지 (Claude 검증 비용 통제). 헤드라인 매칭 우선.
MAX_CANDIDATES_PER_THEME = 30

# ── Claude 검증 레이어 ─────────────────────────────────────────────────
# 공통 호출/파싱은 ai_verifier.verify_with_claude로 위임. 여기서는 프롬프트만 보유.

_VERIFY_PROMPT_TEMPLATE = """당신은 한국 주식 테마 분석 전문가입니다. 이 판정 결과는 자동매매 시스템의 매수 후보 입력으로 사용되므로, 오탐(false positive)의 비용이 매우 큽니다.

한 투자자가 다음 테마의 수혜주를 찾고 있습니다:
테마명: {theme_name}
검색 키워드: {matched_keyword}

아래 뉴스에 언급된 종목 "{stock_name}"을 판정하세요.

--- 뉴스 시작 ---
제목: {title}
설명: {description}
--- 뉴스 끝 ---

다음 **두 조건을 모두** 만족할 때만 YES:

조건 1 — 실질 관련성:
- 종목의 **주력 사업(매출 비중이 큰 핵심 사업)**이 이 테마와 직접 관련 있어야 함
- 그룹 지주회사가 계열사 이슈로 언급된 경우는 NO (예: 방산 뉴스의 "한화"는 한화에어로스페이스가 수혜주이지 지주사 한화가 아님)
- 테마가 **일부 사업부·자회사**에만 해당하면 NO (예: 운송사의 작은 항공우주 부문, 식품사의 소규모 신사업)
- **비교·예시·업황 설명·간접 연관**으로 언급됐을 뿐이면 NO (예: "유가 상승으로 항공주 영향" 류 거시 연관)
- 뉴스에 이름만 스쳐 지나가는 경우 NO

조건 2 — 신규 촉매:
- 이 뉴스가 **구체적인 신규 사건**(수주, 계약, 실적 발표, 정책 결정, 신제품, 투자 유치 등)을 다루고 있어야 함
- 단순 시황 나열, 업종 동향 일반론, 과거 사건의 반복 언급, "관련주 정리" 류 기사는 NO

**애매하면 NO.** 확신이 없으면 NO.

출력 형식 (정확히 지켜주세요):
VERDICT: YES
REASON: (1줄 근거)

또는:

VERDICT: NO
REASON: (1줄 근거)

**주의:** 종목의 주력 사업 판단은 뉴스 본문이 아닌 당신이 알고 있는 정보를 기준으로 하되, "무슨 사건이 발생했는가"는 뉴스 내용을 기준으로 판정하세요."""


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
    prompt = _VERIFY_PROMPT_TEMPLATE.format(
        theme_name=theme_name,
        matched_keyword=matched_keyword,
        stock_name=stock_name,
        title=title,
        description=description or "(설명 없음)",
    )

    verdict, reason = await ai_verifier.verify_with_claude(
        prompt,
        log_context=f"theme={theme_name} stock={stock_name}",
    )
    # 정책: theme_radar는 fail-closed — 검증 실패(None)는 NO로 강등
    return (verdict is True), reason


# ── 스캔 엔진 (스케줄러/수동 스캔 진입점) ─────────────────────────────────


async def scan_all_themes() -> dict[str, int]:
    """전체 활성 테마 스캔. {테마명: 신규감지건수} 반환.

    동시에 `theme_scan_runs` / `theme_scan_results` 테이블에 실행 메타데이터와
    검증 통과 종목을 저장한다 (StockAI Pull 조회용).
    """
    scan_date = datetime.now(KST).date()
    results: dict[str, int] = {}
    _ac_cache.clear()   # 스캔 1회 수명 캐시 초기화 (상장/상폐 반영)

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

        total_stocks = 0
        for theme in themes:
            try:
                async with async_session() as session:
                    count = await _scan_single_theme(session, theme, scan_date=scan_date)
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
    """Claude 검증 통과 종목만 ThemeDetection으로 저장하고 통과분 반환.

    - existing_codes에 이미 있는 종목은 검증 스킵 (중복 윈도우)
    - 검증 실패(None/False)는 fail-closed로 제외
    - DB commit 실패 시 rollback 후 빈 리스트 반환
    """
    new_detections: list[dict[str, Any]] = []
    for stock_code, info in detected_stocks.items():
        if stock_code in existing_codes:
            continue

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
        return []

    return new_detections


async def _scan_single_theme(
    session: AsyncSession,
    theme: Theme,
    scan_date: Optional[date] = None,
) -> int:
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
        description = news.get("description", "")
        combined_text = f"{title} {description[:200]}"
        candidates = set(STOCK_NAME_PATTERN.findall(combined_text))
        for candidate in candidates:
            if len(candidate) < 2:
                continue
            if candidate in STOPWORDS:            # 불용어 차단 (호출 전)
                continue
            if candidate in GROUP_PREFIX_NAMES:   # 지주사 오탐 차단
                continue
            if _is_noise_token(candidate):        # 숫자/금액/조사/HTML잔재 차단
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
                }

    # ── DART 🟢 호재 공시 추출 (테마 키워드가 공시 제목에 포함된 것만) ──
    # DART는 stock_code를 직접 제공 → 네이버 AC 역추적·정확일치 필터 불필요(이미 정확).
    # 단, 이후 Claude 검증 + prefilter는 뉴스 추출분과 동일하게 통과한다.
    try:
        from app.collectors import dart_collector
        disclosures = await dart_collector.get_today_disclosures(target_date=scan_date)
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

    # 중복 검증 윈도우 — DETECTION_WINDOW_DAYS 이내 검증한 종목만 SKIP.
    # 그 이전 레코드는 무시 → 폭등 후 RSI 정상화된 종목을 매수 적기에 재검증.
    cutoff = now_kst_naive() - timedelta(days=DETECTION_WINDOW_DAYS)
    existing_result = await session.execute(
        select(ThemeDetection.stock_code)
        .where(ThemeDetection.theme_id == theme.id)
        .where(ThemeDetection.detected_at >= cutoff)
    )
    existing_codes = set(existing_result.scalars().all())

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
