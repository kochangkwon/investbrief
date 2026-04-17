# InvestBrief — 테마 선행 스캐너 추가 지시서

## 목표

관심 있는 **테마 키워드**(예: "AI 데이터센터 전력 인프라", "방산 수출")를 등록하고, 주 1회 관련 뉴스를 스캔하여 **새로운 수혜주**를 발견하면 텔레그램으로 알림.

### 동작 시나리오

```
[Ko~님]
  /theme-add "AI 데이터센터 전력 인프라" 북미인증,초고압케이블,변압기수주,345kV,KEMA

[매주 월요일 08:00 — 자동 스캔]
  → 테마별 키워드로 네이버 뉴스 검색
  → 뉴스 제목에서 종목명 추출 → stock_search로 검증
  → 이미 감지된 종목은 제외
  → 신규 종목 발견 시 텔레그램 알림

[텔레그램 알림]
  🎯 테마 선행 포착 — AI 데이터센터 전력 인프라
  새로운 수혜주 후보:
  • LS에코에너지 (229640) — "KEMA 230kV 인증 획득"
  • 일진전기 (103590) — "북미 변압기 수주 확대"
```

---

## 수정 1: DB 모델 추가

### 1-1. 테마 모델 신규 생성

파일: `backend/app/models/theme.py` (신규)

```python
import datetime
from typing import Optional

from sqlalchemy import DateTime, String, Text, Integer, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Theme(Base):
    """테마 스캐너 — 관심 테마 및 키워드 목록"""
    __tablename__ = "theme"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    keywords: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now
    )


class ThemeDetection(Base):
    """테마 스캔으로 감지된 종목 — 중복 알림 방지용"""
    __tablename__ = "theme_detection"

    id: Mapped[int] = mapped_column(primary_key=True)
    theme_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("theme.id", ondelete="CASCADE"), index=True
    )
    stock_code: Mapped[str] = mapped_column(String(6))
    stock_name: Mapped[str] = mapped_column(String(100))
    headline: Mapped[str] = mapped_column(Text)
    matched_keyword: Mapped[str] = mapped_column(String(100))
    news_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    detected_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now
    )
```

### 1-2. `backend/app/models/__init__.py`에 import 추가

```python
from app.models.theme import Theme, ThemeDetection  # noqa: F401
```

### 1-3. DB 테이블 생성

`database.py`의 `init_db()` 함수가 앱 시작 시 자동 호출되어 `Base.metadata.create_all`로 테이블이 생성됩니다. 수정 1-2의 import가 제대로 되면 자동으로 테이블이 생성됩니다.

수동 실행이 필요한 경우:
```bash
cd backend
python3 -c "
import asyncio
from app.database import init_db
from app.models.theme import Theme, ThemeDetection

asyncio.run(init_db())
print('✅ theme, theme_detection 테이블 생성 완료')
"
```

---

## 수정 2: 테마 스캐너 서비스 신규 생성

파일: `backend/app/services/theme_radar_service.py` (신규)

**★ 핵심 설계 원칙:**
- `watchlist_service`와 동일하게 **session을 외부에서 주입받는 패턴** 사용
- `async_session`을 사용하는 곳은 스케줄러 진입점뿐
- CRUD 함수는 session을 인자로 받음

```python
"""테마 선행 스캐너 — 키워드 기반 뉴스 스캔으로 수혜주 후보 발굴"""
from __future__ import annotations

import re
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.theme import Theme, ThemeDetection
from app.collectors.stock_search import search_stocks
from app.collectors.news_collector import _fetch_naver_news
from app.services import telegram_service

logger = logging.getLogger(__name__)


# 한글 종목명 추출 정규식 — 한글 2~15자 (영문/숫자 포함 가능)
STOCK_NAME_PATTERN = re.compile(r"([가-힣][가-힣A-Za-z0-9]{1,14})")


# ── 스캔 엔진 (스케줄러/수동 스캔 진입점) ─────────────────────────────────


async def scan_all_themes() -> dict[str, int]:
    """전체 활성 테마 스캔. {테마명: 신규감지건수} 반환."""
    results: dict[str, int] = {}

    async with async_session() as session:
        result = await session.execute(
            select(Theme).where(Theme.enabled == True)
        )
        themes = list(result.scalars().all())

    # 테마별로 독립 세션 — 한 테마 실패가 다른 테마에 영향 주지 않도록
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

    # 1. 키워드별 뉴스 수집
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

    # 2. 뉴스 제목에서 종목명 후보 추출 → stock_search로 검증
    detected_stocks: dict[str, dict[str, Any]] = {}  # stock_code → 정보
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

            # 정확 매칭만 인정 (stock_name == candidate)
            if not matches:
                continue
            m = matches[0]
            if m.get("stock_name") != candidate:
                continue

            stock_code = m["stock_code"]
            # 최초 감지만 저장 (동일 종목 여러 번 나와도 첫 번째만)
            if stock_code not in detected_stocks:
                detected_stocks[stock_code] = {
                    "stock_code": stock_code,
                    "stock_name": candidate,
                    "headline": title,
                    "matched_keyword": news["matched_keyword"],
                    "url": news.get("link", ""),
                }

    if not detected_stocks:
        return 0

    # 3. 이미 감지된 종목 필터링
    existing_result = await session.execute(
        select(ThemeDetection.stock_code).where(ThemeDetection.theme_id == theme.id)
    )
    existing_codes = set(existing_result.scalars().all())

    new_detections: list[dict[str, Any]] = []
    for stock_code, info in detected_stocks.items():
        if stock_code in existing_codes:
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

    # 4. 텔레그램 알림
    if new_detections:
        await _send_theme_alert(theme.name, new_detections)

    return len(new_detections)


async def _send_theme_alert(theme_name: str, detections: list[dict[str, Any]]) -> None:
    """신규 감지 종목 텔레그램 알림"""
    # HTML 특수문자 이스케이프
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
    from sqlalchemy import delete

    result = await session.execute(select(Theme).where(Theme.name == name))
    theme = result.scalar_one_or_none()
    if not theme:
        return False, f"테마를 찾을 수 없습니다: {name}"

    # SQLite에서 FK CASCADE가 비활성화된 경우를 대비해 감지 이력 먼저 삭제
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
```

