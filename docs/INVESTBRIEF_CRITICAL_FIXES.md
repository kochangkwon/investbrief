# INVESTBRIEF_CRITICAL_FIXES.md

## 목적

코드 리뷰에서 발견된 보안·정합성 문제를 수정한다. 우선순위 순서대로 Phase A → F를 적용하며, **Phase A~C는 P0(즉시), D~F는 P1**이다. 각 Phase는 독립적으로 커밋 가능하다.

핵심 문제 요약:

1. **(A)** 공개 API 전체가 무인증 — `POST /api/brief/generate`로 누구나 브리프 삭제 + Claude API 비용 유발 + 텔레그램 발송 가능
2. **(B)** 브리프 계열 코드가 naive `date.today()`/`datetime.now()` 사용 — 서버 TZ가 UTC면 07:30 KST 발송 브리프가 전날 날짜로 저장되어 `/today`가 404
3. **(C)** `fetch_market_cap`이 종목 1개당 `fdr.StockListing` 전체를 다운로드 — 느리고 차단 위험, 실패 시 fail-open으로 시총 필터 무력화
4. **(D)** Claude 검증 프롬프트가 "애매하면 관대하게 YES" — 자동매매(StockAI) 입력으로는 방향이 반대이며, "신규 촉매 여부"를 전혀 묻지 않음
5. **(E)** `GROUP_PREFIX_NAMES` 차단이 discovery에만 있고 radar에 없음 — "한화", "LG", "SK" 등 단독 토큰이 동명의 지주회사로 오탐
6. **(F)** 주간 테마 발굴이 무조건 자동 등록(enabled=True) — 테마 무한 증식, 사람 승인 게이트 필요

## 전체 규칙

- CLAUDE.md의 Simplicity First / Surgical Changes 준수. 각 Phase에서 명시된 파일만 수정한다.
- 기존 테스트가 없으므로, 각 Phase의 "검증" 절차를 수동으로 수행하고 결과를 보고한다.
- DB 스키마 변경 없음 (전 Phase 공통).

---

## Phase A (P0): 공개 API 인증

### A-1. 백엔드 — Admin API Key 의존성

`backend/app/config.py`에 설정 추가:

```python
    # 공개 API 보호용 (프론트엔드 프록시 ↔ 백엔드)
    admin_api_key: str = ""
```

`backend/app/api/auth.py` 신규 생성 (internal/auth.py와 동일 패턴):

```python
"""공개 API 인증 — 프론트엔드 프록시와 공유하는 Admin Key 검증"""
from __future__ import annotations

import secrets
from typing import Optional

from fastapi import Header, HTTPException, status

from app.config import settings


async def verify_admin_api_key(
    x_admin_api_key: Optional[str] = Header(default=None, alias="X-Admin-API-Key"),
) -> None:
    """`X-Admin-API-Key` 헤더 검증 (타이밍 공격 방지)."""
    expected = settings.admin_api_key

    if not expected:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ADMIN_API_KEY not configured on server",
        )
    if not x_admin_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Admin-API-Key header",
        )
    if not secrets.compare_digest(x_admin_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
```

라우터 레벨로 적용 — `brief.py`, `watchlist.py`, `stock.py` 세 파일의 `APIRouter(...)` 생성부에 의존성 추가:

```python
from app.api.auth import verify_admin_api_key

router = APIRouter(
    prefix="/api/brief",
    tags=["brief"],
    dependencies=[Depends(verify_admin_api_key)],
)
```

적용 범위:
- ✅ `/api/brief/*`, `/api/watchlist/*`, `/api/stock/*` — 전부 보호 (GET 포함. 브리프 내용도 개인 투자 데이터)
- ❌ `/health` — 보호하지 않음 (헬스체크용)
- ❌ `/api/internal/*` — 기존 `STOCKAI_INTERNAL_API_KEY` 유지, 변경 없음

### A-2. 프론트엔드 — rewrite를 서버사이드 프록시로 교체

현재 `next.config.ts`의 rewrites는 헤더를 추가할 수 없으므로 Route Handler 프록시로 교체한다. **클라이언트 코드(`lib/api.ts`, 컴포넌트)는 수정하지 않는다** — 상대경로 `/api/...` 호출이 그대로 동작해야 한다.

