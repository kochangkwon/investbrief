# 지시서: /theme-discover 시스템 개선 (권고 1+2+3 v3)

## 📋 개요

본 지시서는 InvestBrief의 `/theme-discover` 명령어 시스템을 3가지 차원에서 개선한다.

### 분석 결과 (theme_discovery_service 정밀 분석)

**현재 평가: 6.5/10**

| 영역 | 점수 | 평가 |
|---|---|---|
| 데이터 활용 | 9/10 | DB 누적 30일 활용 우수 |
| AI 발굴 | 7/10 | 프롬프트 정교, 일관성 약함 |
| 정확도 | 5/10 | 종목코드 매핑 오류 가능 |
| 시스템 통합 | 4/10 | theme_radar와 단절 |

### 본 지시서로 해결되는 3가지 권고

| 권고 | 내용 | 작업 시간 | 효과 |
|---|---|---|---|
| 1 | `/theme-discover` → Theme DB 자동 등록 (수동/자동 모두) | 1.5시간 | 시스템 통합 자동화 |
| 2 | 종목코드 매핑 정확도 개선 | 1시간 | 오탐 90%+ 감소 |
| 3 | 시장 주목 검증 게이트 (전용 프롬프트) | 1시간 | 의미 있는 ✅/⚠️ 마크 |
| 합계 | | **3.5시간** | 6.5 → 8.5 예상 |

### 영향 범위

**수정 파일 (2개):**
- `backend/app/services/theme_discovery_service.py` (메인)
- `backend/app/services/telegram_bot.py` (수동 핸들러 연계)

**참조 파일 (수정 안 함):**
- `backend/app/services/theme_radar_service.py` — 자체 프롬프트로 대체. 재사용 안 함.
- `backend/app/models/theme.py` — Theme 모델 사용 (수정 X)
- `backend/app/services/scheduler.py` — 기존 스케줄 그대로

**기존 동작 유지:**
- 매주 일요일 09:00 자동 실행 — 그대로
- `/theme-discover [일수]` 수동 실행 — **자동 등록 추가**
- 텔레그램 발송 형식 — 그대로 (한 줄 추가)

### v1 → v2 → v3 변경 요약

**v1 결함:** 권고 3에서 `theme_radar_service._verify_theme_match` 재사용 시도. 프롬프트 의미 부적합.

**v2 해결:** 빈도 검증 전용 프롬프트 + 함수를 `theme_discovery_service.py` 내부에 신규 작성.

**v3 변경 (옵션 B):** 수동 `/theme-discover` 실행 시에도 Theme DB 자동 등록 활성화. 공통 헬퍼 함수로 코드 중복 제거.

---

# 권고 1 (v3): /theme-discover → Theme DB 자동 등록 (수동/자동 통합)

## 🎯 목표

AI가 발굴한 테마를 자동으로 Theme 테이블에 등록 → 다음 월요일 08:00 `theme_radar` 자동 스캔에 포함 → 신규 종목 알림 자동 발송 → 측정 인프라(ThemeAlert)에 자동 누적.

**v3 변경 사항:** 수동 `/theme-discover` 실행 시에도 자동 등록 활성화. Ko~님이 즉시 효과 확인 가능.

## 🔬 현재 문제 (v3 기준)

```
현재 흐름:
  ① 일요일 09:00 자동 실행 → AI 발굴 → 텔레그램 발송 → ❌ DB 등록 안 됨
  ② /theme-discover 수동 실행 → AI 발굴 → 텔레그램 발송 → ❌ DB 등록 안 됨
    ↓
  ❌ 월요일 theme_radar 스캔에 포함 안 됨 (사용자 등록 테마만 스캔)
    ↓
  ❌ 측정 인프라(ThemeAlert) 데이터 누적 안 됨
```

**손실:** AI가 발굴한 좋은 테마가 활용되지 않음. 시스템이 단절됨.

## 🛠 수정안 (v3)

### 설계 원칙

수동 실행과 자동 실행이 **같은 자동 등록 로직** 공유. 코드 중복 제거를 위해 공통 헬퍼 함수 사용.

### 수정 위치 1: `theme_discovery_service.py`

#### 사전 준비: import 추가

파일 상단 (line 8 근처) `typing` import에 `Optional` 추가:

**변경 전:**
```python
from typing import Any
```

**변경 후:**
```python
from typing import Any, Optional
```

#### 신규 함수: AI 응답 파싱

`_build_theme_discovery_prompt` 함수 다음, `send_weekly_theme_report` 함수 이전에 추가:

```python
# ── AI 응답 파싱 (v2: 자동 테마 등록용) ──────────────────────────────────


def _extract_themes_from_analysis(analysis: str) -> list[dict[str, Any]]:
    """AI 응답에서 테마명 + 키워드 추출.
    
    파싱 규칙:
    - "### 1. [테마명]" 또는 "### 1. 테마명" 형식 매칭
    - 다음 줄들에서 "**핵심 키워드**:" 라인 찾기
    - 키워드는 쉼표 또는 슬래시로 구분
    
    Returns: [{"name": str, "keywords": list[str]}, ...]
    """
    themes: list[dict[str, Any]] = []
    
    # 테마 헤더: "### 1. 테마명" 또는 "### 1. [테마명]"
    theme_pattern = re.compile(
        r"^###\s+\d+\.\s+\[?([^\]\n]+?)\]?\s*$",
        re.MULTILINE,
    )
    # 키워드 라인: "**핵심 키워드**: 키워드1, 키워드2, 키워드3"
    keyword_pattern = re.compile(
        r"\*\*핵심\s*키워드\*\*\s*:\s*(.+?)(?=\n|$)",
    )
    
    theme_matches = list(theme_pattern.finditer(analysis))
    
    for idx, match in enumerate(theme_matches):
        theme_name = match.group(1).strip()
        if not theme_name or len(theme_name) > 100:
            continue
        
        start = match.end()
        end = theme_matches[idx + 1].start() if idx + 1 < len(theme_matches) else len(analysis)
        section = analysis[start:end]
        
        kw_match = keyword_pattern.search(section)
        if not kw_match:
            logger.warning("테마 '%s' 키워드 파싱 실패 — 스킵", theme_name)
            continue
        
        keyword_str = kw_match.group(1)
        keyword_str = re.sub(r"\*+", "", keyword_str)
        keywords = re.split(r"[,/;]", keyword_str)
        keywords = [k.strip() for k in keywords if k.strip() and len(k.strip()) <= 30]
        
        if not keywords:
            logger.warning("테마 '%s' 키워드 비어있음 — 스킵", theme_name)
            continue
        
        themes.append({
            "name": theme_name,
            "keywords": keywords,
        })
    
    logger.info("AI 응답에서 %d개 테마 추출", len(themes))
    return themes
```

#### 신규 함수: Theme DB 자동 등록

```python
async def _auto_register_themes(themes_data: list[dict[str, Any]]) -> tuple[int, int]:
    """추출된 테마를 Theme DB에 자동 등록.
    
    중복 처리:
    - 동일 name 이미 존재 → 스킵 (사용자 등록 보존)
    - 신규 → Theme(enabled=True)로 추가
    
    Returns: (신규_등록_수, 기존_스킵_수)
    """
    from app.models.theme import Theme  # 지연 import (순환 방지)
    
    if not themes_data:
        return 0, 0
    
    new_count = 0
    skip_count = 0
    
    async with async_session() as session:
        existing_result = await session.execute(select(Theme.name))
        existing_names = set(existing_result.scalars().all())
        
        for theme in themes_data:
            name = theme["name"]
            keywords = theme["keywords"]
            
            if name in existing_names:
                skip_count += 1
                logger.info("테마 자동등록 스킵 (이미 존재): %s", name)
                continue
            
            new_theme = Theme(
                name=name,
                keywords=",".join(keywords),
                enabled=True,
            )
            session.add(new_theme)
            new_count += 1
            logger.info(
                "테마 자동등록: %s (키워드 %d개)",
                name, len(keywords),
            )
        
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("테마 자동등록 commit 실패")
            return 0, skip_count
    
    return new_count, skip_count
```

#### ★ v3 신규: 공통 헬퍼 — 자동 등록 + 결과 메시지 생성

`_auto_register_themes` 다음에 추가:

```python
async def auto_register_from_analysis(analysis: str) -> str:
    """AI 분석 결과에서 테마 추출 + 자동 등록 + 결과 메시지 생성.
    
    수동 (/theme-discover)와 자동 (send_weekly_theme_report) 양쪽에서 호출.
    
    Args:
        analysis: discover_themes()의 result["analysis"] 텍스트
    
    Returns:
        결과 요약 메시지 (텔레그램 메시지에 추가할 1줄). 자동 등록 0개면 빈 문자열.
    """
    try:
        themes_extracted = _extract_themes_from_analysis(analysis)
        if not themes_extracted:
            return ""
        
        new_count, skip_count = await _auto_register_themes(themes_extracted)
        
        if new_count > 0:
            msg = (
                f"\n✅ <b>{new_count}개 테마 자동 등록됨</b> "
                f"(다음 월요일 08:00 자동 스캔 예정)"
            )
            if skip_count > 0:
                msg += f" · 기존 {skip_count}개 스킵"
            return msg
        elif skip_count > 0:
            return f"\nℹ️ 모두 기존 테마 ({skip_count}개)"
        else:
            return ""
    except Exception:
        logger.exception("테마 자동 등록 실패 (발굴 메시지는 정상)")
        return ""
```

#### `send_weekly_theme_report` 수정 (자동 실행)

**변경 전 (line 226-247):**

```python
async def send_weekly_theme_report() -> None:
    """주간 테마 발굴 리포트 (스케줄러에서 호출)"""
    logger.info("주간 테마 발굴 리포트 시작")

    result = await discover_themes(days=30)

    if "error" in result:
        await telegram_service.send_text(
            f"⚠️ 주간 테마 발굴 실패: {result['error']}"
        )
        return

    top_stocks = await analyze_stock_frequency(days=30)
    # ... 기존 메시지 빌드 ...
```

**변경 후 (v3):**

```python
async def send_weekly_theme_report() -> None:
    """주간 테마 발굴 리포트 (스케줄러에서 호출)"""
    logger.info("주간 테마 발굴 리포트 시작")

    result = await discover_themes(days=30)

    if "error" in result:
        await telegram_service.send_text(
            f"⚠️ 주간 테마 발굴 실패: {result['error']}"
        )
        return

    # ★ v3: 공통 헬퍼로 자동 등록 (수동/자동 통합)
    auto_register_summary = await auto_register_from_analysis(result["analysis"])
    
    # 권고 2+3: 빈도 분석 + 시장 주목 검증
    top_stocks, name_titles = await _analyze_stock_frequency_with_titles(days=30)
    
    if top_stocks and settings.anthropic_api_key:
        try:
            top_stocks = await _verify_top_stocks_attention(
                top_stocks=top_stocks,
                sample_news=name_titles,
                days=30,
                verify_count=5,
            )
        except Exception:
            logger.exception("TOP 종목 시장 주목 검증 실패")
    
    # ... (이하 텔레그램 메시지 빌드는 권고 3 섹션 참조)
```

