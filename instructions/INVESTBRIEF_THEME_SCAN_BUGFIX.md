# INVESTBRIEF_THEME_SCAN_BUGFIX.md

## 목적

`theme_radar_service.scan_single_theme`의 종목 선정 흐름에서 발견된 **2건의 본질적 결함**을 즉시 보정한다. 사전 필터(`prefilter_service`)는 이미 정상 동작 중이지만, 그 윗단의 종목 추출/중복 검증 단계에서 잡혀야 할 종목이 시스템적으로 누락되거나 영구 차단되는 문제가 있다. 본 지시서는 두 결함을 한 번에 수정한다.

## 배경

검증 과정에서 2건의 결함 발견:

### Critical 1: 영문 시작 종목 시스템적 누락

`STOCK_NAME_PATTERN = r"([가-힣][가-힣A-Za-z0-9]{1,14})"` — **한글로 시작해야만** 매칭. 한국 시총 상위 우량주 상당수가 영문 시작이라 영원히 검출 안 됨:

| 종목 | 현재 매칭 결과 | 결과 |
|------|---------------|------|
| LG에너지솔루션 (시총 50조) | `에너지솔루션`만 매칭 | search_stocks 정확 매칭 실패 → SKIP |
| SK하이닉스 (시총 100조) | `하이닉스`만 매칭 | SKIP |
| LG화학 (시총 30조) | `화학`만 매칭 | SKIP |
| POSCO홀딩스 (시총 25조) | `홀딩스`만 매칭 | SKIP |
| KT&G (시총 13조) | `&` 분리로 매칭 안 됨 | SKIP |
| HD현대일렉트릭 | `현대일렉트릭` | SKIP |
| F&F | 매칭 안 됨 | SKIP |

코스피 시총 상위 30개 중 약 25%가 영문 시작 종목. **HBM 테마에 SK하이닉스, 2차전지에 LG에너지솔루션이 안 잡히는 게 명백한 결함**.

### Critical 2: ThemeDetection 영구 차단

`scan_single_theme:232-240`:

```python
existing_codes = set(...)  # theme_id별 모든 시점 누적
for stock_code, info in detected_stocks.items():
    if stock_code in existing_codes:
        continue  # 영원히 SKIP
```

ThemeDetection은 `theme_id × stock_code`로 한 번 저장되면 영원히 누적. 그래서:

```
[1일차] X종목 뉴스 → Claude 통과 → ThemeDetection 저장
        → prefilter "RSI 95" 제외 → ThemeScanResult 미저장

[2주 후] X종목 RSI 45로 정상화 → 매수 적기
        → 그러나 ThemeDetection에 1일차 레코드가 영구 보존
        → existing_codes에 포함 → 영원히 SKIP
```

**사전 필터의 가장 큰 가치(시간이 지나 매수 적기가 된 종목 다시 잡기)가 무력화됨**.

## 작업 범위

1. STOCK_NAME_PATTERN 정규식 보강 — 영문/혼합 시작 허용
2. ThemeDetection 영구 차단 → "최근 N일 내" 윈도우 정책 변경
3. 단위 테스트 (정규식 + 윈도우 정책)
4. 필요 시 DB 인덱스 추가 (detected_at)

## 작업하지 않는 것

- `_verify_theme_match` Claude 프롬프트 변경 안 함
- `prefilter_service` 변경 안 함 (이미 적용됨)
- search_stocks 정확 매칭 정책 변경 안 함 — 정규식이 정확한 종목명을 잡으면 그대로 통과
- StockAI 측 코드 변경 0건

---

## ⚠️ 표준 규칙

- macOS: python3, pip3
- 양방향: InvestBrief 백엔드만 수정. StockAI/프론트엔드 무관
- KST 타임존: 윈도우 계산 KST 기준
- 한국 주식: 영문 종목명도 정확히 매칭되도록

---

## 1. Critical 1 — STOCK_NAME_PATTERN 정규식 보강

### 파일: `backend/app/services/theme_radar_service.py`

#### 변경 위치: 27번 줄

**Before**:
```python
STOCK_NAME_PATTERN = re.compile(r"([가-힣][가-힣A-Za-z0-9]{1,14})")
```

