# InvestBrief — 아카이브 기반 테마 자동 발굴 지시서

## 목표

InvestBrief에 누적된 **일일 브리프 아카이브**(news_raw, disclosures, news_summary)를 활용하여 **새로운 테마와 부상 종목을 자동 발굴**하는 기능 추가.

### 두 기능의 관계

```
Tier 1: 키워드 스캐너 (THEME_RADAR) — 이미 작성됨
  Ko~님이 정의한 키워드로 신규 수혜주 발굴

Tier 2: 아카이브 테마 발굴 (이번 지시서)
  누적 데이터에서 AI가 "시장이 말하는 테마"를 자동 감지
```

### 동작 시나리오

```
[매주 일요일 09:00 — 자동 실행]
  → 최근 30일 아카이브 조회 (news_raw, disclosures, news_summary)
  → 종목명 빈도 통계 + 키워드 클러스터링
  → Claude API로 "부상 테마 3~5개" 분석
  → 각 테마별 수혜 종목 정리
  → 텔레그램 주간 리포트 발송

[Ko~님이 수동 실행]
  /theme-discover 30     → 최근 30일 분석
  /theme-discover 7      → 최근 7일 분석
  /theme-trending        → 부상 중인 종목 빈도 TOP 10
```

---

## 수정 1: cleanup 정책 완화 (90일 → 180일)

파일: `backend/app/services/scheduler.py`

**이유:** 테마 발굴은 **누적 데이터가 많을수록 정확**합니다. 90일로는 계절성, 장기 트렌드 포착이 어렵습니다.

현재:
```python
async def _cleanup_old_data():
    """90일 이전 데이터 삭제"""
    try:
        cutoff = date.today() - timedelta(days=90)
```

수정:
```python
async def _cleanup_old_data():
    """180일 이전 데이터 삭제 — 테마 발굴용 누적 데이터 확보"""
    try:
        cutoff = date.today() - timedelta(days=180)
```

**저장 공간 영향:** 1일당 약 50KB (news_raw 20건 + disclosures) × 180일 = 약 9MB. 무시 가능.

---

## 수정 2: 아카이브 분석 서비스 신규 생성

파일: `backend/app/services/theme_discovery_service.py` (신규)