### 수정 위치 2: `telegram_bot.py` (수동 핸들러)

`_handle_theme_discover` 함수 수정 — **공통 헬퍼 호출 추가**.

**변경 전 (line 250-285):**

```python
async def _handle_theme_discover(args: str) -> str:
    """
    /theme-discover [일수]
    아카이브에서 부상 테마 자동 발굴. 기본 30일.
    """
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

    def escape(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    message = (
        f"🎯 <b>테마 발굴 결과 ({days}일)</b>\n"
        f"뉴스 {result['news_count']}건 · 공시 {result['disclosure_count']}건 분석\n\n"
        f"{escape(result['analysis'])}"
    )

    await theme_discovery_service._send_long_message(message)
    return ""
```

**변경 후 (v3):**

```python
async def _handle_theme_discover(args: str) -> str:
    """
    /theme-discover [일수]
    아카이브에서 부상 테마 자동 발굴. 기본 30일.
    
    v3: 자동 등록 활성화 — 발굴된 테마는 Theme DB에 즉시 등록되어
    다음 월요일 08:00 theme_radar 스캔에 포함됨.
    """
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

    # ★ v3: 자동 등록 (수동 실행도 활성화)
    auto_register_summary = await theme_discovery_service.auto_register_from_analysis(
        result["analysis"]
    )

    def escape(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    message = (
        f"🎯 <b>테마 발굴 결과 ({days}일)</b>\n"
        f"뉴스 {result['news_count']}건 · 공시 {result['disclosure_count']}건 분석\n\n"
        f"{escape(result['analysis'])}"
        f"{auto_register_summary}"  # ★ v3 추가: 자동 등록 결과
    )

    await theme_discovery_service._send_long_message(message)
    return ""
```

### 영향 분석 (v3)

**기존 동작 유지:**
- ✅ 매주 일요일 09:00 발송 그대로
- ✅ `/theme-discover [일수]` 동일 사용법
- ✅ 발굴 실패 시 기존 fail-safe 그대로
- ✅ 자동 등록 실패해도 발굴 메시지는 발송 (try-except로 격리)

**신규 동작 (v3):**
- 일요일 09:00 자동 실행 → Theme DB 자동 등록
- **★ /theme-discover 수동 실행 → Theme DB 자동 등록**
- 텔레그램 메시지에 "✅ N개 테마 자동 등록됨" 표시

**리스크:**
- Ko~님이 다양한 일수 (30/60/90)로 테스트 시 같은 테마 여러 번 발굴 가능
- 그러나 `_auto_register_themes`가 **이름 기준 중복 체크**하므로 같은 이름은 1회만 등록됨
- "이미 존재" 메시지 표시 (혼란 방지)

**주의:**
- 수동 실행 시 의도치 않게 등록될 수 있음 → Ko~님이 인지하고 사용 필요
- `/theme-list` 명령어로 등록된 테마 확인 가능
- `/theme-remove` 명령어로 삭제 가능

---

# 권고 2: 종목코드 매핑 정확도 개선

## 🎯 목표

"한화" → 한화(000880, 지주사) 같은 잘못된 매핑 방지. 짧은 그룹명 차단.

## 🔬 현재 문제

`theme_discovery_service.py:78-92`:

```python
for name, count in top_candidates:
    try:
        matches = await search_stocks(name, limit=1)
    except Exception:
        continue
    if not matches or matches[0].get("stock_name") != name:
        continue
    verified.append({...})
```

**문제 1:** 그룹명 단독 매칭 (한화 → 한화 지주사)
**문제 2:** 너무 흔한 그룹명 (삼성, LG, 현대, SK, 롯데)

## 🛠 수정안

### 수정 위치

`backend/app/services/theme_discovery_service.py:22` 근처 (STOPWORDS 다음)

### 신규 상수 추가

```python
# 한국 주요 그룹명 — 단독 등장 시 지주사로 잘못 매핑되므로 차단
# (그룹명 + 후속 단어 결합한 종목명은 정상 매칭됨, 예: "한화에어로스페이스")
GROUP_PREFIX_NAMES = {
    "삼성", "LG", "현대", "SK", "롯데", "한화", "한국", "GS",
    "CJ", "두산", "포스코", "효성", "한진", "신세계", "농심",
    "오리온", "동원", "코오롱", "대상",
}
```

### 함수 변경

`_analyze_stock_frequency_with_titles` 신규 함수에 차단 로직 통합. (권고 3에서 함께 작성)

---

# 권고 3 (v2 재설계 유지): 시장 주목 검증 게이트

## 🎯 목표

빈도 TOP 종목이 **특정 이슈/모멘텀으로 부각**된 것인지, **단순 시장 전반 뉴스에 자주 등장하는 일반 대형주**인지 AI로 구분.

## 🛠 수정안

### 수정 위치 1: 상수 추가

