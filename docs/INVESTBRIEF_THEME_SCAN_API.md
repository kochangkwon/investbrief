# INVESTBRIEF_THEME_SCAN_API.md

## 목적

InvestBrief의 `/theme-scan` 결과를 DB에 영속 저장하고, StockAI가 조회할 수 있는 내부 API 엔드포인트를 제공한다.

## 배경

- StockAI의 일일 batch-analyze가 InvestBrief 테마 스캔 결과를 입력으로 사용
- 두 시스템은 독립 운영 (Pull 방식, InvestBrief는 데이터 제공자)
- 인증은 API 키 기반 (StockAI 전용 토큰)

## 작업 범위

1. DB 테이블 추가: `theme_scan_results`
2. DB 테이블 추가: `theme_scan_runs` (스캔 실행 메타데이터)
3. `/theme-scan` 명령어 수정: 결과를 DB에 INSERT, 완료 시 run 레코드 갱신
4. 내부 API 엔드포인트 추가: `GET /api/internal/theme-scan/results`
5. API 키 인증 미들웨어 추가
6. 환경 변수 추가: `STOCKAI_INTERNAL_API_KEY`

## 작업하지 않는 것

- 기존 `/theme-scan` 텔레그램 알림 로직은 그대로 유지
- 기존 `/theme-discover` 명령어는 변경 없음
- StockAI 측 코드 변경 없음 (별도 지시서)

## 타임존 정책

- `scan_date`는 **KST 기준 날짜**로 저장
- 모든 timestamp는 `TIMESTAMP WITH TIME ZONE`으로 저장
- API 응답의 `scan_date`는 ISO 날짜 문자열 (KST)

---

## 1. DB 스키마 추가

### 파일: `backend/app/db/migrations/XXXX_add_theme_scan_results.py` (Alembic)

```sql
CREATE TABLE IF NOT EXISTS theme_scan_results (
    id SERIAL PRIMARY KEY,
    scan_date DATE NOT NULL,
    theme_name TEXT NOT NULL,
    stock_code VARCHAR(6) NOT NULL,
    stock_name TEXT NOT NULL,
    detected_keywords JSONB DEFAULT '[]'::jsonb,
    source_url TEXT,
    claude_validation_passed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- 같은 날 같은 테마에 같은 종목 중복 저장 방지
    UNIQUE (scan_date, theme_name, stock_code)
);

CREATE INDEX idx_theme_scan_results_date ON theme_scan_results(scan_date);
CREATE INDEX idx_theme_scan_results_theme ON theme_scan_results(theme_name);
CREATE INDEX idx_theme_scan_results_code ON theme_scan_results(stock_code);

-- 스캔 실행 메타데이터 (StockAI가 완료 여부를 확인하기 위함)
CREATE TABLE IF NOT EXISTS theme_scan_runs (
    id SERIAL PRIMARY KEY,
    scan_date DATE NOT NULL UNIQUE,
    started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    status VARCHAR NOT NULL DEFAULT 'running',  -- 'running' | 'completed' | 'failed'
    total_themes INT DEFAULT 0,
    total_stocks INT DEFAULT 0,
    error_message TEXT
);

CREATE INDEX idx_theme_scan_runs_date ON theme_scan_runs(scan_date);
```

### Supabase RLS

```sql
-- 외부에서 직접 접근 차단 (API를 통해서만 접근)
ALTER TABLE theme_scan_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE theme_scan_runs ENABLE ROW LEVEL SECURITY;
```

### SQLAlchemy 모델: `backend/app/db/models.py` (추가)

```python
from sqlalchemy import Column, Integer, String, Date, Boolean, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.db.base import Base


class ThemeScanResult(Base):
    __tablename__ = "theme_scan_results"

    id = Column(Integer, primary_key=True)
    scan_date = Column(Date, nullable=False, index=True)
    theme_name = Column(Text, nullable=False, index=True)
    stock_code = Column(String(6), nullable=False, index=True)
    stock_name = Column(Text, nullable=False)
    detected_keywords = Column(JSONB, default=list)
    source_url = Column(Text)
    claude_validation_passed = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ThemeScanRun(Base):
    __tablename__ = "theme_scan_runs"

    id = Column(Integer, primary_key=True)
    scan_date = Column(Date, nullable=False, unique=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True))
    status = Column(String, nullable=False, default="running")
    total_themes = Column(Integer, default=0)
    total_stocks = Column(Integer, default=0)
    error_message = Column(Text)
```

