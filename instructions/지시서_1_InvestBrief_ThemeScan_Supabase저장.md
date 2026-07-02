# 지시서 1: InvestBrief — theme-scan 결과 공용 Supabase 저장

## 0. 개요

### 목표
매일 08:10 실행되는 `theme-scan` 결과를 **공용 Supabase 테이블**에 저장한다. StockAI가 08:30에 동일 Supabase에서 데이터를 읽어 `batch-analyze`를 실행한다.

### 변경 요약
- 신규 Supabase 테이블 2개: `theme_scan_runs`, `theme_scan_results`
- `theme_radar_service.py`에 Supabase 저장 훅 추가
- `.env`에 변수 추가 없음 (기존 `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` 재사용)

### 영향 범위
- InvestBrief 단독 변경 (StockAI는 별도 지시서 2에서 진행)
- 텔레그램 발송 로직 변경 없음 — 기존 동작 100% 유지
- DB 저장 실패해도 텔레그램은 정상 발송 (fail-soft)

---

## 1. 환경 / 사전 조건

| 항목 | 값 |
|---|---|
| 프로젝트 경로 | `~/dev/investbrief-main` |
| Python | python3 (3.9+) |
| 패키지 매니저 | pip3 |
| Supabase URL | `.env`의 `SUPABASE_URL` 재사용 |
| Service Key | `.env`의 `SUPABASE_SERVICE_KEY` 재사용 |

확인 명령:
```bash
cd ~/dev/investbrief-main/backend
grep -E "^SUPABASE_URL|^SUPABASE_SERVICE_KEY" .env
pip3 show supabase 2>/dev/null | head -3
```

`supabase` 패키지가 없으면:
```bash
pip3 install supabase
echo "supabase>=2.0.0" >> requirements.txt
```

---

## 2. Supabase 스키마 마이그레이션

### 2.1 SQL 파일 작성

**경로**: `~/dev/investbrief-main/backend/migrations/20260501_theme_scan_tables.sql`

```sql
-- ================================================================
-- theme_scan_runs: 일별 스캔 실행 메타 (StockAI polling용 status flag)
-- ================================================================
CREATE TABLE IF NOT EXISTS public.theme_scan_runs (
    id              BIGSERIAL PRIMARY KEY,
    scan_date       DATE NOT NULL UNIQUE,
    status          TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    total_themes    INTEGER DEFAULT 0,
    total_stocks    INTEGER DEFAULT 0,
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_theme_scan_runs_date_status
    ON public.theme_scan_runs (scan_date DESC, status);

COMMENT ON TABLE public.theme_scan_runs IS
    'InvestBrief theme-scan 일별 실행 상태. StockAI가 status=completed 확인 후 batch-analyze 진행';

-- ================================================================
-- theme_scan_results: 테마별 감지 종목 (검증 통과분만 저장)
-- ================================================================
CREATE TABLE IF NOT EXISTS public.theme_scan_results (
    id                  BIGSERIAL PRIMARY KEY,
    scan_date           DATE NOT NULL,
    theme_name          TEXT NOT NULL,
    stock_code          TEXT NOT NULL,
    stock_name          TEXT NOT NULL,
    detected_keywords   JSONB DEFAULT '[]'::jsonb,
    source_count        INTEGER DEFAULT 1,
    validation_passed   BOOLEAN NOT NULL DEFAULT TRUE,
    validation_reason   TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- 같은 날짜·테마·종목 중복 방지
    UNIQUE (scan_date, theme_name, stock_code)
);

CREATE INDEX IF NOT EXISTS idx_theme_scan_results_date
    ON public.theme_scan_results (scan_date DESC);
CREATE INDEX IF NOT EXISTS idx_theme_scan_results_date_code
    ON public.theme_scan_results (scan_date DESC, stock_code);

COMMENT ON TABLE public.theme_scan_results IS
    'InvestBrief theme-scan 결과. StockAI가 batch-analyze 입력으로 사용';

-- ================================================================
-- updated_at 자동 갱신 트리거
-- ================================================================
CREATE OR REPLACE FUNCTION public.update_theme_scan_runs_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_theme_scan_runs_updated_at ON public.theme_scan_runs;
CREATE TRIGGER trg_theme_scan_runs_updated_at
    BEFORE UPDATE ON public.theme_scan_runs
    FOR EACH ROW EXECUTE FUNCTION public.update_theme_scan_runs_updated_at();

-- ================================================================
-- RLS: service_role만 접근 (anon/authenticated 차단)
-- ================================================================
ALTER TABLE public.theme_scan_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.theme_scan_results ENABLE ROW LEVEL SECURITY;

-- service_role은 RLS 우회하므로 별도 정책 불필요. anon/authenticated는 차단됨.
```