---

## 수정 3: 스케줄러에 주간 스캔 추가

파일: `backend/app/services/scheduler.py`

### 3-1. import 추가

기존 import 블록에 추가:
```python
from app.services import theme_radar_service
```

### 3-2. 스캔 함수 추가

기존 job 함수들(`_midday_watchlist_check`, `_daily_report` 등) 근처에 추가:

```python
async def _weekly_theme_scan():
    """주 1회 테마 선행 스캐너 (매주 월요일 08:00)"""
    logger.info("주간 테마 스캔 시작")
    try:
        results = await theme_radar_service.scan_all_themes()
        total_new = sum(results.values())
        logger.info("주간 테마 스캔 완료 — 신규 감지 %d건: %s", total_new, results)
    except Exception:
        logger.exception("주간 테마 스캔 실패")
```

### 3-3. `start_scheduler` 함수에 job 추가

기존:
```python
scheduler.add_job(_cleanup_old_data, "cron", hour=18, minute=0, id="cleanup")
```

위에 추가:
```python
scheduler.add_job(
    _weekly_theme_scan, "cron",
    day_of_week="mon", hour=8, minute=0,
    id="weekly_theme_scan",
)
scheduler.add_job(_cleanup_old_data, "cron", hour=18, minute=0, id="cleanup")
```

로그 메시지 업데이트:
```python
logger.info(
    "스케줄러 시작: %02d:00 브리프 | 12:00 점심체크 | 16:30 일일리포트 | 월 08:00 테마스캔 | 18:00 정리",
    hour,
)
```

---

## 수정 4: 텔레그램 명령어 4개 추가

파일: `backend/app/services/telegram_bot.py`

### 4-1. import 수정

현재:
```python
import asyncio
import logging
from datetime import date
from typing import Any

import httpx

from app.config import settings
from app.database import async_session
from app.services import brief_service, daily_report_service, watchlist_service, telegram_service
from app.collectors import news_collector, dart_collector
```

수정 — `re` 모듈 추가, `theme_radar_service` 추가:
```python
import asyncio
import logging
import re
from datetime import date
from typing import Any

import httpx

from app.config import settings
from app.database import async_session
from app.services import brief_service, daily_report_service, watchlist_service, telegram_service, theme_radar_service
from app.collectors import news_collector, dart_collector
```

### 4-2. 핸들러 함수 추가

기존 핸들러들(`_handle_help` 위) 근처에 추가:

```python
async def _handle_theme_add(args: str) -> str:
    """
    /theme-add "테마명" 키워드1,키워드2,키워드3
    예: /theme-add "AI 데이터센터 전력" 북미인증,초고압케이블,345kV
    """
    if not args.strip():
        return (
            "사용법:\n"
            '/theme-add "테마명" 키워드1,키워드2,키워드3\n\n'
            "예시:\n"
            '/theme-add "AI 데이터센터 전력" 북미인증,초고압케이블,345kV,KEMA'
        )

    # "테마명" 파싱
    match = re.match(r'^"([^"]+)"\s+(.+)$', args.strip())
    if not match:
        return '테마명은 큰따옴표로 감싸주세요: /theme-add "테마명" 키워드1,키워드2'

    theme_name = match.group(1)
    keywords = match.group(2).strip()

    if not keywords:
        return "키워드를 최소 1개 이상 입력해주세요."

    async with async_session() as session:
        success, message = await theme_radar_service.add_theme(session, theme_name, keywords)
    return ("✅ " if success else "❌ ") + message


async def _handle_theme_remove(args: str) -> str:
    """/theme-remove "테마명" """
    if not args.strip():
        return '사용법: /theme-remove "테마명"'

    match = re.match(r'^"([^"]+)"$', args.strip())
    if not match:
        return '테마명은 큰따옴표로 감싸주세요: /theme-remove "테마명"'

    theme_name = match.group(1)
    async with async_session() as session:
        success, message = await theme_radar_service.remove_theme(session, theme_name)
    return ("✅ " if success else "❌ ") + message


async def _handle_theme_list() -> str:
    """/theme-list — 등록된 테마 목록"""
    async with async_session() as session:
        themes = await theme_radar_service.list_themes(session)

    if not themes:
        return "등록된 테마가 없습니다.\n/theme-add 로 테마를 추가해보세요."

    lines = [f"🎯 <b>등록된 테마 ({len(themes)}개)</b>", ""]
    for i, t in enumerate(themes, 1):
        status = "🟢" if t["enabled"] else "🔴"
        lines.append(
            f"{i}. {status} <b>{t['name']}</b>\n"
            f"   키워드: {t['keywords']}\n"
            f"   감지 종목: {t['detected_count']}개"
        )

    return "\n".join(lines)


async def _handle_theme_scan() -> str:
    """/theme-scan — 수동 즉시 스캔"""
    await telegram_service.send_text("🔍 테마 스캔 시작... (시간이 걸릴 수 있습니다)")

    results = await theme_radar_service.scan_all_themes()
    total_new = sum(results.values())

    if total_new == 0:
        return "✅ 스캔 완료 — 새로운 수혜주 후보 없음"

    lines = [f"✅ 스캔 완료 — 총 {total_new}종목 신규 감지", ""]
    for theme_name, count in results.items():
        if count > 0:
            lines.append(f"• {theme_name}: {count}종목")

    return "\n".join(lines)
```

### 4-3. COMMAND_HANDLERS에 등록

현재:
```python
COMMAND_HANDLERS = {
    "/today": lambda args: _handle_today(),
    "/watch": _handle_watch,
    "/unwatch": _handle_unwatch,
    "/list": lambda args: _handle_list(),
    "/news": _handle_news,
    "/dart": _handle_dart,
    "/report": _handle_report,
    "/help": _handle_help,
    "/start": _handle_help,
}
```

수정:
```python
COMMAND_HANDLERS = {
    "/today": lambda args: _handle_today(),
    "/watch": _handle_watch,
    "/unwatch": _handle_unwatch,
    "/list": lambda args: _handle_list(),
    "/news": _handle_news,
    "/dart": _handle_dart,
    "/report": _handle_report,
    "/theme-add": _handle_theme_add,
    "/theme-remove": _handle_theme_remove,
    "/theme-list": lambda args: _handle_theme_list(),
    "/theme-scan": lambda args: _handle_theme_scan(),
    "/help": _handle_help,
    "/start": _handle_help,
}
```

**패턴 일관성:** `_handle_theme_add`/`_handle_theme_remove`는 `args`를 받으므로 직접 참조. `_handle_theme_list`/`_handle_theme_scan`은 `args` 미사용이므로 `lambda args: _handle_theme_list()` 패턴 (기존 `/today`, `/list`와 동일).

### 4-4. HELP_TEXT 업데이트

현재 HELP_TEXT(파일 상단 상수)에 테마 섹션 추가. 기존 HELP_TEXT 내용 끝에 다음 블록 추가:

```python
HELP_TEXT = """<b>📋 InvestBrief 명령어</b>

... (기존 내용 유지) ...

<b>🎯 테마 선행 스캐너</b>
/theme-add "테마명" 키워드1,키워드2 — 테마 추가
/theme-remove "테마명" — 테마 삭제
/theme-list — 테마 목록
/theme-scan — 즉시 스캔 (수동)

매주 월 08:00 자동 스캔 → 신규 수혜주 텔레그램 알림
"""
```

기존 HELP_TEXT 구조를 유지하면서 `<b>🎯 테마 선행 스캐너</b>` 섹션만 추가.

---

## 전체 동작 흐름