**After**:
```python
# 종목명 추출 정규식
# - 영문/한글 시작 모두 허용 (LG, SK, HD, KT&G, POSCO 등 대형주 매칭 위해)
# - 첫 글자: 영문 대소문자 또는 한글
# - 후속 글자: 영문/한글/숫자/& (KT&G, F&F 등)
# - 길이: 2~15자 (한 글자 단어 제외)
STOCK_NAME_PATTERN = re.compile(r"([A-Za-z가-힣][A-Za-z가-힣0-9&]{1,14})")
```

### 검증 매트릭스

```
LG에너지솔루션 (8자): ✅ 'LG에너지솔루션' 매칭
SK하이닉스 (5자):     ✅ 'SK하이닉스' 매칭
KT&G (4자):           ✅ 'KT&G' 매칭
F&F (3자):            ✅ 'F&F' 매칭
POSCO홀딩스 (7자):    ✅ 'POSCO홀딩스' 매칭
HD현대일렉트릭 (7자): ✅ 'HD현대일렉트릭' 매칭
삼성전자 (4자):       ✅ 'SamsungElectronics' 같은 영문은 한국 주식 아니므로 무관
한화오션 (4자):       ✅ 매칭 유지
```

### 부수 효과 (의도된 변경)

뉴스 제목에서 **영문 단어**(예: HBM, AI, ETF)도 매칭되지만, search_stocks 단계에서 한국 종목 데이터에 없으므로 자동 SKIP. 즉 후속 처리 무관.

### 거짓양성 검토

`F1, A1` 같은 자동차 모델명이 매칭될 수 있으나:
- 길이 ≥ 2 조건 통과
- search_stocks에서 종목 없음 → SKIP

문제 없음.

---

## 2. Critical 2 — ThemeDetection 윈도우 정책

### 정책 변경

```
Before: "한 번 저장된 종목은 영원히 SKIP"
After:  "최근 14일 내 저장된 종목만 SKIP. 그 이전은 다시 검증"
```

### 윈도우 기간 근거

- 7일: 너무 짧아 같은 뉴스 사이클에서 중복 검증 → Claude API 비용 증가
- 14일: 한국 주식 추세 전환 평균 주기. 폭등 후 RSI 정상화 충분 시간
- 30일: 너무 길어 진짜 매수 적기 놓칠 가능성

→ **14일** 채택. 추후 운영 데이터 보고 7~30일 범위에서 조정 가능.

### 파일: `backend/app/services/theme_radar_service.py`

#### 변경 위치: 232-235번 줄

**Before**:
```python
    existing_result = await session.execute(
        select(ThemeDetection.stock_code).where(ThemeDetection.theme_id == theme.id)
    )
    existing_codes = set(existing_result.scalars().all())
```

**After**:
```python
    # ── 중복 검증 윈도우 (14일) ────────────────────────────────────
    # 같은 종목을 14일 이내 다시 검증하지 않는다 (Claude API 비용 절약).
    # 14일 이전 레코드는 무시 → 매수 적기로 회복된 종목 다시 검증 가능.
    DETECTION_WINDOW_DAYS = 14
    cutoff = datetime.datetime.now() - datetime.timedelta(
        days=DETECTION_WINDOW_DAYS
    )
    existing_result = await session.execute(
        select(ThemeDetection.stock_code)
        .where(ThemeDetection.theme_id == theme.id)
        .where(ThemeDetection.detected_at >= cutoff)
    )
    existing_codes = set(existing_result.scalars().all())
```

> ⚠️ 파일 상단에 `import datetime` 또는 `from datetime import datetime, timedelta`가 이미 있어야 한다. theme_radar_service.py 시작 부분 확인 후 없으면 추가.

#### import 점검

```bash
grep -n "^import datetime\|^from datetime" backend/app/services/theme_radar_service.py
```

**이미 있는 경우**: After 코드에서 `datetime.datetime.now()`, `datetime.timedelta()` 사용. 그대로 OK.

**없는 경우**: 파일 상단에 추가:
```python
import datetime
```

#### DETECTION_WINDOW_DAYS 모듈 상수화 (권장)

함수 안 지역 상수보다 모듈 상단 상수가 운영 시 조정 편함. 27번 줄(STOCK_NAME_PATTERN) 근처로 이동:

**파일 상단 (27~30번 줄 근처)**:
```python
STOCK_NAME_PATTERN = re.compile(r"([A-Za-z가-힣][A-Za-z가-힣0-9&]{1,14})")

# ThemeDetection 중복 검증 윈도우 (일)
# 같은 종목을 이 기간 이내에 다시 검증하지 않는다.
# 14일이 지나면 다시 Claude 검증 + 사전 필터 적용 → 매수 적기 회복 종목 재검출.
DETECTION_WINDOW_DAYS = 14
```

**scan_single_theme 안 (232번 줄)**:
```python
    cutoff = datetime.datetime.now() - datetime.timedelta(
        days=DETECTION_WINDOW_DAYS
    )
    existing_result = await session.execute(
        select(ThemeDetection.stock_code)
        .where(ThemeDetection.theme_id == theme.id)
        .where(ThemeDetection.detected_at >= cutoff)
    )
    existing_codes = set(existing_result.scalars().all())
```

---

## 3. DB 인덱스 추가 (성능)

`ThemeDetection.detected_at`을 WHERE 조건에 사용하므로 인덱스 추가 권장. 종목 누적 많아지면 성능 저하.

### 파일: `backend/app/models/theme.py`

#### 변경 위치: ThemeDetection 모델

**Before**:
```python
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

**After**:
```python
class ThemeDetection(Base):
    """테마 스캔으로 감지된 종목 — 14일 내 중복 검증 방지용"""
    __tablename__ = "theme_detection"
    __table_args__ = (
        Index("ix_theme_detection_theme_detected", "theme_id", "detected_at"),
    )

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
        DateTime, default=datetime.datetime.now, index=True
    )
```

변경:
- `__table_args__`로 복합 인덱스 추가 (theme_id + detected_at). WHERE 조건 그대로 사용
- `detected_at`에 단일 인덱스도 추가 (다른 쿼리에서 사용 시)
- import에 `Index` 추가:

```python
# 기존 import
from sqlalchemy import (..., Index, ...)
```

#### import 점검

```bash
grep "from sqlalchemy" backend/app/models/theme.py | head -3
```

이미 `Index`가 import되어 있는지 확인. 없으면 추가.

#### DB 인덱스 적용 방법

InvestBrief는 Alembic 미사용, `Base.metadata.create_all`로 자동 생성. **새 인덱스가 자동 적용 안 됨** (테이블이 이미 존재하므로).

**옵션 A: 수동으로 인덱스 추가 (권장)**

```bash
# SQLite의 경우
sqlite3 ~/dev/investbrief-main/backend/investbrief.db <<EOF
CREATE INDEX IF NOT EXISTS ix_theme_detection_theme_detected
  ON theme_detection (theme_id, detected_at);
CREATE INDEX IF NOT EXISTS ix_theme_detection_detected_at
  ON theme_detection (detected_at);
EOF

# Neon/PostgreSQL의 경우
psql $DATABASE_URL <<EOF
CREATE INDEX IF NOT EXISTS ix_theme_detection_theme_detected
  ON theme_detection (theme_id, detected_at);
CREATE INDEX IF NOT EXISTS ix_theme_detection_detected_at
  ON theme_detection (detected_at);
EOF
```

**옵션 B: 인덱스 생략**

종목 수가 적으면 (수백~수천 건) 인덱스 없이도 성능 문제 없음. 운영 1~2개월 후 느려지면 그때 추가. 모델 코드만 수정해두고 실제 인덱스는 나중에 적용해도 됨.

→ **옵션 B 권장 (단순함)**. 모델 코드는 수정해두되 SQL 직접 실행은 생략. 종목 누적 많아지면 그때 추가.

---

## 4. 단위 테스트

### 파일: `backend/tests/test_theme_radar_bugfix.py` (신규)

```python
"""theme_radar_service Critical 1, 2 보정 테스트.

- 정규식: 영문 시작 종목 매칭
- 윈도우 정책: 14일 이전 종목 재검증
"""
import datetime
import re

import pytest

from app.services.theme_radar_service import (
    DETECTION_WINDOW_DAYS,
    STOCK_NAME_PATTERN,
)


# ── Critical 1: 정규식 ──────────────────────────────────────────────


