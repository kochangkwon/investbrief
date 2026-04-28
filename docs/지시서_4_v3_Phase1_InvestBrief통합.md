# 지시서 4 v3 Phase 1: InvestBrief 측정 인프라 통합

## 📋 개요

본 지시서는 **InvestBrief에 v3 측정 인프라를 통합**하여 테마 알림 발송 시 자동으로 ThemeAlert/ThemeAlertCandidate 테이블에 데이터가 쌓이도록 한다.

### 배경

| 항목 | 상태 |
|---|---|
| 알림 발송 주체 | InvestBrief (`theme_radar_service.py:248`의 `_send_theme_alert`) |
| StockAI v3 인프라 | 코드 정의됨 but 호출 안 됨 (불용) |
| StockAI DB | Supabase/PostgreSQL |
| InvestBrief DB | SQLite (`investbrief.db`) — **분리됨** |

→ DB 분리로 시나리오 A-1 (DB 공유) 불가능. **옵션 2: InvestBrief에 측정 인프라 복제** 채택.

### 목표

InvestBrief가 자체 SQLite에 측정 데이터를 쌓아 1-2개월 후 KPI 기반 의사결정 가능하게 한다.

### 제외 범위 (옵션 2 트레이드오프)

- ❌ **매수 매핑 (KPI 매수 전환율) 제외**: 매수는 StockAI에서 발생하므로 InvestBrief에서 추적 불가
- ✅ **나머지 5개 KPI는 모두 측정 가능**

---

## 🔧 Step 1: 모델 복사 (15분)

### 작업

```bash
# StockAI에서 InvestBrief로 복사
cp ~/path/to/stockai/backend/app/models/theme_alert.py \
   ~/path/to/investbrief/backend/app/models/theme_alert.py
```

### 수정 — InvestBrief에 맞게 import 경로 확인

`investbrief/backend/app/models/theme_alert.py` 상단:

```python
from app.database import Base
from app.utils.time import utcnow
```

InvestBrief에 동일 모듈 있는지 확인:

```bash
cd ~/path/to/investbrief
python3 -c "from app.database import Base; print('OK')"
python3 -c "from app.utils.time import utcnow; print('OK')"
```

**없으면 대체:**

```python
# utcnow 없으면 직접 정의
from datetime import datetime
def utcnow() -> datetime:
    return datetime.utcnow()
```

또는 모델 파일 내에 인라인:

```python
# theme_alert.py 상단
from datetime import datetime as _dt
def utcnow() -> _dt:
    return _dt.utcnow()
```

### 모델 등록

`investbrief/backend/app/models/__init__.py` 또는 동등 위치에서 import 보장:

```python
# 마이그레이션/테이블 생성 시 모델이 인식되도록
from app.models.theme_alert import ThemeAlert, ThemeAlertCandidate  # noqa
```

---

## 🔧 Step 2: 발송 서비스 복사 + 수정 (30분)

### 작업

```bash
cp ~/path/to/stockai/backend/app/services/theme_alert_service.py \
   ~/path/to/investbrief/backend/app/services/theme_alert_service.py
```

### 수정 1: 키움 의존성 제거 → InvestBrief의 가격 수집기 사용

`investbrief/backend/app/services/theme_alert_service.py` 라인 14:

```python
# 변경 전 (StockAI 코드)
from app.collectors.kiwoom_collector import kiwoom_collector
```

InvestBrief의 가격 수집기 확인:

```bash
cd ~/path/to/investbrief
ls backend/app/collectors/ 2>/dev/null
grep -rn "get_stock_price\|get_current_price" backend/app/collectors/ --include="*.py" 2>/dev/null | head -5
```

**가능한 대체 (InvestBrief 환경에 따라 선택):**

```python
# 옵션 A: 네이버 collector 사용
from app.collectors.naver_collector import naver_collector

# 옵션 B: yfinance 사용
import yfinance as yf

# 옵션 C: FDR 사용
import FinanceDataReader as fdr
```

### 수정 2: 가격 스냅샷 로직 변경

`theme_alert_service.py:113-119`:

```python
# 변경 전
try:
    price_data = await kiwoom_collector.get_stock_price(c["stock_code"])
    if price_data:
        item["price_at_alert"] = int(price_data.get("current_price") or 0) or None
except Exception as e:
    logger.warning(f"가격 스냅샷 실패 {c.get('stock_code')}: {e}")
    item.setdefault("price_at_alert", None)
```

**InvestBrief의 collector에 맞게 수정 (예: 네이버):**

```python
try:
    price_data = await naver_collector.get_stock_price(c["stock_code"])
    if price_data:
        # naver_collector 응답 구조에 맞게 키 조정
        cur = price_data.get("current_price") or price_data.get("price")
        item["price_at_alert"] = int(cur) if cur else None
except Exception as e:
    logger.warning(f"가격 스냅샷 실패 {c.get('stock_code')}: {e}")
    item.setdefault("price_at_alert", None)
```

**FDR 폴백 (네이버 실패 시):**

```python
import FinanceDataReader as fdr
from datetime import date, timedelta

try:
    # 네이버 우선
    price_data = await naver_collector.get_stock_price(c["stock_code"])
    cur = (price_data or {}).get("current_price")
    
    if not cur:
        # FDR 폴백 (전일 종가)
        end = date.today()
        start = end - timedelta(days=5)
        df = fdr.DataReader(c["stock_code"], start, end)
        if df is not None and not df.empty:
            cur = int(df["Close"].iloc[-1])
    
    item["price_at_alert"] = int(cur) if cur else None
except Exception as e:
    logger.warning(f"가격 스냅샷 실패 {c.get('stock_code')}: {e}")
    item.setdefault("price_at_alert", None)
```

### 수정 3: 텔레그램 발송 로직 검증

`theme_alert_service.py`의 `send_telegram_with_buttons`는 `notification_service._telegram_config`를 참조함. InvestBrief에 동등 모듈 있는지 확인:

```bash
cd ~/path/to/investbrief
grep -rn "telegram_service\|notification_service\|send_telegram\|send_text" backend/app/services/ --include="*.py" 2>/dev/null | head -10
```

InvestBrief는 `telegram_service.send_text` 사용 중 (코드에서 확인됨). **수정 필요:**

```python
# 변경 전 (StockAI 코드)
from app.services.notification_service import notification_service
# ...
await notification_service.send_telegram(message)

# 변경 후 (InvestBrief 환경)
from app.services.telegram_service import telegram_service
# ...
await telegram_service.send_text(message)
```

`send_telegram_with_buttons` 함수도 InvestBrief의 텔레그램 인프라에 맞게 재작성 필요. **단순화 권장:**

**Phase 1 단계에서는 InlineKeyboard 사용 안 함.** Step 4에서 `use_inline_buttons=False`로 호출.

```python
# theme_alert_service.py:55-83의 send_telegram_with_buttons 함수는
# Phase 2-A (사용자 피드백)에서 추후 활용
# Phase 1에서는 use_inline_buttons=False로 우회
```

---

## 🔧 Step 3: 가격 추적 + 분석 모듈 복사 (15분)

```bash
cp ~/path/to/stockai/backend/app/services/theme_alert_tracker.py \
   ~/path/to/investbrief/backend/app/services/theme_alert_tracker.py

cp ~/path/to/stockai/backend/app/services/theme_alert_analytics.py \
   ~/path/to/investbrief/backend/app/services/theme_alert_analytics.py
```

### tracker 수정

`theme_alert_tracker.py:15`:

```python
# 변경 전 (StockAI)
from app.collectors.fdr_collector import FdrCollector

# 변경 후 (InvestBrief에 동등 collector 있는지 확인)
```

```bash
ls ~/path/to/investbrief/backend/app/collectors/ | grep -i fdr
```

**없으면 직접 FDR 사용:**

```python
import FinanceDataReader as fdr

# _fdr = FdrCollector() 제거하고
# 함수 내에서 직접:
df = fdr.DataReader(stock_code, start, end)
```

### analytics 수정