```
[Ko~님이 테마 등록]
  /theme-add "AI 데이터센터 전력 인프라" 북미인증,초고압케이블,345kV,KEMA
    ↓
  async_session() → theme_radar_service.add_theme()
    ↓
  DB: theme 테이블 저장
  ✅ 테마 추가 완료 알림

[매주 월요일 08:00 자동 실행]
  scheduler._weekly_theme_scan()
    ↓
  theme_radar_service.scan_all_themes()
    ├── 전체 활성 테마 조회
    ├── 테마별로 독립 세션 열기
    │   └── _scan_single_theme()
    │       ├── 키워드별 네이버 뉴스 검색
    │       ├── 뉴스 제목에서 한글 종목명 추출
    │       ├── stock_search.search_stocks()로 종목코드 검증
    │       ├── ThemeDetection에서 기존 감지 종목 제외
    │       ├── 신규 종목 DB 저장 + 커밋
    │       └── 텔레그램 알림
    ↓
  로그: "주간 테마 스캔 완료 — 신규 감지 N건"

[텔레그램 알림]
  🎯 테마 선행 포착 — AI 데이터센터 전력 인프라
  새로운 수혜주 후보 (2종목):
  • LS에코에너지 (229640)
     └ KEMA · LS에코에너지 베트남법인 美 230kV급 초고압 케이블 인증
  • 일진전기 (103590)
     └ 변압기수주 · 일진전기 북미 대형 변압기 수주
```

---

## 검증 방법

### 테스트 1: 테마 등록
```
/theme-add "AI 데이터센터 전력" 북미인증,초고압케이블,345kV,KEMA
→ ✅ 테마 추가 완료: AI 데이터센터 전력 (키워드 4개)
```

### 테스트 2: 목록 조회
```
/theme-list
→ 🎯 등록된 테마 (1개)
   1. 🟢 AI 데이터센터 전력
      키워드: 북미인증,초고압케이블,345kV,KEMA
      감지 종목: 0개
```

### 테스트 3: 수동 스캔
```
/theme-scan
→ 🔍 테마 스캔 시작...
→ ✅ 스캔 완료 — 총 2종목 신규 감지
   (텔레그램에 상세 알림도 함께 전송)
```

### 테스트 4: 중복 감지 방지
```
/theme-scan (1회차) → 2종목 감지
/theme-scan (2회차) → 0종목 (이미 감지됨, DB에서 필터링)
```

### 테스트 5: 테마 삭제
```
/theme-remove "AI 데이터센터 전력"
→ ✅ 테마 삭제 완료
  (ThemeDetection도 명시적으로 함께 삭제됨 — SQLite FK 환경 독립)
```

---

## 초기 추천 테마 예시

Ko~님 관심사 기반:

```
/theme-add "AI 데이터센터 전력 인프라" 북미인증,초고압케이블,345kV,KEMA,HVDC,데이터센터

/theme-add "방산 수출 확대" K9자주포,K2전차,KF-21,폴란드수주,중동수주,사우디,루마니아

/theme-add "반도체 HBM 슈퍼사이클" HBM,고대역폭메모리,파운드리,TSMC,삼성파운드리,후공정

/theme-add "원전 SMR 모멘텀" SMR,소형모듈원자로,X-Energy,원전수주,베트남원전

/theme-add "테슬라 AI칩 국내" 테슬라AI,도조칩,AI반도체,TSMC국내,삼성AI파운드리
```

---

## 주의사항

- **종목명 오탐 리스크**: `stock_search`는 네이버 자동완성 API 기반. 정확 매칭(`stock_name == candidate`)으로 필터링하여 "한국", "시장" 같은 일반 명사가 오인되지 않도록 설계함. 다만 "한국"이 실제 종목명으로 존재한다면 오탐 가능. 감지 결과를 처음 1~2주 모니터링하여 패턴 조정 필요할 수 있음.
- **네이버 API 호출 제한**: 키워드당 5건 × 키워드 수 × 테마 수. 10개 테마 × 5개 키워드 = 주 50회 호출 (일일 할당량 내 충분).
- **스캔 시간**: 종목 검증을 위해 stock_search를 순차 호출하므로, 10개 테마 기준 2~5분 소요 예상. 필요 시 `asyncio.gather`로 병렬화 가능.
- **알림 스팸 방지**: `theme_detection` 테이블에 감지 이력 저장. 같은 종목+테마 조합은 재알림 안 함.
- **오래된 감지 이력 정리**: 필요 시 `_cleanup_old_data`에 `theme_detection` 테이블의 N개월 이상 된 레코드 삭제 로직 추가 가능 (향후 고도화).
- **세션 관리 패턴**: `watchlist_service`와 동일하게 session 외부 주입 패턴 사용. CRUD는 session 인자 받고, 스캐너 진입점에서만 `async_session()` 사용.
- **CASCADE 안전장치**: 모델에는 `ondelete="CASCADE"`를 선언했지만, SQLite는 기본적으로 `PRAGMA foreign_keys=OFF` 상태일 수 있음. `remove_theme` 함수에서 `ThemeDetection`을 명시적으로 먼저 삭제하도록 구현하여 FK 설정과 무관하게 동작 보장.
- 코드 변경 전 반드시 현재 코드를 확인하고 Ko~님에게 보고 후 승인받을 것.