### 2.2 마이그레이션 실행

**Supabase Dashboard → SQL Editor**에서 위 SQL 전체 붙여넣고 실행.

또는 supabase CLI 사용 시:
```bash
cd ~/dev/investbrief-main/backend
supabase db push
```

### 2.3 검증

Supabase Dashboard → Table Editor에서:
- `theme_scan_runs` 테이블 존재 확인
- `theme_scan_results` 테이블 존재 확인
- 두 테이블 모두 RLS 활성화 확인 (방패 아이콘)

---

## 3. Supabase 클라이언트 모듈

### 3.1 신규 파일: `app/services/theme_scan_storage.py`

```python
"""
theme-scan 결과를 공용 Supabase에 저장.
StockAI가 동일 테이블에서 batch-analyze 입력으로 사용한다.

저장 실패해도 예외를 raise하지 않는다 (텔레그램 발송 등 본 흐름 보호).
"""

import logging
from datetime import date, datetime
from typing import Any

from supabase import Client, create_client

from app.config import settings  # SUPABASE_URL, SUPABASE_SERVICE_KEY

logger = logging.getLogger(__name__)


def _client() -> Client | None:
    """Supabase 클라이언트 생성. 환경변수 누락 시 None 반환."""
    url = settings.SUPABASE_URL
    key = settings.SUPABASE_SERVICE_KEY
    if not url or not key:
        logger.warning("[theme_scan_storage] SUPABASE_URL/SERVICE_KEY 미설정 — 저장 skip")
        return None
    return create_client(url, key)


async def mark_scan_started(scan_date: date, total_themes: int = 0) -> None:
    """스캔 시작 시점에 status='running' 레코드 upsert."""
    client = _client()
    if client is None:
        return

    try:
        client.table("theme_scan_runs").upsert(
            {
                "scan_date": scan_date.isoformat(),
                "status": "running",
                "started_at": datetime.now().isoformat(),
                "completed_at": None,
                "total_themes": total_themes,
                "total_stocks": 0,
                "error_message": None,
            },
            on_conflict="scan_date",
        ).execute()
        logger.info(f"[theme_scan_storage] scan_runs running: {scan_date}")
    except Exception as e:
        logger.error(f"[theme_scan_storage] mark_scan_started 실패: {e}", exc_info=True)


async def save_scan_results(
    scan_date: date,
    theme_name: str,
    stocks: list[dict[str, Any]],
) -> int:
    """
    검증 통과한 종목들을 results 테이블에 INSERT.
    
    stocks 형식:
      [
        {
          "code": "005930",
          "name": "삼성전자",
          "keywords": ["HBM", "후공정"],   # optional
          "source_count": 3,                # optional
          "validation_reason": "..."        # optional
        },
        ...
      ]
    
    중복(scan_date, theme_name, stock_code)은 ON CONFLICT DO NOTHING 처리.
    
    Returns: 실제 저장된 행 수
    """
    client = _client()
    if client is None or not stocks:
        return 0

    rows = [
        {
            "scan_date": scan_date.isoformat(),
            "theme_name": theme_name,
            "stock_code": str(s["code"]).zfill(6),
            "stock_name": s["name"],
            "detected_keywords": s.get("keywords", []),
            "source_count": s.get("source_count", 1),
            "validation_passed": True,
            "validation_reason": s.get("validation_reason"),
        }
        for s in stocks
    ]

    try:
        # upsert로 중복 무시 (ignore_duplicates 효과)
        result = (
            client.table("theme_scan_results")
            .upsert(rows, on_conflict="scan_date,theme_name,stock_code")
            .execute()
        )
        n = len(result.data) if result.data else 0
        logger.info(f"[theme_scan_storage] {scan_date} {theme_name}: {n}건 저장")
        return n
    except Exception as e:
        logger.error(
            f"[theme_scan_storage] save_scan_results 실패 ({theme_name}): {e}",
            exc_info=True,
        )
        return 0


async def mark_scan_completed(
    scan_date: date,
    total_themes: int,
    total_stocks: int,
) -> None:
    """스캔 정상 완료 시 status='completed' UPDATE."""
    client = _client()
    if client is None:
        return

    try:
        client.table("theme_scan_runs").update(
            {
                "status": "completed",
                "completed_at": datetime.now().isoformat(),
                "total_themes": total_themes,
                "total_stocks": total_stocks,
                "error_message": None,
            }
        ).eq("scan_date", scan_date.isoformat()).execute()
        logger.info(
            f"[theme_scan_storage] scan_runs completed: "
            f"{scan_date} themes={total_themes} stocks={total_stocks}"
        )
    except Exception as e:
        logger.error(f"[theme_scan_storage] mark_scan_completed 실패: {e}", exc_info=True)


async def mark_scan_failed(scan_date: date, error: str) -> None:
    """스캔 실패 시 status='failed' UPDATE."""
    client = _client()
    if client is None:
        return

    try:
        client.table("theme_scan_runs").update(
            {
                "status": "failed",
                "completed_at": datetime.now().isoformat(),
                "error_message": error[:1000],  # TEXT 컬럼이지만 장문 방지
            }
        ).eq("scan_date", scan_date.isoformat()).execute()
        logger.warning(f"[theme_scan_storage] scan_runs failed: {scan_date} — {error[:200]}")
    except Exception as e:
        logger.error(f"[theme_scan_storage] mark_scan_failed 실패: {e}", exc_info=True)
```