```python
"""아카이브 기반 테마 자동 발굴 — 누적 뉴스/공시에서 AI가 테마 감지"""
from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import date, timedelta
from typing import Any

import anthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session
from app.models.brief import DailyBrief
from app.collectors.stock_search import search_stocks
from app.services import telegram_service

logger = logging.getLogger(__name__)

# 종목명 추출 정규식 (THEME_RADAR와 동일)
STOCK_NAME_PATTERN = re.compile(r"([가-힣][가-힣A-Za-z0-9]{1,14})")

# 불용어 — 종목명 오탐 방지
STOPWORDS = {
    "한국", "미국", "중국", "일본", "유럽", "코스피", "코스닥",
    "증시", "시장", "투자", "기업", "정부", "대통령", "장관", "위원회",
    "분석", "전망", "예상", "발표", "공시", "뉴스", "기사", "매출", "실적",
    "영업이익", "순이익", "주가", "주식", "종목", "거래", "상승", "하락",
    "오늘", "내일", "어제", "금주", "이번", "지난", "최근",
}


# ── 데이터 조회 ──────────────────────────────────────────────────────


async def _get_recent_archives(
    session: AsyncSession, days: int
) -> list[DailyBrief]:
    """최근 N일 브리프 아카이브 조회"""
    cutoff = date.today() - timedelta(days=days)
    result = await session.execute(
        select(DailyBrief)
        .where(DailyBrief.date >= cutoff)
        .order_by(DailyBrief.date.desc())
    )
    return list(result.scalars().all())


# ── 종목 빈도 분석 ───────────────────────────────────────────────────


async def analyze_stock_frequency(days: int = 30) -> list[dict[str, Any]]:
    """최근 N일 동안 뉴스에서 가장 많이 언급된 종목 TOP 20"""
    async with async_session() as session:
        archives = await _get_recent_archives(session, days)

    if not archives:
        return []

    # 1. 모든 뉴스 제목에서 종목명 후보 추출
    name_counter: Counter[str] = Counter()
    name_dates: dict[str, set[str]] = {}  # 종목명 → 언급 날짜 집합

    for brief in archives:
        news_raw = brief.news_raw or []
        date_str = brief.date.isoformat()
        for news in news_raw:
            title = news.get("title", "")
            candidates = set(STOCK_NAME_PATTERN.findall(title))
            for candidate in candidates:
                if candidate in STOPWORDS or len(candidate) < 2:
                    continue
                name_counter[candidate] += 1
                name_dates.setdefault(candidate, set()).add(date_str)

    # 2. 상위 50개 후보만 종목코드 검증 (API 호출 절약)
    top_candidates = name_counter.most_common(50)
    verified: list[dict[str, Any]] = []

    for name, count in top_candidates:
        try:
            matches = await search_stocks(name, limit=1)
        except Exception:
            continue
        if not matches or matches[0].get("stock_name") != name:
            continue

        verified.append({
            "stock_code": matches[0]["stock_code"],
            "stock_name": name,
            "mention_count": count,
            "unique_days": len(name_dates[name]),
            "period_days": days,
        })

        if len(verified) >= 20:
            break

    # mention_count 내림차순 정렬
    verified.sort(key=lambda x: x["mention_count"], reverse=True)
    return verified


# ── AI 기반 테마 발굴 ────────────────────────────────────────────────


async def discover_themes(days: int = 30) -> dict[str, Any]:
    """최근 N일 아카이브를 Claude API에 보내 테마 자동 발굴"""
    async with async_session() as session:
        archives = await _get_recent_archives(session, days)

    if not archives:
        return {"error": "분석할 아카이브가 없습니다."}

    if not settings.anthropic_api_key:
        return {"error": "Anthropic API 키가 설정되지 않았습니다."}

    # 1. 데이터 압축 — 뉴스 제목만 추출 (토큰 절약)
    news_titles: list[str] = []
    disclosure_titles: list[str] = []
    ai_summaries: list[str] = []

    for brief in archives:
        date_str = brief.date.isoformat()
        # 뉴스 제목 (상위 10건만)
        for news in (brief.news_raw or [])[:10]:
            title = news.get("title", "")
            if title:
                news_titles.append(f"[{date_str}] {title}")
        # 공시 제목 (상위 5건만)
        for disc in (brief.disclosures or [])[:5]:
            title = disc.get("title", "") or disc.get("report_nm", "")
            if title:
                disclosure_titles.append(f"[{date_str}] {title}")
        # AI 요약 (첫 200자만)
        if brief.news_summary:
            ai_summaries.append(f"[{date_str}] {brief.news_summary[:200]}")

    # 2. Claude API 프롬프트 구성
    prompt = _build_theme_discovery_prompt(
        days, news_titles, disclosure_titles, ai_summaries
    )

    # 3. Claude API 호출
    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model=settings.ai_model,
            max_tokens=2000,  # 테마 발굴은 상세 분석이 필요 — 기본값보다 큼
            messages=[{"role": "user", "content": prompt}],
        )
        analysis = response.content[0].text
        logger.info(
            "테마 발굴 완료 (%d tokens, %d days)",
            response.usage.output_tokens, days,
        )
    except anthropic.RateLimitError:
        return {"error": "Claude API 호출 한도 초과 — 잠시 후 재시도해주세요."}
    except Exception:
        logger.exception("테마 발굴 실패")
        return {"error": "테마 발굴 중 오류 발생"}

    return {
        "days": days,
        "archive_count": len(archives),
        "news_count": len(news_titles),
        "disclosure_count": len(disclosure_titles),
        "analysis": analysis,
    }


def _build_theme_discovery_prompt(
    days: int,
    news_titles: list[str],
    disclosure_titles: list[str],
    ai_summaries: list[str],
) -> str:
    """테마 발굴용 Claude 프롬프트 구성"""
    # 토큰 제한 고려 — 각 리스트 최대 길이 제한
    news_section = "\n".join(news_titles[:300])  # 최대 300건
    disclosure_section = "\n".join(disclosure_titles[:100])
    summary_section = "\n\n".join(ai_summaries[:30])

    return f"""당신은 한국 주식 시장 테마 분석 전문가입니다.

다음은 최근 {days}일간 한국 증시 관련 뉴스 제목, DART 공시 제목, 그리고 일일 AI 요약입니다.

이 데이터에서 **부상 중인 투자 테마**와 **수혜 종목**을 발굴해주세요.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📰 뉴스 제목 (최근 {days}일):
{news_section}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 DART 공시 제목:
{disclosure_section}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🤖 일일 AI 요약:
{summary_section}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

다음 형식으로 답변하세요:

## 📈 부상 중인 테마 (3~5개)

각 테마에 대해:

### 1. [테마명]
- **부상 근거**: 왜 이 테마가 주목받는지 (2~3줄)
- **핵심 키워드**: 해당 테마를 관통하는 키워드 3~5개
- **수혜 종목**: 뉴스/공시에 등장한 관련 종목 (종목명만 나열, 최대 5개)
- **모멘텀 강도**: 🔥🔥🔥 (강함) / 🔥🔥 (중간) / 🔥 (약함)

## ⚠️ 주의 섹터

단기적으로 하방 압력을 받고 있는 섹터가 있다면 1~2개만 간단히.

## 💡 한 줄 인사이트

이 {days}일간 시장을 관통하는 핵심 스토리를 한 줄로.

---

**중요 규칙:**
- 뉴스에 **실제로 등장한** 종목/키워드만 사용. 추측 금지.
- 이미 누구나 아는 테마(예: "반도체 수혜")는 제외. **새롭게 부상 중인** 것 중심.
- 수혜 종목은 뉴스 제목이나 공시에 명시적으로 나온 것만 포함.
- 서론/결론 없이 위 형식대로 바로 작성."""


# ── 텔레그램 리포트 ─────────────────────────────────────────────────


async def send_weekly_theme_report() -> None:
    """주간 테마 발굴 리포트 (스케줄러에서 호출)"""
    logger.info("주간 테마 발굴 리포트 시작")

    # 30일 기간 분석
    result = await discover_themes(days=30)

    if "error" in result:
        await telegram_service.send_text(
            f"⚠️ 주간 테마 발굴 실패: {result['error']}"
        )
        return

    # 종목 빈도 TOP 10 추가
    top_stocks = await analyze_stock_frequency(days=30)

    # 메시지 조립
    def escape(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    parts = [
        "🎯 <b>주간 테마 발굴 리포트</b>",
        f"(최근 {result['days']}일 · 뉴스 {result['news_count']}건 · 공시 {result['disclosure_count']}건 분석)",
        "",
        escape(result["analysis"]),
    ]

    if top_stocks:
        parts.append("")
        parts.append("━━━━━━━━━━━━━━━━━━━━")
        parts.append("📊 <b>언급 빈도 TOP 10 (최근 30일)</b>")
        parts.append("")
        for i, s in enumerate(top_stocks[:10], 1):
            parts.append(
                f"{i}. <b>{escape(s['stock_name'])}</b> ({s['stock_code']}) "
                f"— {s['mention_count']}회 · {s['unique_days']}일 언급"
            )

    message = "\n".join(parts)

    # 텔레그램 메시지 길이 제한 (4096자) — 초과 시 분할
    await _send_long_message(message)


async def _send_long_message(text: str, max_length: int = 4000) -> None:
    """긴 메시지를 분할해서 텔레그램 전송"""
    if len(text) <= max_length:
        await telegram_service.send_text(text)
        return

    # 줄 단위로 분할
    lines = text.split("\n")
    current = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1  # +1 for \n
        if current_len + line_len > max_length:
            if current:
                await telegram_service.send_text("\n".join(current))
            current = [line]
            current_len = line_len
        else:
            current.append(line)
            current_len += line_len

    if current:
        await telegram_service.send_text("\n".join(current))
```