`theme_alert_analytics.py`도 동일하게 텔레그램 호출부를 `telegram_service.send_text`로 변경.

---

## 🔧 Step 4: theme_radar_service.py 통합 (30분) ⭐ 핵심

### 현재 코드 (라인 248-273)

```python
async def _send_theme_alert(theme_name: str, detections: list[dict[str, Any]]) -> None:
    """신규 감지 종목 텔레그램 알림"""
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
```

### 통합안: 측정 인프라 추가 (텔레그램 발송은 그대로 유지)

**핵심 원칙:** 기존 텔레그램 발송 로직 보존. 측정 인프라 호출은 별도 try-except로 감싸 실패해도 알림은 정상 발송.

```python
async def _send_theme_alert(theme_name: str, detections: list[dict[str, Any]]) -> None:
    """신규 감지 종목 텔레그램 알림 + 측정 인프라 기록 (v3 Phase 1)"""
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

    # 1. 텔레그램 발송 (기존 로직 보존)
    try:
        await telegram_service.send_text("\n".join(lines))
    except Exception:
        logger.exception("테마 알림 전송 실패")

    # 2. 측정 인프라 기록 (v3 Phase 1) — 알림 발송과 별개로 진행
    try:
        from app.services.theme_alert_service import send_theme_alert
        from app.database import async_session
        
        # detections → ThemeAlertCandidate 형식으로 변환
        candidates_data = [
            {
                "stock_code": d["stock_code"],
                "stock_name": d["stock_name"],
                "sub_theme": d.get("matched_keyword"),
                "matched_news_title": d.get("headline"),
            }
            for d in detections
        ]
        
        # theme_id 생성 (theme_name 기반, 공백 제거)
        theme_id = theme_name.replace(" ", "_").replace("/", "_")
        
        async with async_session() as db:
            alert_uid = await send_theme_alert(
                theme_id=theme_id,
                theme_name=theme_name,
                candidates=candidates_data,
                db=db,
                use_inline_buttons=False,  # Phase 1에서는 버튼 미사용
            )
        
        if alert_uid:
            logger.info(f"v3 측정: 알림 기록 완료 — {alert_uid}")
    except Exception:
        logger.exception("v3 측정 인프라 기록 실패 — 알림은 정상 발송됨")
```

### ⚠️ 중요: 이중 발송 방지

`send_theme_alert` 함수가 **자체적으로 텔레그램 발송**하므로 그대로 호출하면 **이중 발송**됩니다.

**해결 방법 두 가지:**

#### 방법 A (권장): `send_theme_alert`에서 텔레그램 발송 비활성화 옵션 추가

`theme_alert_service.py:86`의 `send_theme_alert` 함수에 매개변수 추가:

```python
async def send_theme_alert(
    theme_id: str,
    theme_name: str,
    candidates: List[Dict[str, Any]],
    db: AsyncSession,
    *,
    use_inline_buttons: bool = True,
    skip_telegram: bool = False,  # ★ 신규: True면 DB 저장만, 텔레그램 발송 안 함
) -> Optional[str]:
    # ... 기존 로직 ...
    
    # 5. 텔레그램 발송
    if not skip_telegram:  # ★ 추가
        if use_inline_buttons:
            keyboard = _build_inline_keyboard(alert_uid, theme_id)
            ok = await send_telegram_with_buttons(message, keyboard)
        else:
            ok = await telegram_service.send_text(message)
        
        if not ok:
            logger.error(f"테마 알림 발송 실패 (DB는 기록됨): {alert_uid}")
    
    return alert_uid
```

`theme_radar_service.py`에서 호출 시:

```python
alert_uid = await send_theme_alert(
    theme_id=theme_id,
    theme_name=theme_name,
    candidates=candidates_data,
    db=db,
    use_inline_buttons=False,
    skip_telegram=True,  # ★ 텔레그램은 _send_theme_alert에서 이미 발송함
)
```

#### 방법 B: 발송 로직 일원화 (권장도 낮음)

`_send_theme_alert`의 메시지 생성 + 발송을 모두 `send_theme_alert`에 위임. 다만 InvestBrief 고유 메시지 포맷(/theme-list 안내 등) 유지하려면 복잡.