`next.config.ts`: rewrites 블록 제거.

`frontend/src/app/api/[...path]/route.ts` 신규 생성:

```typescript
import { NextRequest } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8001";
const ADMIN_API_KEY = process.env.ADMIN_API_KEY ?? "";

async function proxy(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  const search = req.nextUrl.search;
  const url = `${BACKEND_URL}/api/${path.join("/")}${search}`;

  const init: RequestInit = {
    method: req.method,
    headers: {
      "Content-Type": req.headers.get("content-type") ?? "application/json",
      "X-Admin-API-Key": ADMIN_API_KEY,
    },
    cache: "no-store",
  };
  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = await req.text();
  }

  const res = await fetch(url, init);
  const body = await res.text();
  return new Response(body, {
    status: res.status,
    headers: { "Content-Type": res.headers.get("content-type") ?? "application/json" },
  });
}

export { proxy as GET, proxy as POST, proxy as DELETE, proxy as PUT, proxy as PATCH };
```

주의: `ADMIN_API_KEY`는 `NEXT_PUBLIC_` 접두사를 **절대 붙이지 않는다** (클라이언트 번들에 노출됨). 서버 전용 env로만 사용.

### A-3. 환경변수

`backend/.env.example`과 `.env.template`에 추가:

```
# 공개 API 보호 (프론트엔드 프록시와 동일 값)
# 생성: openssl rand -hex 32
ADMIN_API_KEY=
```

프론트엔드용 env 안내 주석 추가 (Vercel 환경변수 + 로컬 `.env.local`):

```
BACKEND_URL=http://168.107.9.146:8001   # 또는 백엔드 주소
ADMIN_API_KEY=                          # 백엔드와 동일 값
```

### A-4. 검증

```bash
# 키 없이 → 401
curl -i http://localhost:8001/api/brief/today
curl -i -X POST http://localhost:8001/api/brief/generate

# 키 포함 → 200/404
curl -i -H "X-Admin-API-Key: $ADMIN_API_KEY" http://localhost:8001/api/brief/today

# internal API 기존 동작 유지 확인
curl -i -H "X-Internal-API-Key: $STOCKAI_INTERNAL_API_KEY" \
  "http://localhost:8001/api/internal/theme-scan/results?require_completed=false"

# 프론트: localhost:3001 접속 → 대시보드/아카이브/관심종목 정상 렌더 확인
```

### A-5. 배포 노트 (코드 외 — 사용자 수동 작업)

Oracle Cloud Security List에서 8001 포트 인바운드를 가능하면 차단하고, 프론트(Vercel) → 백엔드 통신만 허용하는 것이 이상적이나 Vercel IP가 고정이 아니므로 본 Phase의 키 인증이 1차 방어선이다. 최소한 8001 포트가 0.0.0.0/0에 열려 있는지 확인할 것.

---

## Phase B (P0): 시간대 KST 통일

### B-1. 헬퍼 모듈

`backend/app/utils/__init__.py`, `backend/app/utils/timezone.py` 신규 생성:

```python
"""KST 시각 헬퍼 — 서버 TZ(UTC 가능)와 무관하게 한국 시간 보장"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def now_kst() -> datetime:
    return datetime.now(KST)


def today_kst() -> date:
    return datetime.now(KST).date()
```

### B-2. naive 호출 치환

다음 파일들에서 `date.today()` → `today_kst()`, `datetime.now()` → `now_kst()`로 치환한다. **치환 전 반드시 `grep -rn "date.today()\|datetime.now()" backend/app/`로 전체 목록을 뽑아 하나씩 판단**할 것. 기준:

- **치환 대상**: "오늘이 며칠인가"를 묻는 모든 곳 — `scheduler.py`(`_is_weekday`, `_generate_and_send`, `_cleanup_old_data`), `brief_service.py`(brief_date, created_at, sent_at), `telegram_bot.py`(`_handle_today`), `api/brief.py`(`get_today_brief`), `news_collector.py`(`get_today_news`의 `is_today` 판정), `watchlist_service.py`, `daily_report_service.py`, `theme_alert_tracker.py`, `prefilter_service.py`(`_fetch_closes_sync`의 `end = date.today()`), `theme_discovery_service.py`(`_get_recent_archives`)
- **치환 제외**: `theme_radar_service.py`, `models/theme.py` 등 이미 `datetime.now(KST)` 사용 중인 곳 — 단, 기존 자체 `KST = ZoneInfo(...)` 선언은 새 헬퍼 import로 정리해도 좋으나 동작 변경은 없어야 함
- **주의**: `theme_radar_service.py`의 중복 검증 윈도우 `cutoff = datetime.now() - timedelta(...)`는 naive인데, 비교 대상 `ThemeDetection.detected_at`(naive, 서버 로컬)과 페어다. 이 페어는 **둘 다 함께** naive-KST 기준으로 바꾸거나(권장: `now_kst().replace(tzinfo=None)`로 naive-KST 통일), 둘 다 그대로 두거나 해야 한다. 한쪽만 aware로 바꾸면 SQLite에선 굴러가다 Postgres 이전 시 비교 오류가 난다. DB 저장 컬럼(naive DateTime)에 들어가는 값은 `now_kst().replace(tzinfo=None)` 패턴으로 naive-KST를 저장한다.

### B-3. 검증

```bash
# 서버 TZ를 UTC로 강제하고 테스트
TZ=UTC python3 -c "
from app.utils.timezone import today_kst, now_kst
from datetime import date
print('system date.today():', date.today())
print('today_kst():', today_kst())
"
# KST 22시 이후~자정 사이에 두 값이 달라지는 것 확인 (낮이면 동일)

# 수동 브리프 생성 후 저장된 date가 KST 기준 오늘인지 확인
sqlite3 investbrief.db "SELECT date, created_at FROM daily_brief ORDER BY id DESC LIMIT 1;"
```

배포 후 운영 서버에서 `timedatectl` 확인. UTC라도 본 Phase 적용으로 무관해지지만, 결과를 보고할 것.

---

## Phase C (P0): 시총 조회 캐시 + 시총 필터 fail-closed

### C-1. `price_collector.fetch_market_cap` 리팩토링

종목당 `fdr.StockListing` 호출을 **일 단위 모듈 캐시**로 교체:

```python
# 모듈 레벨 캐시: (조회일, {code: marcap})
_marcap_cache: tuple[Optional[date], dict[str, int]] = (None, {})


def _load_marcap_map() -> dict[str, int]:
    """KOSPI+KOSDAQ 전 종목 시총 맵. 하루 1회만 다운로드."""
    global _marcap_cache
    today = date.today()  # Phase B 적용 시 today_kst()
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
    """시총(원). 리스팅 로드 실패 시 None, 리스팅엔 있으나 종목 없으면 -1.

    반환 규약:
    - int > 0: 정상 시총
    - -1: 리스팅은 정상 로드됐으나 해당 코드 없음 (KOSPI/KOSDAQ 비상장 등) → 호출 측 제외 권장
    - None: 리스팅 자체 로드 실패 → 호출 측 정책 판단
    """
    marcap_map = _load_marcap_map()
    if not marcap_map:
        return None
    return marcap_map.get(stock_code, -1)
```

기존 시그니처(`Optional[int]`)는 유지하되 `-1` 센티널을 추가한다. docstring에 규약을 명시할 것.

### C-2. `prefilter_service._check_market_cap_filter` 정책 변경

```python
def _check_market_cap_filter(mcap):
    """F6: 시총 ≥ PREFILTER_MIN_MARKET_CAP.

    정책 (StockAI 매매 파이프라인 입력 기준):
    - mcap == -1 (리스팅에 코드 없음) → 제외 (fail-closed)
    - mcap is None (리스팅 로드 자체 실패) → 제외 (fail-closed) + 경고 로그
      ※ 캐시 도입으로 스캔당 최대 2회 다운로드라 실패 확률이 낮아짐.
        리스팅 실패는 전 종목에 동일 적용되므로 그날 시그널 0건 = 의도된 안전 동작.
    - mcap < 기준 → 제외
    """
```