```python
# ── 시장 주목 검증 게이트 (v2 신규) ──────────────────────────────────────

_ATTENTION_VERIFY_MAX_TOKENS = 150
_ATTENTION_VERIFY_TIMEOUT_SEC = 15.0

_VERDICT_RE = re.compile(r"VERDICT:\s*(YES|NO)", re.IGNORECASE)
_REASON_RE = re.compile(r"REASON:\s*(.+?)(?:\n|$)", re.IGNORECASE | re.DOTALL)

_ATTENTION_PROMPT_TEMPLATE = """당신은 한국 주식 시장 분석 전문가입니다.

종목 "{stock_name}"이 최근 {days}일간 뉴스에 {mention_count}회 등장했습니다.
({unique_days}일에 걸쳐 분산 언급)

뉴스 제목 샘플:
{sample_titles}

이 빈도가 **특정 이슈/테마로 인한 시장 주목**인지,
아니면 **단순 시장 전반 뉴스에 자주 등장하는 일반 대형주**인지 판정하세요.

판정 기준:
- **YES**: 특정 호재/모멘텀/실적/수주/정책 이슈로 부각된 종목
- **NO**: 시총 1-2위 시장 전반 뉴스 빈출 종목 (예: 삼성전자, SK하이닉스가 단순 시황 뉴스에 자주 등장)
- **NO**: 부정적 이슈(상폐, 사고, 사기 등)로 자주 언급되는 종목
- 애매하면 보수적으로 NO

출력 형식 (정확히 지켜주세요):
VERDICT: YES
REASON: (1줄 근거)

또는:

VERDICT: NO
REASON: (1줄 근거)
"""
```

### 수정 위치 2: 빈도 분석 함수 (권고 2 차단 + 권고 3 컨텍스트 수집)

```python
async def _analyze_stock_frequency_with_titles(
    days: int = 30,
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """analyze_stock_frequency + 검증 컨텍스트(샘플 제목) 동시 반환.
    
    내부용 (send_weekly_theme_report 전용).
    공개 API(analyze_stock_frequency)는 그대로 유지.
    
    v2 변경:
    - GROUP_PREFIX_NAMES 차단 (권고 2)
    - 단음절 차단 (권고 2)
    - 종목별 샘플 뉴스 제목 수집 (권고 3 검증용)
    """
    async with async_session() as session:
        archives = await _get_recent_archives(session, days)
    
    if not archives:
        return [], {}
    
    name_counter: Counter[str] = Counter()
    name_dates: dict[str, set[str]] = {}
    name_titles: dict[str, list[str]] = {}  # ★ v2 권고 3
    
    for brief in archives:
        news_raw = brief.news_raw or []
        date_str = brief.date.isoformat()
        for news in news_raw:
            title = news.get("title", "")
            candidates = set(STOCK_NAME_PATTERN.findall(title))
            for candidate in candidates:
                if candidate in STOPWORDS or len(candidate) < 2:
                    continue
                # ★ v2 권고 2: 그룹명 차단
                if candidate in GROUP_PREFIX_NAMES:
                    continue
                name_counter[candidate] += 1
                name_dates.setdefault(candidate, set()).add(date_str)
                # ★ v2 권고 3: 검증 컨텍스트용 제목 (최대 3개)
                titles_list = name_titles.setdefault(candidate, [])
                if len(titles_list) < 3:
                    titles_list.append(title)
    
    top_candidates = name_counter.most_common(50)
    verified: list[dict[str, Any]] = []
    
    for name, count in top_candidates:
        # ★ v2 권고 2: 단음절 추가 차단 (동음이의어 위험)
        if len(name) <= 2:
            continue
        
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
    
    verified.sort(key=lambda x: x["mention_count"], reverse=True)
    return verified, name_titles


async def analyze_stock_frequency(days: int = 30) -> list[dict[str, Any]]:
    """공개 API: 빈도 TOP 20만 반환 (외부 호환성 유지)"""
    stocks, _ = await _analyze_stock_frequency_with_titles(days)
    return stocks
```

### 수정 위치 3: 시장 주목 검증 함수

```python
async def _verify_market_attention(
    stock_name: str,
    sample_titles: list[str],
    mention_count: int,
    unique_days: int,
    days: int,
) -> tuple[Optional[bool], str]:
    """이 종목이 특별 이슈로 시장 주목 받는지 판정.
    
    Fail-closed: API key 없음 / 예외 / 파싱 실패 → (None, reason)
    
    Returns: (verdict, reason)
        verdict: True (특별 주목), False (일반 빈출/부정), None (검증 실패)
    """
    if not settings.anthropic_api_key:
        return None, "no api key"
    
    if not sample_titles:
        return None, "no sample"
    
    sample_section = "\n".join(f"- {t}" for t in sample_titles[:3])
    
    prompt = _ATTENTION_PROMPT_TEMPLATE.format(
        stock_name=stock_name,
        days=days,
        mention_count=mention_count,
        unique_days=unique_days,
        sample_titles=sample_section,
    )
    
    try:
        client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            timeout=_ATTENTION_VERIFY_TIMEOUT_SEC,
        )
        response = await client.messages.create(
            model=settings.ai_model,
            max_tokens=_ATTENTION_VERIFY_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text if response.content else ""
    except anthropic.RateLimitError:
        return None, "rate limit"
    except anthropic.APITimeoutError:
        return None, "timeout"
    except Exception as e:
        logger.exception("시장 주목 검증 API 예외: %s", stock_name)
        return None, f"api error: {type(e).__name__}"
    
    verdict_match = _VERDICT_RE.search(raw)
    if not verdict_match:
        logger.warning("시장 주목 검증 파싱 실패: %s", stock_name)
        return None, "parse error"
    
    verdict = verdict_match.group(1).upper() == "YES"
    
    reason_match = _REASON_RE.search(raw)
    reason = reason_match.group(1).strip() if reason_match else "(근거 미파싱)"
    
    return verdict, reason


async def _verify_top_stocks_attention(
    top_stocks: list[dict[str, Any]],
    sample_news: dict[str, list[str]],
    days: int,
    verify_count: int = 5,
) -> list[dict[str, Any]]:
    """TOP N 종목의 시장 주목 여부를 AI로 검증."""
    if not top_stocks:
        return top_stocks
    
    enriched = list(top_stocks)
    
    for stock in enriched[:verify_count]:
        name = stock["stock_name"]
        titles = sample_news.get(name, [])
        
        verdict, reason = await _verify_market_attention(
            stock_name=name,
            sample_titles=titles,
            mention_count=stock["mention_count"],
            unique_days=stock["unique_days"],
            days=days,
        )
        stock["attention_verified"] = verdict
        stock["attention_reason"] = reason
        
        logger.info(
            "시장 주목 검증: %s → %s (%s)",
            name,
            "✅ YES" if verdict is True else ("⚠️ NO" if verdict is False else "? UNVERIFIED"),
            reason,
        )
    
    for stock in enriched[verify_count:]:
        stock["attention_verified"] = None
        stock["attention_reason"] = ""
    
    return enriched
```

