# INVESTBRIEF_INTEGRITY_FIXES.md

> **적용 대상: InvestBrief 레포 단독**
> StockAI에는 적용하지 않는다. (StockAI 쪽 대응은 `STOCKAI_DATE_CONTRACT.md` 별도 지시서 참조 — Phase 1과 짝이지만 독립 실행 가능)

## 목적

코드 리뷰에서 발견된 **로직·정합 문제 4건**을 수정한다. 현재 로컬(맥, localhost:8001)
운영이므로 외부 노출 기반 보안 항목(공개 API 인증·Supabase service_key 등)은 범위 밖이며,
클라우드 상시 배포 시 별도 지시서로 처리한다.

## 적용 순서 (각 Phase 독립 커밋)

| Phase | 항목 | 성격 |
|-------|------|------|
| 1 | TZ 정합 (KST 통일) | 최우선·잠재 결함 선제 제거 |
| 2 | 시총 조회 캐시 + 필터 fail-closed | 속도·외부차단 |
| 3 | GROUP_PREFIX 오탐 차단 | 순수 로직 버그 |
| 4 | 테마 무한 증식 → 승인 게이트 | 운영 누적 |

**반드시 Phase 순서대로 적용 → 검증 → 커밋 → 다음.** 실거래 연동 시스템이므로
한 번에 전부 적용해 "어디서 깨졌는지 모르는" 상태를 만들지 않는다.

## 전체 규칙

- CLAUDE.md의 Simplicity First / Surgical Changes 준수. 명시된 파일만 수정.
- DB 스키마 변경 없음 (전 Phase 공통).
- 각 Phase의 "검증"을 수동 수행하고 결과 보고. 검증 명령의 `backend` 경로는 실제 InvestBrief 레포 경로로 조정.
- macOS 로컬: `python3`/`pip3` 사용.

---

## Phase 1: TZ 정합 — KST 통일

### 1-0. 현재 상태 진단 (먼저 읽을 것)

**StockAI와의 핵심 날짜 계약은 이미 양쪽 KST로 일치한다** — `scan_date` 저장
(`theme_radar_service.py:105` = `datetime.now(KST).date()`)이 StockAI 조회 키와 맞물린다.
즉 맥 TZ가 KST인 한 연동은 정상 동작 중이다.

본 Phase는 "지금 깨진 것"을 고치는 게 아니라, **brief 계열에 남은 naive 호출이
(a) 서버 TZ가 UTC인 환경으로 이전 시 즉시 깨지고 (b) SQLite→Postgres 이전 시
naive/aware 비교 오류를 내는** 잠재 결함을 선제 제거하는 작업이다. 우선순위 최상위인
이유는 어긋나면 "조용히 죽는" 유일한 항목이기 때문이다.

> ⚠️ 이 Phase는 StockAI 쪽 `STOCKAI_DATE_CONTRACT.md`와 짝이다. **InvestBrief의
> scan_date 저장 키(`theme_radar_service.py:105`)는 절대 naive로 바꾸지 말 것** —
> 이 줄이 StockAI 조회 키와의 계약이다. 1-2(D) 제외 목록에 포함되어 있다.

### 1-1. KST 헬퍼 도입

`backend/app/utils/__init__.py`, `backend/app/utils/timezone.py` 신규 생성:

```python
"""KST 시각 헬퍼 — 서버 TZ(UTC 가능)와 무관하게 한국 시간 보장"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def now_kst() -> datetime:
    """KST aware datetime."""
    return datetime.now(KST)


def today_kst() -> date:
    """KST 기준 오늘 날짜."""
    return datetime.now(KST).date()


def now_kst_naive() -> datetime:
    """naive DateTime 컬럼 저장용 — KST 벽시계 값을 tzinfo 없이 반환.

    naive 컬럼(예: ThemeDetection.detected_at)에 들어가는 값과,
    그 컬럼과 비교하는 cutoff를 **동일하게 이 함수로** 생성해야 페어가 깨지지 않는다.
    """
    return datetime.now(KST).replace(tzinfo=None)
```

### 1-2. naive 호출 치환

아래 목록을 **하나씩 판단**하며 치환한다. 무지성 일괄 치환 금지.

**(A) "오늘이 며칠인가" → `today_kst()`:**