---

## 2. theme-scan 명령어 수정

### 파일: `backend/app/services/theme_radar_service.py`

기존 `theme_scan` 함수의 시작/종료 시점에 run 레코드 갱신, 검증 통과 종목을 DB에 저장:

```python
from datetime import date, datetime
from zoneinfo import ZoneInfo
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.models import ThemeScanResult, ThemeScanRun
from app.db.session import get_db_session

KST = ZoneInfo("Asia/Seoul")


async def _start_scan_run(scan_date: date) -> int:
    """스캔 시작 시 run 레코드 생성 (idempotent)"""
    async with get_db_session() as session:
        stmt = pg_insert(ThemeScanRun).values(
            scan_date=scan_date,
            status="running",
            started_at=datetime.now(KST),
        ).on_conflict_do_update(
            index_elements=["scan_date"],
            set_={
                "status": "running",
                "started_at": datetime.now(KST),
                "completed_at": None,
                "error_message": None,
            },
        ).returning(ThemeScanRun.id)
        result = await session.execute(stmt)
        run_id = result.scalar_one()
        await session.commit()
        return run_id


async def _complete_scan_run(
    scan_date: date,
    total_themes: int,
    total_stocks: int,
) -> None:
    async with get_db_session() as session:
        stmt = (
            update(ThemeScanRun)
            .where(ThemeScanRun.scan_date == scan_date)
            .values(
                status="completed",
                completed_at=datetime.now(KST),
                total_themes=total_themes,
                total_stocks=total_stocks,
            )
        )
        await session.execute(stmt)
        await session.commit()


async def _fail_scan_run(scan_date: date, error: str) -> None:
    async with get_db_session() as session:
        stmt = (
            update(ThemeScanRun)
            .where(ThemeScanRun.scan_date == scan_date)
            .values(
                status="failed",
                completed_at=datetime.now(KST),
                error_message=error[:1000],
            )
        )
        await session.execute(stmt)
        await session.commit()


async def save_scan_results(
    scan_date: date,
    theme_name: str,
    validated_stocks: list[dict]
) -> None:
    """검증 통과된 종목들을 DB에 저장 (테마 단위)"""
    if not validated_stocks:
        return

    async with get_db_session() as session:
        for stock in validated_stocks:
            stmt = pg_insert(ThemeScanResult).values(
                scan_date=scan_date,
                theme_name=theme_name,
                stock_code=stock["code"],
                stock_name=stock["name"],
                detected_keywords=stock.get("keywords", []),
                source_url=stock.get("source_url"),
                claude_validation_passed=True,
            ).on_conflict_do_nothing(
                index_elements=["scan_date", "theme_name", "stock_code"]
            )
            await session.execute(stmt)
        await session.commit()
```

### 기존 `theme_scan` 함수 수정 흐름

```python
async def theme_scan():
    scan_date = datetime.now(KST).date()

    try:
        await _start_scan_run(scan_date)

        total_themes = 0
        total_stocks = 0

        for theme in get_registered_themes():
            validated = await scan_and_validate_theme(theme)

            # 텔레그램 알림 (기존 로직 유지)
            await send_theme_scan_alert(theme, validated)

            # DB 저장 (신규)
            await save_scan_results(scan_date, theme.name, validated)

            total_themes += 1
            total_stocks += len(validated)

        await _complete_scan_run(scan_date, total_themes, total_stocks)

    except Exception as e:
        await _fail_scan_run(scan_date, str(e))
        raise
```

---

## 3. 내부 API 엔드포인트 추가

### 파일: `backend/app/api/internal/__init__.py` (신규)

```python
# empty file
```

### 파일: `backend/app/api/internal/theme_scan.py` (신규)