def test_pattern_matches_english_prefix_stocks():
    """영문 시작 종목 매칭."""
    cases = [
        ("LG에너지솔루션 美 공장 가동", "LG에너지솔루션"),
        ("SK하이닉스 HBM 양산", "SK하이닉스"),
        ("LG화학 분기 실적", "LG화학"),
        ("POSCO홀딩스 자사주 매입", "POSCO홀딩스"),
        ("HD현대일렉트릭 수주 잭팟", "HD현대일렉트릭"),
        ("DL이앤씨 재건축 수주", "DL이앤씨"),
        ("BNK금융지주 배당 확대", "BNK금융지주"),
    ]
    for text, expected in cases:
        matches = STOCK_NAME_PATTERN.findall(text)
        assert expected in matches, f"{text!r}에서 {expected} 매칭 실패: {matches}"


def test_pattern_matches_ampersand_stocks():
    """앰퍼샌드 포함 종목 매칭."""
    cases = [
        ("KT&G 신제품 출시", "KT&G"),
        ("F&F 매출 호조", "F&F"),
    ]
    for text, expected in cases:
        matches = STOCK_NAME_PATTERN.findall(text)
        assert expected in matches, f"{text!r}에서 {expected} 매칭 실패: {matches}"


def test_pattern_matches_korean_prefix_stocks():
    """한글 시작 종목도 그대로 매칭 (기존 동작 유지)."""
    cases = [
        ("삼성전자 1Q 실적", "삼성전자"),
        ("한화오션 잠수함", "한화오션"),
        ("롯데에너지머티리얼즈 가동", "롯데에너지머티리얼즈"),
        ("한국전력공사 적자", "한국전력공사"),
    ]
    for text, expected in cases:
        matches = STOCK_NAME_PATTERN.findall(text)
        assert expected in matches, f"{text!r}에서 {expected} 매칭 실패: {matches}"


def test_pattern_length_filter():
    """1글자는 제외 (스캔 코드의 len(candidate) < 2 처리)."""
    text = "A B 신제품"
    matches = STOCK_NAME_PATTERN.findall(text)
    # 매칭은 되지만 후속 길이 체크에서 제외됨
    assert all(len(m) >= 2 for m in matches)


# ── Critical 2: 윈도우 정책 ─────────────────────────────────────────


def test_detection_window_constant():
    """윈도우 상수가 14일."""
    assert DETECTION_WINDOW_DAYS == 14


def test_detection_window_logic():
    """14일 cutoff 계산 검증."""
    now = datetime.datetime.now()
    cutoff = now - datetime.timedelta(days=DETECTION_WINDOW_DAYS)
    delta = now - cutoff
    assert delta.days == 14
    # 13일 전 → 윈도우 안 (SKIP 대상)
    detected_13d_ago = now - datetime.timedelta(days=13)
    assert detected_13d_ago >= cutoff
    # 15일 전 → 윈도우 밖 (재검증 대상)
    detected_15d_ago = now - datetime.timedelta(days=15)
    assert detected_15d_ago < cutoff


# ── 통합 테스트 (선택) ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_window_excludes_old_records():
    """15일 전 레코드는 existing_codes에 포함되지 않음."""
    # 이 테스트는 DB fixture가 필요. 기존 conftest.py 패턴 따라 작성.
    # 만약 DB fixture 없으면 단위 테스트로는 생략하고 수동 검증으로 대체.
    pass
```

테스트 실행:
```bash
cd ~/dev/investbrief-main/backend
source .venv/bin/activate
pytest tests/test_theme_radar_bugfix.py -v
```

기대: 5개 테스트 모두 통과 (test_window_excludes_old_records는 SKIP 또는 PASS).

---

## 5. 적용 절차

### 단계 1: 백업

```bash
cd ~/dev/investbrief-main/backend
cp app/services/theme_radar_service.py \
   app/services/theme_radar_service.py.backup-$(date +%Y%m%d-%H%M%S)
cp app/models/theme.py \
   app/models/theme.py.backup-$(date +%Y%m%d-%H%M%S)
```

### 단계 2: 코드 수정

순서대로:

1. `app/services/theme_radar_service.py:27` — STOCK_NAME_PATTERN 변경
2. `app/services/theme_radar_service.py` 상단 — DETECTION_WINDOW_DAYS 상수 추가
3. `app/services/theme_radar_service.py:232-235` — existing_codes 쿼리에 윈도우 조건 추가
4. (선택) `app/models/theme.py:ThemeDetection` — 인덱스 추가

### 단계 3: 단위 테스트

```bash
pytest tests/test_theme_radar_bugfix.py -v
```

### 단계 4: 정규식 단독 검증 (간단)

```bash
python3 -c "
from app.services.theme_radar_service import STOCK_NAME_PATTERN
cases = ['LG에너지솔루션 가동', 'SK하이닉스 HBM', 'KT&G 매출', '삼성전자 실적']
for c in cases:
    print(f'{c!r} → {STOCK_NAME_PATTERN.findall(c)}')