**방법 A 채택 권장.**

### 결론적 통합 코드

`theme_radar_service.py`의 `_send_theme_alert` 함수 끝부분에 다음 추가:

```python
    # ── v3 측정 인프라 기록 (텔레그램 발송과 별도) ──
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
            await send_theme_alert(
                theme_id=theme_id,
                theme_name=theme_name,
                candidates=candidates_data,
                db=db,
                use_inline_buttons=False,
                skip_telegram=True,  # ★ 이미 위에서 텔레그램 발송함
            )
    except Exception:
        logger.exception("v3 측정 인프라 기록 실패 (알림은 정상)")
```

---

## 🔧 Step 5: DB 마이그레이션 (10분)

### Alembic 사용 시

```bash
cd ~/path/to/investbrief/backend
alembic revision --autogenerate -m "add theme_alert tables (v3 phase 1)"
alembic upgrade head
```

### Alembic 미사용 시 (직접 생성)

```bash
cd ~/path/to/investbrief/backend
python3 << 'EOF'
import asyncio
from app.database import Base, async_engine
from app.models.theme_alert import ThemeAlert, ThemeAlertCandidate  # 모델 등록

async def create_tables():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ theme_alerts, theme_alert_candidates 테이블 생성 완료")

asyncio.run(create_tables())
EOF
```

### 검증

```bash
sqlite3 investbrief.db "
SELECT name FROM sqlite_master 
WHERE type='table' AND name LIKE 'theme_alert%';
"
```

기대 출력:
```
theme_alerts
theme_alert_candidates
```

---

## 🔧 Step 6: 스케줄러 등록 (15분)

InvestBrief의 스케줄러 설정 파일 위치 확인:

```bash
cd ~/path/to/investbrief
grep -rn "AsyncIOScheduler\|BackgroundScheduler\|add_job" backend/app/ --include="*.py" | head -5
```

스케줄러 파일에 다음 추가:

```python
from datetime import datetime
from apscheduler.triggers.cron import CronTrigger

# ── 테마 알림 효과 측정 (v3 Phase 3) ──
# 매일 18:05/15/25에 D+30/60/90 가격 갱신
from app.services.theme_alert_tracker import update_alert_returns_for_target

scheduler.add_job(
    lambda: update_alert_returns_for_target(30),
    trigger=CronTrigger(hour=18, minute=5, timezone="Asia/Seoul"),
    id="theme_alert_returns_30d",
    replace_existing=True,
    misfire_grace_time=3600,
)
scheduler.add_job(
    lambda: update_alert_returns_for_target(60),
    trigger=CronTrigger(hour=18, minute=15, timezone="Asia/Seoul"),
    id="theme_alert_returns_60d",
    replace_existing=True,
    misfire_grace_time=3600,
)
scheduler.add_job(
    lambda: update_alert_returns_for_target(90),
    trigger=CronTrigger(hour=18, minute=25, timezone="Asia/Seoul"),
    id="theme_alert_returns_90d",
    replace_existing=True,
    misfire_grace_time=3600,
)

# ── 월간 리포트 (v3 Phase 4) — 매월 1일 09:10 ──
from app.services.theme_alert_analytics import send_monthly_alert_report

scheduler.add_job(
    send_monthly_alert_report,
    trigger=CronTrigger(day=1, hour=9, minute=10, timezone="Asia/Seoul"),
    id="theme_alert_monthly_report",
    replace_existing=True,
    misfire_grace_time=3600 * 24,
)
```

---

## ✅ Step 7: 검증 (15분)

### 검증 1: import 정상 작동

```bash
cd ~/path/to/investbrief/backend
python3 << 'EOF'
from app.models.theme_alert import ThemeAlert, ThemeAlertCandidate
from app.services.theme_alert_service import send_theme_alert
from app.services.theme_alert_tracker import update_alert_returns_for_target
from app.services.theme_alert_analytics import send_monthly_alert_report
print("✅ 모든 import 성공")
EOF
```