---

## 4. theme_radar_service.py 통합

### 4.1 import 추가

`~/dev/investbrief-main/backend/app/services/theme_radar_service.py` 상단에:

```python
from app.services import theme_scan_storage
from datetime import date as date_cls
```

### 4.2 메인 스캔 함수에 훅 삽입

`run_theme_scan()` 또는 동일 역할 함수 (이름이 다를 수 있음 — 텔레그램 `/theme-scan` 명령이 호출하는 함수)를 찾아 수정:

```python
async def run_theme_scan(send_telegram: bool = True) -> dict:
    """매일 08:10 실행되는 테마 스캔 메인 함수."""
    today = date_cls.today()
    
    # ───── (NEW) 스캔 시작 마킹 ─────
    themes = get_registered_themes()  # 13개 테마
    await theme_scan_storage.mark_scan_started(today, total_themes=len(themes))
    # ─────────────────────────────────

    total_saved = 0
    scan_summary = {}

    try:
        for theme in themes:
            # 기존 스캔 로직 (뉴스 검색 + Claude 검증)
            detected_stocks = await scan_single_theme(theme)
            
            # ───── (NEW) Supabase 저장 ─────
            if detected_stocks:
                saved = await theme_scan_storage.save_scan_results(
                    scan_date=today,
                    theme_name=theme.name,
                    stocks=detected_stocks,
                )
                total_saved += saved
            # ─────────────────────────────────
            
            scan_summary[theme.name] = len(detected_stocks)

            # 기존 텔레그램 발송 로직 (변경 없음)
            if send_telegram and detected_stocks:
                await send_theme_scan_telegram(theme, detected_stocks)

        # ───── (NEW) 스캔 완료 마킹 ─────
        await theme_scan_storage.mark_scan_completed(
            today, total_themes=len(themes), total_stocks=total_saved
        )
        # ─────────────────────────────────

        return {"status": "ok", "summary": scan_summary, "total": total_saved}

    except Exception as e:
        # ───── (NEW) 실패 마킹 ─────
        await theme_scan_storage.mark_scan_failed(today, str(e))
        # ───────────────────────────────
        logger.error(f"[theme_scan] 실패: {e}", exc_info=True)
        raise
```

> **주의**: 실제 함수명/시그니처는 코드 확인 후 맞출 것. 핵심은 **3개 훅**(시작/저장/완료/실패)을 정확한 위치에 끼우는 것.

### 4.3 detected_stocks 형식 정규화

`scan_single_theme`이 반환하는 종목 dict 형식을 `theme_scan_storage.save_scan_results`가 기대하는 형식에 맞추기:

```python
# 기대 형식
{
    "code": "005930",       # str, 6자리
    "name": "삼성전자",
    "keywords": ["HBM"],     # optional
    "source_count": 3,        # optional
    "validation_reason": "..."# optional
}
```

기존 코드가 다른 키 이름을 쓰면 `theme_scan_storage`에 어댑터 함수를 두거나, 호출 시점에 변환할 것.

---

## 5. 테스트

### 5.1 단위 테스트 (수동)

```bash
cd ~/dev/investbrief-main/backend

# Python REPL로 테스트
python3 -c "
import asyncio
from datetime import date
from app.services import theme_scan_storage

async def test():
    today = date.today()
    await theme_scan_storage.mark_scan_started(today, total_themes=2)
    n1 = await theme_scan_storage.save_scan_results(
        today, '테스트테마',
        [
            {'code': '005930', 'name': '삼성전자', 'keywords': ['테스트']},
            {'code': '000660', 'name': 'SK하이닉스', 'keywords': ['테스트']},
        ],
    )
    print(f'저장: {n1}건')
    await theme_scan_storage.mark_scan_completed(today, 1, n1)
    print('완료')

asyncio.run(test())
"
```

Supabase Dashboard에서 두 테이블에 레코드 들어왔는지 확인.

### 5.2 통합 테스트

텔레그램에서 `/theme-scan` 수동 실행 → Supabase Dashboard에서:
- `theme_scan_runs`: 오늘 날짜 status=completed 1행
- `theme_scan_results`: 감지된 종목 수만큼 행

### 5.3 텔레그램 발송 정상 작동 확인

DB 저장 추가가 기존 텔레그램 발송에 영향 없어야 함. 실행 후 텔레그램 메시지 정상 도착 확인.

---

## 6. 정리 데이터 (선택)

오래된 scan 결과는 30일 후 자동 삭제하고 싶다면 Supabase에 cron 함수 추가:

```sql
-- 30일 이전 데이터 정리 (선택, 즉시 적용 안 해도 됨)
SELECT cron.schedule(
    'cleanup-theme-scan',
    '0 3 * * *',  -- 매일 03:00
    $$
    DELETE FROM public.theme_scan_results WHERE scan_date < CURRENT_DATE - INTERVAL '30 days';
    DELETE FROM public.theme_scan_runs WHERE scan_date < CURRENT_DATE - INTERVAL '30 days';
    $$
);
```

> 처음에는 적용하지 말 것. 먼저 일주일 운영 후 데이터량 보고 결정.

---

## 7. 롤백 절차

문제 발생 시:

```sql
-- Supabase SQL Editor
DROP TRIGGER IF EXISTS trg_theme_scan_runs_updated_at ON public.theme_scan_runs;
DROP FUNCTION IF EXISTS public.update_theme_scan_runs_updated_at();
DROP TABLE IF EXISTS public.theme_scan_results;
DROP TABLE IF EXISTS public.theme_scan_runs;
```

코드 측: `theme_radar_service.py`에서 추가한 `mark_scan_started/save_scan_results/mark_scan_completed/mark_scan_failed` 호출 4곳 제거.

---

## 8. 완료 체크리스트

- [ ] `migrations/20260501_theme_scan_tables.sql` 작성
- [ ] Supabase Dashboard에서 마이그레이션 SQL 실행
- [ ] `theme_scan_runs`, `theme_scan_results` 테이블 생성 확인
- [ ] 두 테이블 RLS 활성화 확인
- [ ] `app/services/theme_scan_storage.py` 신규 작성
- [ ] `theme_radar_service.py`에 4개 훅 삽입
- [ ] 단위 테스트 통과 (수동)
- [ ] `/theme-scan` 수동 실행 → Supabase에 데이터 저장 확인
- [ ] 텔레그램 메시지 정상 발송 확인
- [ ] 백엔드 재시작 후 08:10 자동 스캔 정상 작동 확인 (다음 평일)

---

## 9. StockAI 측 작업

이 지시서는 **InvestBrief 측 저장**까지만 다룬다. StockAI가 이 데이터를 읽어 batch-analyze를 실행하는 작업은 별도 **지시서 2**에서 진행한다.

지시서 2 작업 전에 이 지시서가 완료되어 있어야 한다 (StockAI가 읽을 데이터가 있어야 하므로).