### 수정 위치 4: `send_weekly_theme_report` 텔레그램 메시지 빌드

**변경 전 (line 250-260):**

```python
top_stocks = await analyze_stock_frequency(days=30)

# ... (메시지 빌드)

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
```

**변경 후 (v3 권고 1+2+3 통합):**

```python
async def send_weekly_theme_report() -> None:
    """주간 테마 발굴 리포트 (스케줄러에서 호출)"""
    logger.info("주간 테마 발굴 리포트 시작")
    
    result = await discover_themes(days=30)
    
    if "error" in result:
        await telegram_service.send_text(
            f"⚠️ 주간 테마 발굴 실패: {result['error']}"
        )
        return
    
    # ★ v3 권고 1: 자동 등록 (공통 헬퍼)
    auto_register_summary = await auto_register_from_analysis(result["analysis"])
    
    # ★ v2 권고 2+3: 빈도 분석 + 시장 주목 검증
    top_stocks, name_titles = await _analyze_stock_frequency_with_titles(days=30)
    
    if top_stocks and settings.anthropic_api_key:
        try:
            top_stocks = await _verify_top_stocks_attention(
                top_stocks=top_stocks,
                sample_news=name_titles,
                days=30,
                verify_count=5,
            )
        except Exception:
            logger.exception("TOP 종목 시장 주목 검증 실패")
    
    def escape(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    
    parts = [
        "🎯 <b>주간 테마 발굴 리포트</b>",
        f"(최근 {result['days']}일 · 뉴스 {result['news_count']}건 · 공시 {result['disclosure_count']}건 분석)",
        "",
        escape(result["analysis"]),
    ]
    
    # ★ v3: 자동 등록 결과 추가
    if auto_register_summary:
        parts.append(auto_register_summary)
    
    if top_stocks:
        parts.append("")
        parts.append("━━━━━━━━━━━━━━━━━━━━")
        parts.append("📊 <b>언급 빈도 TOP 10 (최근 30일)</b>")
        parts.append("")
        for i, s in enumerate(top_stocks[:10], 1):
            # ★ v2 권고 3: 시장 주목 검증 마크
            attention_mark = ""
            verdict = s.get("attention_verified")
            if verdict is True:
                attention_mark = " ✅"
            elif verdict is False:
                attention_mark = " ⚠️"
            
            parts.append(
                f"{i}. <b>{escape(s['stock_name'])}</b> ({s['stock_code']})"
                f"{attention_mark} — {s['mention_count']}회 · {s['unique_days']}일 언급"
            )
        
        parts.append("")
        parts.append("<i>✅ 특별 이슈로 시장 주목 / ⚠️ 일반 빈출 (TOP 5 검증)</i>")
    
    message = "\n".join(parts)
    await _send_long_message(message)
```

---

# 📋 통합 적용 체크리스트 (v3)

## 적용 순서

```
권고 2 (그룹명 차단) → 권고 3 (시장 주목 검증) → 권고 1 (자동 등록 + 수동 연계)
```

## 권고 2 적용

- [ ] `theme_discovery_service.py:8` typing import에 `Optional` 추가 (`from typing import Any, Optional`)
- [ ] `theme_discovery_service.py:22` 근처에 `GROUP_PREFIX_NAMES` 상수 추가
- [ ] `_analyze_stock_frequency_with_titles` 함수 신규 작성 (그룹명/단음절 차단 포함)
- [ ] `analyze_stock_frequency` 공개 API를 위 함수 호출로 변경

## 권고 3 적용

- [ ] `_ATTENTION_PROMPT_TEMPLATE` 상수 + 정규식 추가
- [ ] `_verify_market_attention` 함수 신규 작성
- [ ] `_verify_top_stocks_attention` 함수 신규 작성

## 권고 1 적용 (v3 — 수동/자동 통합)

- [ ] `_extract_themes_from_analysis` 함수 신규 작성
- [ ] `_auto_register_themes` 함수 신규 작성
- [ ] **★ v3: `auto_register_from_analysis` 공통 헬퍼 함수 신규 작성**
- [ ] `send_weekly_theme_report` — `auto_register_from_analysis` 호출 추가
- [ ] `send_weekly_theme_report` — `_analyze_stock_frequency_with_titles` + `_verify_top_stocks_attention` 호출 추가
- [ ] `send_weekly_theme_report` — 텔레그램 메시지에 자동 등록 결과 + ✅/⚠️ 마크 추가
- [ ] **★ v3: `telegram_bot.py:_handle_theme_discover` — `auto_register_from_analysis` 호출 추가**
- [ ] **★ v3: `telegram_bot.py` 메시지에 자동 등록 결과 추가**