### 검증 2: 테이블 생성 확인

```bash
sqlite3 investbrief.db ".schema theme_alerts"
sqlite3 investbrief.db ".schema theme_alert_candidates"
```

### 검증 3: 단위 테스트 (DB 저장만)

```bash
cd ~/path/to/investbrief/backend
python3 << 'EOF'
import asyncio
from app.database import async_session
from app.services.theme_alert_service import send_theme_alert

async def test():
    async with async_session() as db:
        alert_uid = await send_theme_alert(
            theme_id="test_theme",
            theme_name="테스트 테마",
            candidates=[
                {
                    "stock_code": "042660",
                    "stock_name": "한화오션",
                    "sub_theme": "방산",
                    "matched_news_title": "테스트 뉴스",
                },
            ],
            db=db,
            use_inline_buttons=False,
            skip_telegram=True,  # 테스트는 텔레그램 발송 안 함
        )
        print(f"✅ alert_uid: {alert_uid}")

asyncio.run(test())
EOF
```

### 검증 4: DB 데이터 확인

```sql
-- sqlite3 investbrief.db
SELECT * FROM theme_alerts ORDER BY id DESC LIMIT 1;
SELECT * FROM theme_alert_candidates ORDER BY id DESC LIMIT 5;
```

기대: 테스트 행 1건씩 추가됨.

### 검증 5: 통합 검증 (실제 알림 발송)

테마 감지 트리거하거나, 다음 정기 스케줄 발송 후:

```sql
-- 최근 1시간 내 발송된 알림
SELECT id, alert_uid, theme_id, theme_name, sent_at, candidate_count
FROM theme_alerts
WHERE sent_at >= datetime('now', '-1 hour')
ORDER BY sent_at DESC;

-- 후보 종목 정보
SELECT alert_id, stock_code, stock_name, sub_theme, price_at_alert
FROM theme_alert_candidates
WHERE alert_id = (SELECT MAX(id) FROM theme_alerts);
```

---

## 📊 적용 후 자동 측정 KPI

### 즉시 측정 가능 (Phase 1)

```sql
-- KPI A: 일별 알림 발송
SELECT DATE(sent_at) AS d, COUNT(*) AS alerts, SUM(candidate_count) AS candidates
FROM theme_alerts
GROUP BY DATE(sent_at)
ORDER BY d DESC LIMIT 30;

-- KPI B: 테마별 분포
SELECT theme_name, COUNT(*) AS cnt
FROM theme_alerts
GROUP BY theme_name
ORDER BY cnt DESC;

-- KPI C: 가격 스냅샷 성공률
SELECT
    COUNT(*) AS total,
    SUM(CASE WHEN price_at_alert IS NOT NULL THEN 1 ELSE 0 END) AS with_price,
    ROUND(100.0 * SUM(CASE WHEN price_at_alert IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 1) AS success_pct
FROM theme_alert_candidates;
```

### 30일 후 측정 가능 (Phase 3 자동)

```sql
-- KPI E: D+30 평균 수익률 + 코스피 대비 alpha
SELECT
    COUNT(*) AS samples,
    ROUND(AVG(return_30d), 2) AS avg_return,
    ROUND(AVG(kospi_return_30d), 2) AS avg_kospi,
    ROUND(AVG(return_30d - kospi_return_30d), 2) AS avg_alpha
FROM theme_alert_candidates
WHERE return_30d IS NOT NULL;

-- 테마별 30일 수익률
SELECT 
    ta.theme_name,
    COUNT(*) AS samples,
    ROUND(AVG(tac.return_30d), 2) AS avg_return,
    ROUND(AVG(tac.return_30d - tac.kospi_return_30d), 2) AS avg_alpha
FROM theme_alerts ta
JOIN theme_alert_candidates tac ON ta.id = tac.alert_id
WHERE tac.return_30d IS NOT NULL
GROUP BY ta.theme_name
HAVING COUNT(*) >= 3
ORDER BY avg_return DESC;
```

### 1개월 후 측정 가능 (Phase 4 자동)

