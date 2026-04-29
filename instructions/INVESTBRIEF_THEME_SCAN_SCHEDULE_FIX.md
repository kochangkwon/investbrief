# INVESTBRIEF_THEME_SCAN_SCHEDULE_FIX.md

## 목적

InvestBrief의 `/theme-scan`을 **주 1회(월요일 08:00) → 평일 매일(08:10)** 로 변경한다.

## 배경

- StockAI의 `daily_batch_from_investbrief`가 매일 08:30(KST)에 InvestBrief의 당일 스캔 결과를 호출하는 워크플로우
- 현재 InvestBrief는 월요일 08:00에만 스캔 실행 → 화~금에는 당일 결과가 없어 StockAI가 409 응답 받고 batch-analyze skip
- 매일 스캔으로 변경하지 않으면 StockAI 자동매매 파이프라인이 주 1회만 동작

## 작업 범위

1. `_weekly_theme_scan` 함수를 `_daily_theme_scan`으로 리네이밍
2. 스케줄 변경: `day_of_week="mon"`, `hour=8, minute=0` → `day_of_week="mon-fri"`, `hour=8, minute=10`
3. job ID 변경: `weekly_theme_scan` → `daily_theme_scan`
4. 로그 메시지의 "주간" → "일일" 표기 정리

## 작업하지 않는 것

- 스캔 로직 자체(`scan_all_themes`) 변경 없음
- 일요일 09:00 `weekly_theme_discovery`는 그대로 유지 (별개 잡)
- 텔레그램 알림 포맷 변경 없음

---

## 운영 영향 검토 (사전 인지)

매일 실행으로 빈도가 5배 증가하므로 다음 항목을 미리 인지해 둔다:

| 항목 | 현재(월 1회) | 변경 후(주 5회) | 비고 |
|------|------------|---------------|------|
| Anthropic API 호출 | 주 1회 분량 | 주 5회 분량 | 테마당 신규 종목 N개 × Claude 검증 1회. 현재 검증 비용 추산 후 월 한도 내 여부 확인 권장 |
| 네이버 뉴스 API | 주 1회 | 주 5회 | 일일 호출 한도 내 (네이버 25,000건/일이면 여유 있음) |
| 텔레그램 알림 | 주 1회 | 매일 가능 | `ThemeDetection`의 `existing_codes` 중복 체크가 있어, **신규 감지가 없는 날은 알림 미발송** (조용한 날 발생 가능) — OK |
| DB 쓰기 | 주 1회 | 매일 | `theme_scan_runs`/`theme_scan_results` 매일 쓰기. 부담 없음 |

> **참고**: 종목별 중복 감지 방지는 `_scan_single_theme:231-234`의 `existing_codes` 체크가 처리하므로, 매일 실행해도 동일 종목이 매일 새로 감지되어 텔레그램이 도배되지는 않는다.

---

## 1. 코드 변경

### 파일: `backend/app/services/scheduler.py`

#### 1-1. 함수 리네이밍 + 로그 메시지 정리

**변경 전 (133-141 라인):**
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

**변경 후:**
```python
async def _daily_theme_scan():
    """평일 매일 테마 선행 스캐너 (08:10 KST)"""
    logger.info("일일 테마 스캔 시작")
    try:
        results = await theme_radar_service.scan_all_themes()
        total_new = sum(results.values())
        logger.info("일일 테마 스캔 완료 — 신규 감지 %d건: %s", total_new, results)
    except Exception:
        logger.exception("일일 테마 스캔 실패")
```

#### 1-2. 스케줄 등록 변경

**변경 전 (207-211 라인):**
```python
scheduler.add_job(
    _weekly_theme_scan, "cron",
    day_of_week="mon", hour=8, minute=0,
    id="weekly_theme_scan",
)
```

**변경 후:**
```python
scheduler.add_job(
    _daily_theme_scan, "cron",
    day_of_week="mon-fri", hour=8, minute=10,
    id="daily_theme_scan",
    replace_existing=True,
    misfire_grace_time=300,  # 서버 재시작 등으로 5분 내 늦어져도 재시도 허용
)
```

#### 1-3. 디스커버리 잡과의 분리 확인 (변경 없음, 검토만)

```python
# 기존 그대로 유지 — 일요일 09:00 테마 발굴
scheduler.add_job(
    _weekly_theme_discovery, "cron",
    day_of_week="sun", hour=9, minute=0,
    id="weekly_theme_discovery",
)
```

→ `discovery`는 별개 잡이며 영향 없음.

---

## 2. 기존 job ID 정리 (배포 시 1회만 실행)

기존 `weekly_theme_scan` job ID로 등록된 잡이 APScheduler 영속 저장소(jobstore)에 남아있을 가능성에 대비.