---

# 🔍 검증 방법 (v3)

## 권고 2 검증 (그룹명 차단)

```python
from app.services.theme_discovery_service import GROUP_PREFIX_NAMES

# 그룹명 차단 확인
assert "한화" in GROUP_PREFIX_NAMES
assert "삼성" in GROUP_PREFIX_NAMES

# 결합 종목명 통과 확인
assert "한화에어로스페이스" not in GROUP_PREFIX_NAMES
assert "삼성전자" not in GROUP_PREFIX_NAMES
```

## 권고 3 검증 (시장 주목 검증)

```python
import asyncio
from app.services.theme_discovery_service import _verify_market_attention

# 케이스 1: 특별 이슈 종목
result = asyncio.run(_verify_market_attention(
    stock_name="한화오션",
    sample_titles=[
        "한화오션, 캐나다 잠수함 60조원 수주전 임박",
        "한화오션 1Q 영업이익 컨센 상회",
    ],
    mention_count=35,
    unique_days=18,
    days=30,
))
print(f"한화오션: {result}")  # 기대: (True, "...")

# 케이스 2: 일반 빈출
result = asyncio.run(_verify_market_attention(
    stock_name="삼성전자",
    sample_titles=[
        "코스피 약보합, 삼성전자 외국인 매도",
        "삼성전자 시황 분석",
    ],
    mention_count=50,
    unique_days=25,
    days=30,
))
print(f"삼성전자: {result}")  # 기대: (False, "...")
```

## 권고 1 검증 (자동 등록 — 수동 통합)

### 단위 테스트: 파싱

```python
from app.services.theme_discovery_service import _extract_themes_from_analysis

sample = """## 📈 부상 중인 테마

### 1. AI 데이터센터 전력
- **부상 근거**: 북미 데이터센터 수요 폭증
- **핵심 키워드**: 북미인증, 초고압케이블, 345kV
- **수혜 종목**: HD현대일렉트릭

### 2. [방산 수출]
- **핵심 키워드**: K-방산, 잠수함, CPSP
"""

themes = _extract_themes_from_analysis(sample)
assert len(themes) == 2
assert themes[0]["name"] == "AI 데이터센터 전력"
assert "북미인증" in themes[0]["keywords"]
assert themes[1]["name"] == "방산 수출"  # 대괄호 제거
```

### 통합 테스트: 자동 등록 (수동 실행)

```bash
# 텔레그램에서:
/theme-discover 30

# 결과 메시지 끝에 다음 라인 확인:
# "✅ N개 테마 자동 등록됨 (다음 월요일 08:00 자동 스캔 예정)"

# DB 확인
sqlite3 ~/path/to/investbrief/backend/investbrief.db "
SELECT name, keywords, created_at FROM theme 
ORDER BY created_at DESC LIMIT 10;
"
```

기대: 새 테마 N개 추가됨.

### 통합 테스트: 자동 실행 (스케줄러)

```bash
# 강제 실행 (다음 일요일 안 기다리고)
cd ~/path/to/investbrief/backend
python3 -c "
import asyncio
from app.services.theme_discovery_service import send_weekly_theme_report
asyncio.run(send_weekly_theme_report())
"

# 텔레그램 메시지 형식 확인
# DB 확인 (위와 동일)
```

### 통합 테스트: 다음 월요일 스캔 연계

```bash
# 다음 월요일 08:00 자동 스캔 후
sqlite3 investbrief.db "
SELECT t.name, COUNT(td.id) as detected
FROM theme t
LEFT JOIN theme_detection td ON t.id = td.theme_id
GROUP BY t.id
ORDER BY t.created_at DESC LIMIT 10;
"
```

기대: 자동 등록된 테마에 신규 감지 종목 1개 이상.

### ThemeAlert 측정 인프라 검증

```bash
sqlite3 investbrief.db "
SELECT theme_name, sent_at, candidate_count
FROM theme_alerts
ORDER BY sent_at DESC LIMIT 10;
"
```

기대: `/theme-discover`로 발굴된 테마가 ThemeAlert 테이블에 누적됨.

---

# 📊 적용 후 예상 효과 (v3)

## 시스템 통합 흐름

```
[적용 후 자동 흐름]

★ 진입점 1: 일요일 09:00 자동 실행
  ↓
  send_weekly_theme_report() 호출
  ↓
  AI 발굴 + ★ 자동 등록 + 시장 주목 검증
  ↓
  텔레그램 발송: 발굴 결과 + "✅ 5개 테마 자동 등록됨" + ✅/⚠️ 마크

★ 진입점 2: /theme-discover 30 수동 실행 (v3 신규)
  ↓
  _handle_theme_discover() 호출
  ↓
  AI 발굴 + ★ 자동 등록 (수동도 활성화)
  ↓
  텔레그램 발송: 발굴 결과 + "✅ N개 테마 자동 등록됨"

월요일 08:00:
  /theme-scan 자동 실행 (theme_radar)
  ↓
  Theme DB의 모든 테마 스캔 (자동 등록 + 사용자 등록)
  ↓
  신규 종목 감지 → 알림 + ThemeAlert DB 저장

월말:
  월간 리포트 자동 발송
    "지난달 발굴 5개 테마 평균 수익률 +X%"
```