---

## 수정 3: 스케줄러에 주간 테마 발굴 job 추가

파일: `backend/app/services/scheduler.py`

### 3-1. import 추가

기존 import 블록에 추가:
```python
from app.services import theme_discovery_service
```

### 3-2. 주간 테마 발굴 함수 추가

기존 job 함수들 근처에 추가:

```python
async def _weekly_theme_discovery():
    """주 1회 아카이브 기반 테마 발굴 (매주 일요일 09:00)"""
    logger.info("주간 테마 발굴 시작")
    try:
        await theme_discovery_service.send_weekly_theme_report()
        logger.info("주간 테마 발굴 완료")
    except Exception:
        logger.exception("주간 테마 발굴 실패")
```

### 3-3. `start_scheduler`에 job 등록

기존:
```python
scheduler.add_job(_cleanup_old_data, "cron", hour=18, minute=0, id="cleanup")
```

위에 추가 (THEME_RADAR 지시서의 `_weekly_theme_scan`과 별도 시점):
```python
scheduler.add_job(
    _weekly_theme_discovery, "cron",
    day_of_week="sun", hour=9, minute=0,
    id="weekly_theme_discovery",
)
scheduler.add_job(_cleanup_old_data, "cron", hour=18, minute=0, id="cleanup")
```

로그 메시지 업데이트:
```python
logger.info(
    "스케줄러 시작: %02d:00 브리프 | 12:00 점심체크 | 16:30 일일리포트 | 월 08:00 테마스캔 | 일 09:00 테마발굴 | 18:00 정리",
    hour,
)
```