InvestBrief는 현재 메모리 jobstore를 쓰는 것으로 보이므로(`scheduler.py`에 SQLAlchemyJobStore 설정 없음 → 기본 MemoryJobStore), **서버 재시작 시 자동으로 깨끗이 정리됨**. 별도 마이그레이션 명령 불필요.

다만 향후 영속 jobstore로 변경할 가능성을 대비해, `start_scheduler()` 시작부에 안전장치 추가:

```python
def start_scheduler():
    """스케줄러 시작"""
    # 구버전 job ID 잔재 정리 (1회용 안전장치)
    try:
        scheduler.remove_job("weekly_theme_scan")
        logger.info("구 job 'weekly_theme_scan' 제거")
    except Exception:
        pass  # 없으면 정상

    hour = settings.brief_send_hour
    # ... 이하 기존 코드 유지 ...
```

> 이 정리 코드는 일정 기간 운영 후 제거해도 무방.

---

## 3. 검증

### 3-1. 단위 검증 (배포 직후)

```bash
# 1. 스케줄 등록 확인
cd backend
python3 -c "
import asyncio
from app.services.scheduler import scheduler, start_scheduler
start_scheduler()
for job in scheduler.get_jobs():
    print(f'{job.id:30s} | {job.trigger}')
"
```

**기대 출력에 다음 라인 포함**:
```
daily_theme_scan               | cron[day_of_week='mon-fri', hour='8', minute='10']
```

`weekly_theme_scan`은 **출력에 없어야 함**.

### 3-2. 운영 검증 (배포 후 첫 평일)

배포 후 첫 평일 08:11~08:30 사이 다음 확인:

```bash
# DB에 당일 run 레코드 생성 확인
psql $DATABASE_URL -c "
SELECT scan_date, status, started_at, completed_at, total_themes, total_stocks
FROM theme_scan_runs
WHERE scan_date = CURRENT_DATE;
"
```

**기대 결과**: 1행, status='running' (스캔 중) 또는 'completed' (완료)

```bash
# StockAI 측 호출 시뮬레이션
curl -H "X-Internal-API-Key: $STOCKAI_INTERNAL_API_KEY" \
  "http://localhost:8001/api/internal/theme-scan/runs/$(date +%Y-%m-%d)"
```

**기대 응답**: 200 OK + status="completed" (08:30 이후)

### 3-3. 일주일 운영 검증

```bash
# 평일 5일치 run 레코드 확인
psql $DATABASE_URL -c "
SELECT scan_date, status, total_themes, total_stocks,
       EXTRACT(EPOCH FROM (completed_at - started_at)) AS duration_sec
FROM theme_scan_runs
WHERE scan_date >= CURRENT_DATE - INTERVAL '7 days'
ORDER BY scan_date DESC;
"
```

**기대 결과**:
- 평일(월~금)에만 레코드 존재 (토/일 없음)
- 모두 status='completed'
- duration_sec이 합리적 범위 (보통 60~600초, 테마 13개 × 평균 검증)

---

## 4. 배포 체크리스트

- [ ] `scheduler.py`의 함수명 `_weekly_theme_scan` → `_daily_theme_scan`
- [ ] 함수 docstring/log 메시지의 "주간" → "일일"
- [ ] `add_job` 인자 변경: `day_of_week`, `hour`, `minute`, `id`
- [ ] `replace_existing=True`, `misfire_grace_time=300` 추가
- [ ] (안전장치) `start_scheduler()` 시작부에 구 job ID 정리 코드 추가
- [ ] 서버 재배포 후 `scheduler.get_jobs()`로 등록 상태 확인
- [ ] 다음 평일 08:11~08:30에 `theme_scan_runs` 신규 레코드 확인
- [ ] 텔레그램에 신규 감지 알림이 도배되지 않는지 확인 (existing_codes 중복 체크 정상 동작)
- [ ] Anthropic API 일일 사용량 모니터링 (첫 1주일)

---

## 5. 롤백 절차

매일 실행으로 인해 API 비용/리소스 문제가 발생할 경우:

```python
# 임시 롤백 — 다시 주 1회로
scheduler.add_job(
    _daily_theme_scan, "cron",
    day_of_week="mon", hour=8, minute=10,
    id="daily_theme_scan",
    replace_existing=True,
)
```

> 함수명/job ID는 그대로 두고 `day_of_week`만 되돌림. StockAI 측은 그동안 결과 없으면 자동 skip하므로 안전.

---

## 6. 작성/수정 파일 목록

```
backend/app/services/scheduler.py    (수정 - 함수명, 스케줄, ID, 로그)
```

단일 파일 1개만 수정. 다른 파일은 영향 없음.