## 정량 효과

| 항목 | 이전 | 이후 (v3) |
|---|---|---|
| 시스템 통합 | 단절 | 자동 연계 (수동/자동 모두) |
| 사용자 수동 작업 | /theme-add 필요 | **자동 등록 (즉시 효과)** |
| 측정 데이터 누적 | 사용자 등록 테마만 | AI 발굴 테마도 포함 |
| 그룹명 오탐 | 빈번 | 90%+ 감소 |
| TOP 종목 신뢰성 | 빈도만 | AI 검증 마크 |
| 토큰 추가 비용 | $0 | $0.06/월 (무시 수준) |

## 정성 효과

- ✅ Ko~님이 매주 "테마 등록" 수동 작업 불필요
- ✅ **★ /theme-discover 즉시 효과 (다음 일요일 안 기다림)**
- ✅ AI 발굴이 추적되는 데이터로 누적
- ✅ TOP 종목 중 진짜 주목 vs 일반 빈출 구분
- ✅ 1-2개월 후 정확도 분석 가능

---

# ⚠️ 주의 사항 (v3)

## A. 백업 필수

```bash
cd ~/path/to/investbrief
git add -A
git commit -m "[backup] before /theme-discover v3 improvements"

cp backend/investbrief.db backend/investbrief.db.backup_$(date +%Y%m%d)
```

## B. 수동 실행 시 DB 영향 인지

**v3에서 수동 실행도 자동 등록됨.** Ko~님 인지 필요:

- `/theme-discover 30` → 5개 테마 자동 등록 가능
- `/theme-discover 60` → 또 다른 5개 등록 가능 (60일에서 새로 발견된 것)
- `/theme-discover 90` → 또 다른 등록

**중복 방지:** 이름 동일하면 자동 스킵. 그러나 **이름 미세 다르면 별개로 등록**:
- "AI 데이터센터" / "AI 데이터센터 전력" / "AI 데이터 센터" → 3개로 등록

**대응:**
- `/theme-list`로 등록 현황 확인
- 불필요한 테마는 `/theme-remove "테마명"`으로 삭제

## C. AI 응답 형식 의존성

권고 1의 `_extract_themes_from_analysis`는 AI 응답 형식 의존:

```
### 1. 테마명
- **핵심 키워드**: 키워드1, 키워드2, ...
```

**리스크:**
- AI가 응답 형식을 미묘하게 바꾸면 파싱 실패
- 그러나 발굴 메시지는 정상 발송 (try-except로 격리)
- 모니터링: 첫 1-2주 자동 등록 성공률 확인

## D. 권고 3 검증 정확도

권고 3은 "특별 주목 vs 일반 빈출" 판정. AI 판정 100% 정확하지 않을 수 있음:
- 진짜 호재 종목이 ⚠️로 분류 가능
- 보수적 판정 ("애매하면 NO")으로 일부 ✅ 누락 가능

**대응:**
- 1-2개월 데이터 누적 후 정확도 평가
- 필요 시 프롬프트 보정

## E. theme_radar_service.py와의 일관성

본 지시서는 `theme_discovery_service.py`만 수정. `theme_radar_service.py`는 같은 `STOCK_NAME_PATTERN` 사용하지만 수정 안 함.

**향후 검토:** 양쪽 같은 차단 로직 적용 (공통 모듈 추출).

## F. AI 모델 영향

`settings.ai_model = "claude-sonnet-4-20250514"` (현재 설정).

추가 API 호출:
- 발굴 메시지: 기존 1회/주
- 권고 3 검증: 신규 5회/주
- 합계: 주당 6회 → 월 24회 → 약 $0.10/월

→ 무시 가능.

---

# 🚀 Claude Code 적용 명령

```
@/mnt/user-data/outputs/지시서_theme-discover_시스템개선.md 의 지시서를 
InvestBrief 프로젝트에 적용해줘.

작업 환경:
- 프로젝트: ~/path/to/investbrief (실제 경로 확인 후 적용)
- 적용 순서: 권고 2 → 권고 3 → 권고 1 (수동/자동 통합)

각 권고 적용 후:
1. git diff 출력 (변경 사항 확인)
2. Python 문법 검증:
   - python3 -m py_compile backend/app/services/theme_discovery_service.py
   - python3 -m py_compile backend/app/services/telegram_bot.py
3. 다음 권고 진행 전 결과 보고

수정 파일 (2개):
- backend/app/services/theme_discovery_service.py (메인)
- backend/app/services/telegram_bot.py (수동 핸들러)

수정 안 하는 파일:
- theme_radar_service.py (재사용 안 함)
- models/theme.py (Theme 모델 그대로 사용)
- scheduler.py (스케줄 그대로)

주의:
- 작업 전 git commit (백업)
- DB 백업: cp investbrief.db investbrief.db.backup
- analyze_stock_frequency 공개 API 시그니처는 변경 안 함
- 수동/자동 모두 auto_register_from_analysis 공통 헬퍼 사용
```

---

# 📂 수정 파일 종합

## 수정 대상 (2개 파일) ⭐ v3 변경

| 파일 | 권고 1 | 권고 2 | 권고 3 |
|---|---|---|---|
| `theme_discovery_service.py` | 함수 3개 추가 + send_weekly 수정 | GROUP_PREFIX_NAMES + 차단 + _analyze_..._with_titles | _ATTENTION_PROMPT + 함수 2개 |
| **`telegram_bot.py`** | **★ v3: _handle_theme_discover 수정** | - | - |