위 정책대로 None과 -1 모두 `(False, [사유], ...)` 반환으로 변경. F1~F4(가격 데이터 부족 시 보수적 통과)는 **변경하지 않는다** — 가격 필터는 StockAI pipeline_agent가 어차피 재검증하므로 기존 fail-open 유지.

### C-3. 검증

```bash
cd backend && python3 -c "
import asyncio, time
from app.services.prefilter_service import prefilter_stocks

async def main():
    t0 = time.time()
    r = await prefilter_stocks(['005930', '000660', '028260', '999999'])
    print(f'{time.time()-t0:.1f}s')
    for code, res in r.items():
        print(code, res.passed, res.reasons, res.metrics.get('market_cap'))

asyncio.run(main())
"
# 기대: 두 번째 실행부터 리스팅 재다운로드 없음 (로그로 확인),
#       999999는 mcap=-1로 제외, 028260(삼성물산)은 시총 통과
```

---

## Phase D (P1): Claude 검증 프롬프트 보수화 + 신규 촉매 축 추가

### D-1. `theme_radar_service._VERIFY_PROMPT_TEMPLATE` 교체

**파서(`ai_verifier`)는 수정하지 않는다.** 출력 형식 `VERDICT: YES/NO` + `REASON:`은 그대로 유지. 프롬프트만 다음 방향으로 재작성:

```python
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
- 종목의 **주력 사업**이 이 테마와 직접 관련 있어야 함
- 그룹 지주회사가 계열사 이슈로 언급된 경우는 NO (예: 방산 뉴스의 "한화"는 한화에어로스페이스가 수혜주이지 지주사 한화가 아님)
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
```

### D-2. 검증

수동 스캔(텔레그램 `/theme-scan`)을 1회 실행하고, 로그의 `테마 검증:` 라인에서 YES/NO 비율 변화를 확인한다. 기존 대비 YES 비율이 유의미하게 줄어야 정상. 변경 전후 비율을 보고할 것.

> 참고: 프롬프트 강화로 통과 종목 수가 일시적으로 급감할 수 있다. 이는 의도된 동작이며, 1~2주 운영 후 D+30 추적 데이터로 정밀도를 재평가한다.

---

## Phase E (P1): GROUP_PREFIX_NAMES를 radar에 적용

### E-1. 공통 상수 모듈 분리

`backend/app/services/stock_name_rules.py` 신규 생성. `theme_discovery_service.py`의 `STOPWORDS`, `GROUP_PREFIX_NAMES`를 이 모듈로 **이동**(복사 아님)하고 discovery에서는 import로 변경.

### E-2. `theme_radar_service._scan_single_theme` 후보 필터에 적용

종목명 후보 루프에 차단 추가:

```python
from app.services.stock_name_rules import GROUP_PREFIX_NAMES

        for candidate in candidates:
            if len(candidate) < 2:
                continue
            if candidate in GROUP_PREFIX_NAMES:   # 지주사 오탐 차단
                continue
```

> 정책 메모: 지주회사 자체가 테마 수혜주인 케이스(예: 지배구조 테마의 "LG")는 이 차단으로 잃게 되지만, 빈도와 피해 크기를 비교하면 차단이 옳다. Phase D의 프롬프트에도 지주사 규칙이 들어가 이중 방어가 된다.

### E-3. 검증

```bash
cd backend && python3 -c "
import re
from app.services.theme_radar_service import STOCK_NAME_PATTERN
from app.services.stock_name_rules import GROUP_PREFIX_NAMES
title = '한화·LG, 폴란드 방산 수주 경쟁'
tokens = set(STOCK_NAME_PATTERN.findall(title))
print('추출:', tokens)
print('차단 후:', {t for t in tokens if t not in GROUP_PREFIX_NAMES and len(t) >= 2})
"
# 기대: '한화', 'LG'가 차단 후 목록에서 제거됨
```

---

## Phase F (P1): 테마 자동등록 → 제안(승인 게이트) 전환

### F-1. `theme_discovery_service` 수정

`auto_register_from_analysis`를 **등록하지 않고 제안만 하는 함수**로 변경한다:

- `_extract_themes_from_analysis`는 그대로 유지 (파싱 재활용)
- `_auto_register_themes` 호출을 제거하고, 추출된 테마를 **복사-실행 가능한 명령어 목록**으로 포맷:

```
🆕 신규 테마 후보 3건 — 등록하려면 아래 명령을 그대로 보내세요:

/theme-add "유리기판" 유리기판,글라스기판,TGV
/theme-add "전력기기 수출" 변압기,전력기기,HVDC

ℹ️ 기존 테마 1건 스킵: 조선 기자재
```

- 기존 테마와 이름 중복인 후보는 스킵 카운트만 표시 (기존 로직 재활용)
- `_auto_register_themes` 함수는 호출처가 없어지면 삭제한다 (CLAUDE.md: 내 변경으로 생긴 고아 정리)
- 텔레그램 `/theme-discover` 핸들러와 `send_weekly_theme_report` 양쪽 모두 동일하게 적용
- 메시지 내 "(다음 월요일 08:00 자동 스캔 예정)" 같은 stale 문구를 실제 스케줄("평일 매일 08:10")로 수정

### F-2. 스테일 테마 자동 비활성화 (간단 버전)

`scheduler.py`의 `_weekly_theme_discovery` 끝에 정리 단계 추가 — 또는 별도 함수로 분리해 같은 cron에서 호출:

- 기준: `enabled=True`이고, **최근 28일간 ThemeDetection이 0건**이며, **생성 후 28일 이상 경과**한 테마 → `enabled=False`로 변경
- 비활성화된 테마가 있으면 텔레그램으로 1줄 통지: `🧹 휴면 테마 N건 비활성화: 테마A, 테마B (재활성화: /theme-add 재등록)`
- 삭제가 아닌 비활성화이므로 감지 이력은 보존됨

### F-3. HELP_TEXT 정리

`telegram_bot.py` HELP_TEXT의 "매주 월 08:00 자동 스캔" → "평일 매일 08:10 자동 스캔"으로 수정. 테마 발굴 설명에 "후보 제안 → /theme-add로 승인" 흐름 반영.

### F-4. 검증

텔레그램에서 `/theme-discover 30` 실행 → 자동 등록 없이 명령어 목록이 오는지, 그중 하나를 복사-전송해 `/theme-add`로 정상 등록되는지 확인. `/theme-list`로 테마 수가 발굴 전후 동일한지 확인.

---

## 부록 (P2 — 본 지시서 범위 외, 별도 지시서로 진행 예정)

구현하지 말 것. 기록 목적:

1. **한국 공휴일 처리**: `_is_weekday()`가 토/일만 거름 → `holidays` 패키지(`holidays.KR()`) 도입 검토
2. **cleanup 확대**: `_cleanup_old_data`가 DailyBrief만 삭제 → theme_detection, theme_scan_results, theme_alert 계열 추가
3. **네이버 AC 캐시**: 토큰→종목코드 일 단위 메모리 캐시로 외부 호출 90% 절감
4. **스캔 소요시간**: Claude 검증 순차 처리 → 동시 3~5건 병렬화. 단, 08:30 StockAI Pull의 409 재시도 로직 유무를 **StockAI 측에서 먼저 확인** 후 진행
5. **`ai_model` 기본값** `claude-sonnet-4-20250514` — .env에서 최신 모델로 덮고 있는지 확인

## 최종 배포 체크리스트

- [ ] `openssl rand -hex 32`로 ADMIN_API_KEY 생성, 백엔드 `.env` + Vercel 환경변수 양쪽 등록
- [ ] Vercel에 `BACKEND_URL` 환경변수 등록
- [ ] 키 없는 curl → 401 확인 (운영 서버 대상)
- [ ] 운영 서버 `timedatectl` 결과 확인
- [ ] 배포 다음 날 07:30 브리프가 KST 오늘 날짜로 저장 + `/today` 정상 조회 확인
- [ ] 08:10 테마 스캔 로그에서 StockListing 다운로드가 스캔당 최대 2회인지 확인
- [ ] 08:30 StockAI Pull이 200으로 정상 수신하는지 확인
- [ ] 다음 월요일 07:45 발굴 리포트가 "명령어 제안" 형식으로 오는지 확인