매월 1일 09:10에 텔레그램으로 자동 발송되는 월간 리포트.

---

## ⚠️ 주의 사항

### A. macOS 환경 (메모리 규칙)

- `python3`, `pip3` 사용
- 가상환경 활성화 후 작업

### B. InvestBrief 운영 영향 최소화

- 측정 인프라 추가는 기존 알림에 영향 없도록
- try-except로 측정 실패해도 알림은 정상 발송
- 운영 중 적용 가능 (다운타임 불필요)

### C. SQLite 한계

- InvestBrief는 SQLite 사용 → 동시 쓰기 제한
- 측정 데이터 누적 → 1년 후 DB 파일 크기 검토 필요
- 백업 권장: 매월 `investbrief.db` 복사

### D. 키움/StockAI 의존성 제거 검증

복사한 코드에 StockAI 고유 import가 남아있지 않은지 확인:

```bash
cd ~/path/to/investbrief
grep -rn "kiwoom\|stockai" backend/app/services/theme_alert_*.py backend/app/models/theme_alert.py 2>/dev/null
```

빈 결과 = 정상.

### E. 매수 매핑 KPI 제외 인지

옵션 2 채택으로 KPI 매수 전환율은 측정 안 됨. 1-2개월 후 필요해지면:
- StockAI에서 별도 매수 매핑 인프라 구축
- 또는 InvestBrief ↔ StockAI 데이터 동기화

---

## 📋 완료 체크리스트

### 코드 작업
- [ ] Step 1: 모델 복사 + import 경로 검증
- [ ] Step 2: 발송 서비스 복사 + 키움/텔레그램 의존성 수정
- [ ] Step 3: tracker/analytics 복사 + 의존성 수정
- [ ] Step 4: theme_radar_service.py:248의 `_send_theme_alert`에 측정 통합
- [ ] `send_theme_alert`에 `skip_telegram=True` 매개변수 추가

### 인프라
- [ ] Step 5: DB 마이그레이션 (theme_alerts, theme_alert_candidates 테이블)
- [ ] Step 6: 스케줄러 등록 (Phase 3 D+30/60/90 + Phase 4 월간)

### 검증
- [ ] Step 7-1: 모든 import 성공
- [ ] Step 7-2: 테이블 생성 확인
- [ ] Step 7-3: 단위 테스트 (DB 저장)
- [ ] Step 7-4: 단위 테스트 검증 (SQL)
- [ ] Step 7-5: 통합 검증 (실제 알림 → DB 기록)

### 운영
- [ ] 1주 후: ThemeAlert 누적 5건 이상 확인
- [ ] 30일 후: D+30 가격 추적 자동 작동 확인
- [ ] 1-2개월 후: KPI 분석 → 지시서 6/7/8/9 적용 결정

---

## 🎯 핵심 한 줄 요약

**InvestBrief의 `_send_theme_alert` 함수 끝에 `send_theme_alert(skip_telegram=True)` 호출 추가하면 측정 인프라 작동 시작.**

나머지는 모두 인프라 준비 작업 (모델 복사, 스케줄 등록 등).

---

## 💡 솔직한 마지막 의견

### 옵션 2의 합리성

DB 분리 상황에서 옵션 2가 가장 실용적:
- 알림 발송과 측정이 같은 프로젝트
- 추가 인프라 (HTTP API) 불필요
- DB 마이그레이션 위험 회피

### 단점 인정

코드 중복은 피할 수 없음. 향후 양쪽 프로젝트 측정 코드 동기화 필요.

**완화 방안 (선택):** StockAI의 v3 인프라 코드 제거 (사용 안 하므로). 또는 InvestBrief를 메인 측정 시스템으로 두고 StockAI는 매수 매핑만 제공하는 종속 관계로 정리.

이건 1-2개월 후 데이터 보고 결정.

### 작업 시간 추정

- 숙련 개발자: 2시간
- 신중하게 검증하며: 3-4시간
- Claude Code에 위임: 30분 ~ 1시간 (단, 검증은 Ko~님이)

본 지시서를 Claude Code에 전달하면 자동 적용 가능합니다.