| 파일:라인 | 현재 | 비고 |
|-----------|------|------|
| `services/brief_service.py:33` | `date.today()` | brief_date — 핵심 |
| `services/scheduler.py:37` | `date.today()` | 오늘 브리프 조회 |
| `services/scheduler.py:201` | `date.today()` | cleanup cutoff |
| `services/telegram_bot.py:67` | `date.today()` | /today 조회 |
| `api/brief.py:20,50` | `date.today()` | today 조회·생성 |
| `collectors/dart_collector.py:54` | `target_date or date.today()` | 공시 당일 |
| `collectors/news_collector.py:102` | `target_date == date.today()` | is_today 판정 |
| `collectors/price_collector.py:77,111` | `date.today()` | 시세 anchor |
| `services/prefilter_service.py:76` | `date.today()` | 종가 조회 end |
| `services/daily_report_service.py:23,87` | `date.today()` | 리포트 기간 |
| `services/theme_alert_tracker.py:63` | `date.today()` | D+N 추적 cutoff |
| `services/theme_alert_analytics.py:148` | `date.today()` | 월간 집계 |
| `services/theme_discovery_service.py:79` | `date.today()` | 아카이브 cutoff |

**(B) `datetime.now()` (naive timestamp) → `now_kst_naive()`:**

| 파일:라인 | 현재 | 비고 |
|-----------|------|------|
| `services/brief_service.py:73` | `datetime.now()` | created_at |
| `services/scheduler.py:45,58` | `datetime.now()` | sent_at |
| `services/watchlist_service.py:24` | `datetime.now()` | created_at |

**(C) ⚠️ 페어로 함께 바꿔야 하는 곳 — `theme_radar_service.py:257`:**

```python
cutoff = datetime.now() - timedelta(days=DETECTION_WINDOW_DAYS)
```

이 `cutoff`는 `ThemeDetection.detected_at`(naive 컬럼)과 비교된다. **둘 다 함께**
KST-naive로 통일:

1. `cutoff`를 `now_kst_naive() - timedelta(...)`로 변경
2. `models/theme.py`의 `ThemeDetection.detected_at` default를 `now_kst_naive`로 변경
   (`from app.utils.timezone import now_kst_naive`)

한쪽만 바꾸면 SQLite에선 굴러가다 의미가 어긋난다. 반드시 동시 변경.

**(D) 치환 제외 (그대로 둘 것):**

- `theme_radar_service.py:105` `scan_date = datetime.now(KST).date()` — **StockAI 계약 키. 변경 금지**
- 이미 `datetime.now(KST)` 사용 중인 다른 곳 — 동작 동일, 변경 불필요
- `services/us_market/*.py`의 `datetime.now()` (캐시 TTL 경과시간 측정) — TZ 무관. 변경 불필요
- `models/theme.py`의 `ThemeScanRun`(이미 `_now_kst` aware) — 유지

### 1-3. 검증

```bash
cd backend && TZ=UTC python3 -c "
from app.utils.timezone import today_kst, now_kst, now_kst_naive
from datetime import date
print('system date.today():', date.today())
print('today_kst():        ', today_kst())
print('now_kst_naive():    ', now_kst_naive())
"
# KST 22시~자정이면 system과 today_kst 하루 차이 / 낮이면 동일

# 중복 윈도우 페어 정합 — 저장/비교가 같은 naive-KST인지
grep -n "now_kst_naive\|detected_at" backend/app/services/theme_radar_service.py backend/app/models/theme.py

# scan_date 계약 키가 보존됐는지 (변경 금지 확인)
grep -n "scan_date = datetime.now(KST).date()" backend/app/services/theme_radar_service.py
```

---

## Phase 2: 시총 조회 캐시 + 필터 fail-closed

### 2-1. `price_collector.fetch_market_cap` 캐시화

종목당 `fdr.StockListing` 전체 다운로드(20종목=최대 40회)를 일 1회 캐시로 교체:

```python
from datetime import date
from typing import Optional
from app.utils.timezone import today_kst   # Phase 1 헬퍼

_marcap_cache: tuple[Optional[date], dict[str, int]] = (None, {})


def _load_marcap_map() -> dict[str, int]:
    """KOSPI+KOSDAQ 전 종목 시총 맵. 하루 1회만 다운로드."""
    global _marcap_cache
    today = today_kst()
    cached_date, cached_map = _marcap_cache
    if cached_date == today and cached_map:
        return cached_map

    merged: dict[str, int] = {}
    for market in ("KOSPI", "KOSDAQ"):
        try:
            df = fdr.StockListing(market)
        except Exception as e:
            logger.warning("StockListing 실패 (%s): %s", market, e)
            continue
        if df is None or df.empty or "Code" not in df.columns or "Marcap" not in df.columns:
            continue
        for code, marcap in zip(df["Code"], df["Marcap"]):
            try:
                merged[str(code)] = int(marcap)
            except (TypeError, ValueError):
                continue

    if merged:
        _marcap_cache = (today, merged)
    return merged


def fetch_market_cap(stock_code: str) -> Optional[int]:
    """시총(원).

    반환 규약:
    - int > 0: 정상 시총
    - -1: 리스팅 정상 로드됐으나 코드 없음 (비상장/우선주 등)
    - None: 리스팅 자체 로드 실패
    """
    marcap_map = _load_marcap_map()
    if not marcap_map:
        return None
    return marcap_map.get(stock_code, -1)
```