```python
from datetime import date, datetime
from zoneinfo import ZoneInfo
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from app.api.internal.auth import verify_internal_api_key
from app.db.models import ThemeScanResult, ThemeScanRun
from app.db.session import get_db_session

KST = ZoneInfo("Asia/Seoul")

router = APIRouter(
    prefix="/api/internal/theme-scan",
    tags=["internal"],
    dependencies=[Depends(verify_internal_api_key)],
)


@router.get("/runs/{target_date}")
async def get_scan_run_status(target_date: date):
    """
    특정 날짜 스캔 실행 상태 조회 (StockAI가 완료 여부 확인용)
    """
    async with get_db_session() as session:
        stmt = select(ThemeScanRun).where(ThemeScanRun.scan_date == target_date)
        run = (await session.execute(stmt)).scalar_one_or_none()

    if not run:
        raise HTTPException(404, "Scan run not found")

    return {
        "scan_date": run.scan_date.isoformat(),
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "total_themes": run.total_themes,
        "total_stocks": run.total_stocks,
        "error_message": run.error_message,
    }


@router.get("/results")
async def get_theme_scan_results(
    target_date: Optional[date] = Query(None, alias="date"),
    require_completed: bool = Query(True),
):
    """
    특정 날짜의 테마 스캔 결과 조회 (StockAI 전용)

    - target_date 미지정 시 오늘(KST) 날짜
    - require_completed=True (기본): 스캔이 완료(completed)된 경우만 결과 반환,
      그 외에는 409 반환 → StockAI가 재시도하거나 skip
    - 검증 통과 (claude_validation_passed=True) 종목만 반환
    """
    if target_date is None:
        target_date = datetime.now(KST).date()

    async with get_db_session() as session:
        # 완료 여부 확인
        run_stmt = select(ThemeScanRun).where(ThemeScanRun.scan_date == target_date)
        run = (await session.execute(run_stmt)).scalar_one_or_none()

        if require_completed:
            if not run:
                raise HTTPException(
                    status_code=409,
                    detail=f"No scan run for {target_date}",
                )
            if run.status != "completed":
                raise HTTPException(
                    status_code=409,
                    detail=f"Scan status is '{run.status}', not 'completed'",
                )

        # 결과 조회
        stmt = (
            select(ThemeScanResult)
            .where(ThemeScanResult.scan_date == target_date)
            .where(ThemeScanResult.claude_validation_passed.is_(True))
            .order_by(ThemeScanResult.theme_name, ThemeScanResult.stock_code)
        )
        results = (await session.execute(stmt)).scalars().all()

    # 테마별로 그룹핑
    themes_dict: dict[str, list[dict]] = {}
    for r in results:
        themes_dict.setdefault(r.theme_name, []).append({
            "code": r.stock_code,
            "name": r.stock_name,
            "keywords": r.detected_keywords or [],
            "source_url": r.source_url,
            "detected_at": r.created_at.isoformat() if r.created_at else None,
        })

    return {
        "scan_date": target_date.isoformat(),
        "scan_status": run.status if run else "missing",
        "scan_completed_at": (
            run.completed_at.isoformat() if run and run.completed_at else None
        ),
        "themes": [
            {"theme": name, "stocks": stocks}
            for name, stocks in themes_dict.items()
        ],
        "total_stocks": sum(len(s) for s in themes_dict.values()),
    }
```

### 라우터 등록: `backend/app/main.py` (수정)

```python
from app.api.internal.theme_scan import router as internal_theme_scan_router

app.include_router(internal_theme_scan_router)
```

---

## 4. API 키 인증 미들웨어

### 파일: `backend/app/api/internal/auth.py` (신규)

```python
import os
import secrets
from typing import Annotated
from fastapi import Header, HTTPException, status


async def verify_internal_api_key(
    x_internal_api_key: Annotated[str | None, Header()] = None,
):
    """
    내부 API 호출 인증
    StockAI가 X-Internal-API-Key 헤더로 인증
    """
    expected_key = os.getenv("STOCKAI_INTERNAL_API_KEY")

    if not expected_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="STOCKAI_INTERNAL_API_KEY not configured on server",
        )

    if not x_internal_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Internal-API-Key header",
        )

    # 타이밍 공격 방지를 위해 secrets.compare_digest 사용
    if not secrets.compare_digest(x_internal_api_key, expected_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
```