**실행 타이밍:**
- **월 08:00**: 테마 **스캔** (키워드 → 신규 종목 감지, 즉시 알림)
- **일 09:00**: 테마 **발굴** (아카이브 → AI 분석, 주간 리포트)

---

## 수정 4: 텔레그램 명령어 2개 추가

파일: `backend/app/services/telegram_bot.py`

### 4-1. import 추가

기존 `theme_radar_service` import 블록에 추가:
```python
from app.services import brief_service, daily_report_service, watchlist_service, telegram_service, theme_radar_service, theme_discovery_service
```

### 4-2. 핸들러 함수 추가

```python
async def _handle_theme_discover(args: str) -> str:
    """
    /theme-discover [일수]
    아카이브에서 부상 테마 자동 발굴. 기본 30일.
    """
    # 일수 파싱 (기본 30일)
    days = 30
    if args.strip():
        try:
            days = int(args.strip())
            if days < 7:
                return "최소 7일 이상 분석 가능합니다."
            if days > 180:
                return "최대 180일까지 분석 가능합니다."
        except ValueError:
            return "사용법: /theme-discover [일수]\n예: /theme-discover 30"

    await telegram_service.send_text(
        f"🔍 최근 {days}일 아카이브 분석 중... (Claude API 호출, 30초~1분 소요)"
    )

    result = await theme_discovery_service.discover_themes(days=days)

    if "error" in result:
        return f"❌ {result['error']}"

    # HTML 이스케이프
    def escape(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    message = (
        f"🎯 <b>테마 발굴 결과 ({days}일)</b>\n"
        f"뉴스 {result['news_count']}건 · 공시 {result['disclosure_count']}건 분석\n\n"
        f"{escape(result['analysis'])}"
    )

    await theme_discovery_service._send_long_message(message)
    return ""  # 응답은 이미 위에서 보냈으므로 추가 메시지 없음


async def _handle_theme_trending() -> str:
    """/theme-trending — 최근 30일 언급 빈도 TOP 10 종목"""
    top_stocks = await theme_discovery_service.analyze_stock_frequency(days=30)

    if not top_stocks:
        return "최근 30일 아카이브가 없습니다."

    def escape(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    lines = ["📊 <b>언급 빈도 TOP 10 (최근 30일)</b>", ""]
    for i, s in enumerate(top_stocks[:10], 1):
        lines.append(
            f"{i}. <b>{escape(s['stock_name'])}</b> ({s['stock_code']})\n"
            f"   └ {s['mention_count']}회 언급 · {s['unique_days']}일 노출"
        )

    lines.append("")
    lines.append("💡 /theme-discover 로 AI 테마 분석 가능")

    return "\n".join(lines)
```