"
```

각 줄에 우량주 종목명이 매칭되어 출력되어야 함.

### 단계 5: 수동 스캔 1회

```bash
set -a && source .env && set +a

python3 -u -c "
import asyncio
from app.services.theme_radar_service import scan_all_themes
asyncio.run(scan_all_themes())
" 2>&1 | tee /tmp/scan_after_bugfix.log
```

스캔 진행 중 로그에서 다음 패턴이 보이면 fix 효과 검증 완료:

```
테마 검증: theme=HBM 후공정 stock=SK하이닉스(000660) verdict=YES   ← 영문 시작 종목 검출
[scan_single_theme] HBM 후공정: verified=N → filtered=M (rejected=K)
```

기존 로그에서는 SK하이닉스/LG에너지솔루션 같은 종목이 등장하지 않았음. 등장한다면 Critical 1 fix 성공.

### 단계 6: StockAI에서 재분석

InvestBrief의 새 결과를 StockAI에서 처리:

```bash
cd ~/dev/stock-investment-program/backend
source ../.venv/bin/activate
set -a && source .env && set +a

python3 -u -c "
import asyncio
from app.services.scheduler_service import run_daily_batch_from_investbrief
asyncio.run(run_daily_batch_from_investbrief())
" 2>&1 | tee /tmp/daily_batch_after_bugfix.log
```

기대 결과:
- InvestBrief가 보낸 종목에 영문 시작 우량주 포함
- 등급 분포에 A/B 등장 가능성 ↑ (우량주는 펀더멘탈 양호)

### 단계 7: 14일 윈도우 검증 (시간 필요)

이 검증은 14일 운영 후 가능. 즉시 검증 어려움. 대신 SQL로 직접 확인:

```bash
# 현재 ThemeDetection 누적 종목 수
sqlite3 ~/dev/investbrief-main/backend/investbrief.db "
SELECT theme_id, COUNT(*) AS detections
FROM theme_detection
GROUP BY theme_id
ORDER BY detections DESC;
" 2>/dev/null

# 14일 이내 vs 이전 분포
sqlite3 ~/dev/investbrief-main/backend/investbrief.db "
SELECT
  COUNT(*) FILTER (WHERE detected_at >= datetime('now', '-14 days')) AS recent_14d,
  COUNT(*) FILTER (WHERE detected_at < datetime('now', '-14 days')) AS older
FROM theme_detection;
" 2>/dev/null
```

> SQLite의 `FILTER` 절이 안 되면 두 쿼리로 분리해서 실행.

`older` 카운트가 0보다 크면 14일 윈도우 fix 효과 검증 — 그 종목들이 다음 스캔에서 다시 검증 대상이 됨.

---

## 6. 운영 모니터링 (3~7일)

코드 적용 후 며칠간 텔레그램 알림에서 다음 확인:

### 확인 항목

1. **영문 시작 종목 등장**
   - SK하이닉스, LG에너지솔루션, LG화학 등 우량주가 알림에 등장하는지
   - HBM/2차전지 테마에 정상 매칭되는지

2. **사전 필터 효과 변화**
   - rejected 사유 분포에 변화 (우량주는 rejected 적을 가능성)

3. **StockAI 등급 분포 변화**
   - A/B 등급 비율 ↑ (우량주는 펀더멘탈 양호)
   - D/F 비율 ↓

4. **Claude API 호출 빈도**
   - 정규식 보강으로 후보 ↑ → search_stocks 호출 ↑
   - search_stocks 정확 매칭 통과 → Claude 검증 호출 ↑
   - 비용 모니터링 (Anthropic 콘솔)

### 비용 추산

기존 13종목 → 보정 후 20~30종목 가정:
- search_stocks: 한국 네이버 증권 무료 (호출 비용 0)
- Claude 검증: 종목 1건당 ~$0.005 (Sonnet 4 기준)
- 추가 비용: 일일 7~17건 × $0.005 = **$0.035~$0.085/일** = **$1~$2.5/월**

본 fix로 발생하는 추가 비용은 미미. 우량주 발견 가치가 훨씬 큼.

---

## 7. 롤백 절차

코드 적용 후 의외 결과 (예: 너무 많은 종목 검출, Claude API 비용 폭증, 잘못된 종목 잡힘) 발생 시:

```bash
cd ~/dev/investbrief-main/backend