### 2-2. `prefilter_service._check_market_cap_filter` 정책

```python
def _check_market_cap_filter(mcap):
    """F6: 시총 ≥ PREFILTER_MIN_MARKET_CAP.

    정책 (StockAI 매매 파이프라인 입력 — fail-closed):
    - mcap == -1 (코드 없음) → 제외
    - mcap is None (로드 실패) → 제외 + 경고 로그
      ※ 캐시로 스캔당 최대 2회 다운로드 → 실패 확률 낮음.
        실패는 전 종목 동일 적용 → 그날 시그널 0건 = 의도된 안전 동작.
    - mcap < 기준 → 제외
    """
```

`None`과 `-1` 모두 `(False, [사유], ...)`로 변경. **가격 필터 F1~F4는 변경하지 않는다**
(StockAI가 재검증하므로 기존 fail-open 유지).

> 근거: StockAI `validate_absolute_excludes`가 `market_cap==0`을 이미 차단한다.
> 시총 fail-closed는 이중 방어이자 불필요한 batch-analyze 비용 절감.

### 2-3. 검증

```bash
cd backend && python3 -c "
import asyncio, time, logging
logging.basicConfig(level=logging.INFO)
from app.services.prefilter_service import prefilter_stocks

async def main():
    t0 = time.time()
    r = await prefilter_stocks(['005930', '000660', '028260', '999999'])
    print(f'elapsed: {time.time()-t0:.1f}s')
    for code, res in r.items():
        print(code, 'pass' if res.passed else 'reject', res.metrics.get('market_cap'))

asyncio.run(main())
"
# 기대: StockListing 다운로드 스캔당 ≤2회, 999999 reject(-1), 028260 통과
```

---

## Phase 3: GROUP_PREFIX 오탐 차단을 radar에 적용

### 3-1. 공통 상수 모듈 분리

`backend/app/services/stock_name_rules.py` 신규 생성. `theme_discovery_service.py`의
`STOPWORDS`, `GROUP_PREFIX_NAMES`를 **이동**(복사 아님):

```python
"""종목명 추출 공통 규칙 — radar / discovery 공유"""

STOPWORDS = {
    # theme_discovery_service.py 원본 전체 이동
}

GROUP_PREFIX_NAMES = {
    "삼성", "LG", "현대", "SK", "롯데", "한화", "한국", "GS",
    "CJ", "두산", "포스코", "효성", "한진", "신세계", "농심",
    "오리온", "동원", "코오롱", "대상",
}
```

`theme_discovery_service.py`는 자체 정의 삭제 후:
```python
from app.services.stock_name_rules import GROUP_PREFIX_NAMES, STOPWORDS
```
(discovery 동작 100% 동일 — 단순 위치 이동)

### 3-2. `theme_radar_service._scan_single_theme`에 적용

종목명 후보 루프에 추가:

```python
from app.services.stock_name_rules import GROUP_PREFIX_NAMES

        for candidate in candidates:
            if len(candidate) < 2:
                continue
            if candidate in GROUP_PREFIX_NAMES:   # 지주사 오탐 차단
                continue
```

> "한화, 폴란드 수주" → 지주 "한화"(000880) 오탐 차단. 지주사 자체가 수혜주인
> 케이스는 잃지만 빈도·피해 비교상 차단이 옳다.

### 3-3. 검증

```bash
cd backend && python3 -c "
from app.services.theme_radar_service import STOCK_NAME_PATTERN
from app.services.stock_name_rules import GROUP_PREFIX_NAMES
title = '한화·LG, 폴란드 방산 수주 경쟁'
tokens = set(STOCK_NAME_PATTERN.findall(title))
print('추출:', tokens)
print('차단 후:', {t for t in tokens if t not in GROUP_PREFIX_NAMES and len(t) >= 2})
"
# 기대: '한화','LG' 제거

python3 -c "from app.services.theme_discovery_service import GROUP_PREFIX_NAMES, STOPWORDS; print('import OK', len(GROUP_PREFIX_NAMES), len(STOPWORDS))"
```

---