## 신규 함수 종합 (theme_discovery_service.py)

| 함수 | 권고 | 용도 |
|---|---|---|
| `_extract_themes_from_analysis` | 1 | AI 응답에서 테마명/키워드 추출 |
| `_auto_register_themes` | 1 | Theme DB 자동 등록 (저수준) |
| **`auto_register_from_analysis`** | **1 (v3)** | **공통 헬퍼: 추출 + 등록 + 메시지** |
| `_analyze_stock_frequency_with_titles` | 2 | 빈도 분석 + 샘플 뉴스 (그룹명 차단) |
| `_verify_market_attention` | 3 | 단일 종목 시장 주목 판정 |
| `_verify_top_stocks_attention` | 3 | TOP N 종목 일괄 판정 |

## 변경되는 기존 함수

| 함수 | 파일 | 변경 내용 |
|---|---|---|
| `analyze_stock_frequency` | theme_discovery_service.py | 내부 구현만 변경 (시그니처 유지) |
| `send_weekly_theme_report` | theme_discovery_service.py | auto_register_from_analysis + 검증 호출 |
| `_handle_theme_discover` | telegram_bot.py | **★ v3: auto_register_from_analysis 호출** |

## 신규 상수 종합

| 상수 | 권고 | 용도 |
|---|---|---|
| `GROUP_PREFIX_NAMES` | 2 | 한국 그룹명 차단 |
| `_ATTENTION_VERIFY_MAX_TOKENS` | 3 | 검증 max_tokens (150) |
| `_ATTENTION_VERIFY_TIMEOUT_SEC` | 3 | 검증 timeout (15.0) |
| `_VERDICT_RE` | 3 | YES/NO 파싱 정규식 |
| `_REASON_RE` | 3 | REASON 파싱 정규식 |
| `_ATTENTION_PROMPT_TEMPLATE` | 3 | 검증 전용 프롬프트 |

---

# 📊 본 지시서로 해결되는 문제 종합

## 권고 1 (자동 등록 — 수동/자동 통합) 해결

1. ✅ AI 발굴 → 수동 등록 단절 → 자동 연계
2. ✅ 발굴 결과 한 번 보고 끝 → 측정 인프라 누적
3. ✅ 사용자 수동 작업 → 시스템 자동화
4. ✅ **/theme-discover 수동 실행도 즉시 효과 (v3 신규)**

## 권고 2 (그룹명 차단) 해결

5. ✅ "한화" → 한화(000880) 잘못 매핑 → 차단
6. ✅ TOP 빈도 그룹명 노이즈 → 의미 있는 종목만
7. ✅ 단음절 동음이의어 위험 → 차단

## 권고 3 (시장 주목 검증) 해결

8. ✅ 빈도만으로 TOP 종목 표시 → 시장 주목 검증 마크
9. ✅ 일반 대형주 vs 특별 이슈 종목 구분
10. ✅ v1 결함 (theme_radar 함수 부적합 재사용) → 자체 프롬프트로 해결

---

# 💡 향후 확장 (별도 지시서)

본 지시서로 해결 안 된 부분:

1. **STOCK_NAME_PATTERN 한계** (영문 시작 종목 누락: LG에너지솔루션, SK하이닉스 등)
2. **다중 시간 윈도우 분석** (30일 + 90일 비교)
3. **DART 공시 가중치** (수주공시 vs 단순공시)
4. **테마 지속성 추적** (Theme 모델에 weeks_active 등)
5. **가격 + 수급 데이터 결합** (외국인 매수 확인)
6. **theme_radar_service.py에 GROUP_PREFIX_NAMES 적용** (일관성)

→ 본 지시서 적용 후 1-2개월 운영 데이터 보고 별도 결정.

---

# 🎯 적용 시점 권고

## 즉시 적용 가능
- 권고 2 (그룹명 차단) — 30분
- 권고 3 (시장 주목 검증) — 1시간
- 권고 1 (자동 등록 — v3 통합) — 1.5시간

## 작업 시간
- 총 약 3.5시간 (이전 v2 대비 +30분, telegram_bot.py 수정 추가)

## Ko~님 진행 옵션

**Option 1: 본 지시서 그대로 Claude Code에 적용** ⭐ 권장
**Option 2: 권고 별로 분할 적용** — 점진적 검증
**Option 3: 권고 1만 먼저** — 즉시 시스템 통합 효과 확인

---

# 📋 v1 → v2 → v3 변경 누적 요약

## v1 (초안)

권고 3에서 `theme_radar_service._verify_theme_match` 재사용 시도.

## v2 (검증 후 수정)

**v1 결함:** _verify_theme_match 프롬프트가 빈도 검증과 의미 다름.

**v2 해결:** 빈도 검증 전용 프롬프트 + 함수 신규 작성.

## v3 (사용자 요청 반영)

**v2 한계:** 수동 `/theme-discover` 실행 시 자동 등록 안 됨 (옵션 A 채택).

**v3 변경 (옵션 B):** 
- 수동 실행도 자동 등록 활성화
- 공통 헬퍼 `auto_register_from_analysis` 추가 (코드 중복 제거)
- `telegram_bot.py:_handle_theme_discover`도 수정 대상에 추가

**효과:**
- Ko~님이 즉시 효과 확인 가능 (다음 일요일 안 기다림)
- `/theme-discover 30` → 즉시 Theme DB 등록
- 같은 이름 중복 방지 (자동 스킵)