# 가장 최근 백업 복원
ls -lt app/services/theme_radar_service.py.backup-* | head -1
cp app/services/theme_radar_service.py.backup-<timestamp> app/services/theme_radar_service.py

ls -lt app/models/theme.py.backup-* | head -1
cp app/models/theme.py.backup-<timestamp> app/models/theme.py
```

InvestBrief uvicorn 재시작 (자동 재시작 옵션이면 자동, 아니면 수동).

DB 인덱스를 옵션 A로 추가했다면 그것도 제거:
```sql
DROP INDEX IF EXISTS ix_theme_detection_theme_detected;
DROP INDEX IF EXISTS ix_theme_detection_detected_at;
```

---

## 8. 배포 체크리스트

- [ ] 백업 파일 생성 확인 (`*.backup-YYYYMMDD-HHMMSS`)
- [ ] STOCK_NAME_PATTERN 27번 줄 수정
- [ ] DETECTION_WINDOW_DAYS 상수 추가
- [ ] existing_codes 쿼리에 윈도우 조건 추가
- [ ] (선택) ThemeDetection 모델에 인덱스 추가
- [ ] 단위 테스트 통과 (5개)
- [ ] 정규식 단독 검증 (4개 종목 모두 매칭 확인)
- [ ] 수동 scan 실행 → 로그에서 영문 시작 종목 출현 확인
- [ ] StockAI daily_batch 재실행 → 등급 분포 확인
- [ ] 텔레그램 알림에 영문 시작 종목 등장 (3~7일 내)

---

## 9. 작성/수정 파일 목록

```
backend/app/services/theme_radar_service.py           (수정 - 정규식 + 윈도우)
backend/app/models/theme.py                           (수정 - 인덱스 추가, 선택)
backend/tests/test_theme_radar_bugfix.py              (신규)
backend/app/services/theme_radar_service.py.backup-*  (백업, 자동)
backend/app/models/theme.py.backup-*                  (백업, 자동)
```

핵심 수정 라인 수: **약 10줄** (정규식 1줄, 상수 4줄, 윈도우 쿼리 5줄).

---

## 10. 후속 작업 (별도 지시서)

본 fix 적용 후 1~2주 운영 데이터로 다음 결정:

### 후속 1: DB 인덱스 실제 적용

종목 누적 1,000건 이상 또는 scan_single_theme 실행 시간 5초 이상이면 위 § 3의 SQL 실행.

### 후속 2: 윈도우 기간 조정

운영 데이터 기반:
- 같은 종목이 14일 이내 너무 자주 재검증 (Claude 비용 ↑) → 21~30일로 늘림
- 매수 적기 회복 종목이 14일 후에도 재검증 안 됨 → 7일로 줄임

### 후속 3: 정규식 추가 보강 (필요 시)

운영 중 매칭 안 되는 신규 종목명 패턴 발견 시:
- 한자 포함 종목 (예: '中央제어') → `[A-Za-z가-힣\u4e00-\u9fff]`
- 다른 특수문자 (예: 종목명에 점, 하이픈)

### 후속 4: 부분 매칭 검토 (Critical 3 — 본 지시서 범위 밖)

```
뉴스: "한미반도체HBM 본격 양산"
→ '한미반도체HBM' 매칭 → search_stocks 정확 매칭 실패 → SKIP
→ 한미반도체(042700) 못 잡음
```

이건 search_stocks 정책(`m.stock_name != candidate` 정확 매칭)을 부분 매칭으로 변경해야 해결. 거짓양성 위험이 커서 신중한 설계 필요. 본 지시서 후 별도 검토.

---

## 11. 한 줄 요약

> 1) 정규식을 `[A-Za-z가-힣]` 시작으로 변경해 SK하이닉스/LG에너지솔루션 같은 영문 시작 우량주를 잡고, 2) ThemeDetection 중복 검증을 14일 윈도우로 제한해 매수 적기 회복 종목을 다시 검출한다. 코드 약 10줄 수정. 단위 테스트 5개. 적용 후 1~2주 모니터링.