## Phase 4: 테마 무한 증식 → 승인 게이트 + 휴면 비활성화

### 4-1. 자동등록 → 명령어 제안 전환

`theme_discovery_service.auto_register_from_analysis`를 **제안만** 하도록 변경:

- `_extract_themes_from_analysis` 유지 (파싱 재활용)
- `_auto_register_themes` 호출 제거. 추출 테마를 복사-실행 가능 명령어로 포맷:

```
🆕 신규 테마 후보 3건 — 등록하려면 아래 명령을 그대로 보내세요:

/theme-add "유리기판" 유리기판,글라스기판,TGV
/theme-add "전력기기 수출" 변압기,전력기기,HVDC

ℹ️ 기존 테마 1건 스킵: 조선 기자재
```

- 기존 테마명 중복 후보는 스킵 카운트만 표시 (중복판정 로직 재활용)
- `_auto_register_themes`가 호출처 없어지면 삭제 (고아 정리)
- `/theme-discover`(수동) + `send_weekly_theme_report`(자동) 양쪽 적용

### 4-2. 휴면 테마 자동 비활성화 (42일)

`scheduler.py`에 추가:

```python
THEME_DORMANT_DAYS = 42   # 6주 무검출 시 비활성화 (계절성 테마 보호)


async def _deactivate_dormant_themes() -> None:
    """42일 무검출 + 생성 42일 경과한 enabled 테마 비활성화.

    삭제 아닌 enabled=False — 이력 보존, 스캔만 제외. 재활성화는 /theme-add.
    """
    cutoff = now_kst_naive() - timedelta(days=THEME_DORMANT_DAYS)
    deactivated: list[str] = []
    async with async_session() as session:
        themes = (await session.execute(
            select(Theme).where(Theme.enabled == True)  # noqa: E712
        )).scalars().all()
        for t in themes:
            if t.created_at and t.created_at > cutoff:
                continue   # 신생 테마 보호
            recent = (await session.execute(
                select(ThemeDetection.id)
                .where(ThemeDetection.theme_id == t.id)
                .where(ThemeDetection.detected_at >= cutoff)
                .limit(1)
            )).scalar_one_or_none()
            if recent is None:
                t.enabled = False
                deactivated.append(t.name)
        if deactivated:
            await session.commit()

    if deactivated:
        await telegram_service.send_text(
            f"🧹 휴면 테마 {len(deactivated)}건 비활성화 "
            f"(42일 무검출): {', '.join(deactivated)}\n재활성화: /theme-add 재등록"
        )
```

`now_kst_naive`(Phase 1), `timedelta`, `Theme`, `ThemeDetection`, `select` import 확인.
`_weekly_theme_discovery`(월 07:45) 끝에서 호출.

> 42일 근거: ~3개월 데이터 축적 초기 단계라 28일은 분기 실적·정책 사이클 등
> 계절성 테마를 조기에 죽일 위험 → 6주로 완화.

### 4-3. stale 문구 정리

`telegram_bot.py` HELP_TEXT의 "매주 월 08:00 자동 스캔" → "평일 매일 08:10 자동 스캔".
테마 흐름 설명에 "후보 제안 → /theme-add 승인" 반영.

### 4-4. 검증

```bash
# 텔레그램: 1) /theme-discover 30 → 제안 형식 확인
#           2) 한 줄 복사-전송 → 등록 확인
#           3) /theme-list → 테마 수 (수동 등록분 외) 동일 확인

cd backend && python3 -c "
import asyncio
from app.services.scheduler import _deactivate_dormant_themes
asyncio.run(_deactivate_dormant_themes())
print('dormant check 완료')
"
```

---

## 부록 (P2 — 범위 밖, 구현 금지. 기록용)

**클라우드 상시 배포 직전:** 공개 API 인증, Supabase 직결 시 SELECT-only RLS + anon key
**데이터 축적 후:** 검증 프롬프트 보수화, 14일↔7일 윈도우 정합
**기타:** 한국 공휴일 처리, cleanup 대상 확대, 네이버 AC 토큰 캐시

## 커밋 체크리스트

- [ ] Phase 1: `TZ=UTC` 검증 + 페어 grep + scan_date 키 보존 확인 → 커밋
- [ ] Phase 2: StockListing 다운로드 스캔당 ≤2회 → 커밋
- [ ] Phase 3: 토큰 차단 + discovery import OK → 커밋
- [ ] Phase 4: 제안 형식 + 42일 비활성화 동작 → 커밋
- [ ] 전체 후 수동 /theme-scan 1회 정상 + StockAI 08:30 Pull 정상 수신