---

## 5. 환경 변수 추가

### 파일: `backend/.env.example`

```
# StockAI internal API 호출용 (양쪽 시스템에 동일 값 설정)
# 생성: openssl rand -hex 32
STOCKAI_INTERNAL_API_KEY=
```

### 파일: `backend/.env` (실제 키 생성)

```bash
# 키 생성
openssl rand -hex 32
# 출력값을 STOCKAI_INTERNAL_API_KEY=... 에 붙여넣기
# 동일한 값을 StockAI .env의 INVESTBRIEF_API_KEY에도 설정
```

---

## 6. 테스트

### 단위 테스트

```bash
cd backend
pytest tests/test_theme_scan_api.py -v
pytest tests/test_internal_auth.py -v
```

### 수동 테스트

```bash
# 1. theme-scan 실행
/theme-scan

# 2. run 상태 확인
psql $DATABASE_URL -c "SELECT scan_date, status, total_themes, total_stocks FROM theme_scan_runs ORDER BY started_at DESC LIMIT 5;"

# 3. 저장 데이터 확인
psql $DATABASE_URL -c "SELECT scan_date, theme_name, COUNT(*) FROM theme_scan_results WHERE scan_date = CURRENT_DATE GROUP BY scan_date, theme_name;"

# 4. API 호출 테스트 (완료 상태)
curl -H "X-Internal-API-Key: $STOCKAI_INTERNAL_API_KEY" \
  http://localhost:8000/api/internal/theme-scan/results

# 5. 특정 날짜 조회
curl -H "X-Internal-API-Key: $STOCKAI_INTERNAL_API_KEY" \
  "http://localhost:8000/api/internal/theme-scan/results?date=2026-04-29"

# 6. 인증 실패 테스트 (401)
curl http://localhost:8000/api/internal/theme-scan/results

# 7. 잘못된 키 (401)
curl -H "X-Internal-API-Key: wrong" \
  http://localhost:8000/api/internal/theme-scan/results

# 8. 미완료 상태 조회 (409)
curl -H "X-Internal-API-Key: $STOCKAI_INTERNAL_API_KEY" \
  "http://localhost:8000/api/internal/theme-scan/results?date=2099-12-31"

# 9. run 상태 조회
curl -H "X-Internal-API-Key: $STOCKAI_INTERNAL_API_KEY" \
  http://localhost:8000/api/internal/theme-scan/runs/2026-04-29
```

---

## 7. 배포 체크리스트

- [ ] DB 마이그레이션 실행 (theme_scan_results, theme_scan_runs 테이블 생성 확인)
- [ ] 환경 변수 `STOCKAI_INTERNAL_API_KEY` 설정 (운영 환경)
- [ ] `/theme-scan` 실행 후 run 레코드 + 결과 데이터 모두 저장 확인
- [ ] 내부 API `/api/internal/theme-scan/results` 응답 확인
- [ ] 인증 없이/잘못된 키로 호출 시 401 반환 확인
- [ ] 미완료 상태 조회 시 409 반환 확인
- [ ] 기존 텔레그램 알림 정상 동작 확인 (회귀 테스트)
- [ ] StockAI 측 .env에 동일 키를 `INVESTBRIEF_API_KEY`로 공유

---

## 작성된 파일 목록

```
backend/app/db/migrations/XXXX_add_theme_scan_results.py   (신규)
backend/app/db/models.py                                    (수정 - ThemeScanResult, ThemeScanRun 추가)
backend/app/services/theme_radar_service.py                 (수정 - run 관리 + save_scan_results 추가)
backend/app/api/internal/__init__.py                        (신규)
backend/app/api/internal/auth.py                            (신규)
backend/app/api/internal/theme_scan.py                      (신규)
backend/app/main.py                                         (수정 - 라우터 등록)
backend/.env.example                                        (수정)
tests/test_theme_scan_api.py                                (신규)
tests/test_internal_auth.py                                 (신규)
```