### 4-3. COMMAND_HANDLERS에 등록

기존 `/theme-scan` 아래에 추가:

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
    "/theme-discover": _handle_theme_discover,
    "/theme-trending": lambda args: _handle_theme_trending(),
    "/help": _handle_help,
    "/start": _handle_help,
}
```

### 4-4. HELP_TEXT 업데이트

기존 "🎯 테마 선행 스캐너" 섹션에 추가:

```
<b>🔍 아카이브 테마 발굴</b>
/theme-discover [일수] — AI가 부상 테마 자동 발굴 (기본 30일)
/theme-trending — 언급 빈도 TOP 10 종목

매주 일요일 09:00 자동 발굴 리포트 전송
```

---

## 전체 동작 흐름

```
[매주 일요일 09:00 — 자동 실행]
  scheduler._weekly_theme_discovery()
    ↓
  theme_discovery_service.send_weekly_theme_report()
    ↓
  ├── _get_recent_archives(30일)  → DailyBrief 30개 로드
  ├── 뉴스 제목/공시 제목/AI 요약 추출 (토큰 절약)
  ├── Claude API 호출 (max_tokens=2000)
  │   → 프롬프트: "이 데이터에서 부상 테마 3~5개 발굴"
  ├── analyze_stock_frequency(30일)  → 언급 빈도 TOP 10
  └── 텔레그램 리포트 발송 (길이 제한 시 자동 분할)

[텔레그램 리포트 예시]
  🎯 주간 테마 발굴 리포트
  (최근 30일 · 뉴스 324건 · 공시 87건 분석)

  ## 📈 부상 중인 테마

  ### 1. AI 데이터센터 전력 인프라
  - 부상 근거: 테슬라 AI칩 국내 생산 + 북미 데이터센터 전력난
  - 핵심 키워드: 초고압 케이블, 변압기, HVDC, KEMA
  - 수혜 종목: LS에코에너지, LS ELECTRIC, HD현대일렉트릭
  - 모멘텀 강도: 🔥🔥🔥

  ### 2. ...

  📊 언급 빈도 TOP 10 (최근 30일)
  1. 삼성전자 (005930) — 45회 · 28일 언급
  2. LS에코에너지 (229640) — 23회 · 12일 언급
  ...

[수동 실행]
  /theme-discover 60     → 최근 60일 분석 (장기 트렌드)
  /theme-discover 7      → 최근 1주일 분석 (단기 테마)
  /theme-trending        → 빈도 TOP 10만
```

---

## 검증 방법

### 테스트 1: 종목 빈도 분석
```
/theme-trending
→ 📊 언급 빈도 TOP 10
   1. 삼성전자 (005930) — 45회 · 28일 언급
   ...
```

### 테스트 2: 7일 테마 발굴 (단기)
```
/theme-discover 7
→ 🔍 최근 7일 아카이브 분석 중...
→ 🎯 테마 발굴 결과 (7일)
  ## 📈 부상 중인 테마
  ### 1. [AI가 감지한 테마]
  ...
```

### 테스트 3: 90일 테마 발굴 (중기)
```
/theme-discover 90
→ 최근 90일 분석 → 장기 트렌드 포착
```

### 테스트 4: 주간 자동 리포트
- 일요일 09:00 자동 실행 확인 (로그)
- 텔레그램으로 리포트 수신 확인

### 테스트 5: 아카이브 부족 시 처리
```
(DB에 데이터 없는 상태)
/theme-discover
→ ❌ 분석할 아카이브가 없습니다.
```

---

## 주의사항

- **Claude API 비용**: 30일 분석 시 약 2,000~5,000 토큰 소비. 주 1회 자동 실행 + Ko~님 수동 실행 기준 월 3~5만 토큰. 모델이 `claude-sonnet-4-20250514`라 비용 저렴 (약 $0.30/월 예상).
- **max_tokens**: 기본 1,000이 아니라 **2,000으로 상향**. 테마 발굴은 상세 분석이 필요함.
- **토큰 제한**: 프롬프트 자체가 커질 수 있어 뉴스 300건 / 공시 100건 / AI 요약 30일치로 제한. 이 이상은 `discover_themes` 함수 내 로직 수정 필요.
- **종목명 오탐**: STOPWORDS로 흔한 명사 제외 + stock_search 정확 매칭. 그래도 일반 명사가 실제 종목명과 일치하면 오탐 가능.
- **cleanup 정책 변경 영향**: 기존 90일 → 180일. DB 크기 약 9MB로 증가 예상. 필요 시 `cleanup` job에서 주기 조정 가능.
- **THEME_RADAR와의 중복 방지**: 
  - 월요일 08:00 THEME_RADAR (키워드 스캐너) — Ko~님 정의 테마 신규 종목 감지
  - 일요일 09:00 THEME_DISCOVERY (아카이브 발굴) — AI가 새 테마 자동 발굴
  - 두 기능은 **상호 보완적**이며 시점도 다름.
- **통합 사용 시나리오**:
  1. 일요일 09:00 — `/theme-discover` 자동 리포트 수신
  2. 새 테마 발견 → `/theme-add`로 테마 등록
  3. 월요일 08:00부터 해당 테마의 신규 수혜주 자동 스캔
- **텔레그램 4096자 제한**: `_send_long_message`로 자동 분할 처리.
- **코드 변경 전 반드시 현재 코드를 확인하고 Ko~님에게 보고 후 승인받을 것.**

---

## 의존성

본 지시서는 다음 상태를 전제로 함:
- ✅ `STOCKAI_AGENT_TEAM_SETUP.md` 적용 여부 (무관)
- ✅ `INVESTBRIEF_THEME_RADAR.md` 적용 여부 (무관 — 독립 기능이지만 통합 사용 권장)
- ✅ InvestBrief가 정상 동작 중 (일일 브리프 DB 누적 중)

---

## 적용 후 기대 효과

**Week 1~2:** 아카이브 데이터가 적어 분석 품질 낮음
**Week 3~4:** 일일 브리프 30건 누적 → 분석 시작
**Month 2~3:** 60~90일 데이터로 중기 트렌드 포착 가능
**Month 6:** 180일 전체 데이터 활용, 계절성/섹터 로테이션 감지

**LS에코에너지 같은 종목을 어떻게 포착할까?**
- 3월: "전선" 관련 뉴스 산발적 등장 (빈도 낮음)
- 4월 1~10일: LS전선 북미 수주 + LS ELECTRIC 345kV 공급 + LS에코에너지 1분기 실적
- 4월 15일(일) 09:00 자동 리포트: "AI 데이터센터 전력 인프라" 테마 부상 감지, LS계열 종목 3개 언급
- → Ko~님이 `/theme-add "AI 데이터센터 전력" ...`으로 키워드 스캐너 등록
- → 4월 16일 LS에코에너지 KEMA 인증 뉴스 발생
- → 다음 주 월요일 08:00 키워드 스캐너가 즉시 감지 → 알림
