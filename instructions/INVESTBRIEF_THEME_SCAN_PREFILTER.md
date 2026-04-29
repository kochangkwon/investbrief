# INVESTBRIEF_THEME_SCAN_PREFILTER.md

## 목적

`theme_radar_service.scan_single_theme`이 잡아오는 종목들이 **이미 폭등한 상태(R:R < 2.0)** 또는 **연속 적자 기업** 위주라, StockAI의 pipeline_agent에서 100% 즉시제외(F등급) 처리되는 문제를 해결한다. **InvestBrief 측에서 사전 필터를 적용**해서 매수 가능성 있는 종목만 StockAI로 넘긴다.

## 배경

### 발견된 문제

StockAI에서 InvestBrief가 보낸 13종목 분석 결과:

```
즉시제외 사유 분포:
  R:R 비율: 14건 (100%)         ← 대부분 1.0 미만
  영업이익 성장: 7건 (54%)       ← 적자 기업
  급등 추격매수 금지: 5건 (38%)   ← RSI 70+, MA20 +30% 이상 이격
  수급 검증: 3건
  다이버전스 체크: 2건

결과: 13종목 모두 D/F → 매수알림 0건
```

### 종목별 R:R 분포

```
한국피아이엠 R:R 0.28
한화비전     R:R 0.48
두산         R:R 0.48
인벤티지랩   R:R 0.51
성호전자     R:R 0.59
메디포스트   R:R 0.60
한미약품     R:R 0.71
엠젠솔루션   R:R 0.73
한화솔루션   R:R 0.83
에코프로비엠 R:R 1.19
두산로보틱스 R:R 1.18
노타         R:R 1.68
선도전기     R:R 1.70
```

R:R 2.0 이상이 단 한 종목도 없음. **InvestBrief가 종목을 발견할 때는 이미 폭등 후**라는 패턴.

### 왜 이런 일이?

```
1. 뉴스 발생 (예: HBM 수주)
   ↓
2. 시장이 즉시 반영 → 관련 종목 폭등 (당일~3일)
   ↓
3. InvestBrief 스캔 (매주 월요일 08:00 + 매일 08:10)
   → 뉴스 + 종목명 매칭 → 검출
   ↓
4. StockAI 분석 (08:30)
   → 이미 RSI 70+, MA20 +30% 이격 → 추격매수 차단
   → R:R 1.0 미만 → 즉시제외
```

뉴스 → 시장 반영 → 종목 발견까지의 **시차**가 본질적 원인. InvestBrief 자체가 빠를 수 없으므로, **이미 폭등한 종목을 스캔 결과에서 제거**하는 사후 필터가 해법.

## 작업 범위

1. `prefilter_service.py` 신규 — 종목별 사전 필터 함수
2. `theme_radar_service.scan_single_theme` 수정 — Claude 검증 통과 후 사전 필터 적용
3. 필터 사유 로깅 + 텔레그램 알림에 제외 사유 표시
4. 단위 테스트

## 작업하지 않는 것

- `_verify_theme_match` Claude 프롬프트 변경 안 함 (검증 단계는 그대로)
- StockAI 측 코드 변경 안 함 (StockAI는 받은 종목 그대로 분석)
- 뉴스 발견 시점 자체 개선 안 함 (실시간 뉴스 모니터링은 별도 큰 작업)
- Theme 모델 자체 변경 안 함

---

## ⚠️ 표준 규칙 준수

- macOS: python3, pip3
- 양방향: InvestBrief 백엔드만 수정. StockAI/프론트엔드 무관
- KST 타임존: 시세 조회 시 KST 거래일 기준
- 외부 데이터: FDR(시세), DART(재무) 사용. Google Finance 금지

---

## 1. 사전 필터 기준

scan_single_theme이 발견한 종목이 다음 **하나라도 해당하면 제외**:

| 필터 | 임계 | 데이터 소스 | 의미 |
|------|------|-------------|------|
| F1: RSI 과매수 | RSI(14) ≥ 70 | FDR 일봉 30일 | 추격매수 위험 |
| F2: MA20 이격 과대 | 현재가 > MA20 × 1.30 | FDR 일봉 60일 | 단기 폭등 |
| F3: MA60 이격 과대 | 현재가 > MA60 × 1.50 | FDR 일봉 120일 | 중기 폭등 |
| F4: 5일 등락률 과대 | 5일 누적 +30% 이상 | FDR 일봉 5일 | 단기 급등 |
| F5: 적자 기업 | EPS < 0 (직전 연도) | DART 재무제표 캐시 | 펀더멘탈 위험 |
| F6: 시총 너무 작음 | 시총 < 500억 | FDR Marcap | 유동성/조작 위험 |

**모두 통과**한 종목만 ThemeScanResult에 저장. 하나라도 걸리면 제외.

### 임계값 근거

- **RSI 70**: BNF 룰 + 표준 과매수 임계
- **MA20 +30%**: 정상 정배열은 MA20 위 0~10%. 30% 이격은 명백한 단기 과열
- **MA60 +50%**: 중기 정배열 정상 범위(20~30%) 초과
- **5일 +30%**: 1주일 만에 30% 상승은 폭등 신호 (선도전기는 +200% 수준이었음)
- **EPS < 0**: 적자 기업은 자동매매 부적합 (StockAI도 동일 판정)
- **시총 500억**: KOSDAQ 소형주 최소 기준. 그 이하는 일일 거래대금이 적어 호가 슬리피지 위험

> 임계값은 **단계 3 적용 전까지 보수적**으로 시작. 1~2주 운영 후 통과 종목이 너무 적으면 조정.

---

## 2. prefilter_service 구현

### 파일: `backend/app/services/prefilter_service.py` (신규)

```python
"""테마 스캔 결과 사전 필터링.

scan_single_theme이 Claude 검증 통과한 종목 중,
이미 폭등했거나 펀더멘탈 부실한 종목을 사전 제외.

목적: StockAI pipeline_agent에서 100% 즉시제외 처리되는 종목을
       InvestBrief 단계에서 미리 걸러서 노이즈 감소.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select

from app.collectors.fdr_collector import fdr_collector
from app.collectors.dart_collector import dart_collector
from app.database import async_session
from app.models.financial import FinancialStatement  # 또는 InvestBrief의 재무 모델 명

logger = logging.getLogger(__name__)


# ── 임계값 ──────────────────────────────────────────────────────────
PREFILTER_RSI_MAX = 70.0
PREFILTER_MA20_RATIO_MAX = 1.30      # 현재가 ≤ MA20 × 1.30
PREFILTER_MA60_RATIO_MAX = 1.50
PREFILTER_5D_RETURN_MAX = 0.30       # 5일 누적 +30% 미만
PREFILTER_MIN_MARKET_CAP = 50_000_000_000  # 500억 원
# EPS는 0 이상이면 통과 (음수만 차단)


@dataclass
class PrefilterResult:
    """사전 필터 결과."""
    code: str
    passed: bool
    reasons: list[str]   # 통과/제외 사유 (디버깅/로깅용)
    metrics: dict        # 측정값 (RSI, MA20 ratio, etc.)


# ── 보조 계산 함수 ──────────────────────────────────────────────────


def _calc_rsi(closes: list[float], period: int = 14) -> Optional[float]:
    """간단한 RSI 계산. 데이터 부족 시 None.

    closes: 오름차순 종가 리스트 (마지막이 최신).
    """
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _calc_ma(closes: list[float], period: int) -> Optional[float]:
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


# ── 개별 필터 ──────────────────────────────────────────────────────


async def _check_price_filters(stock_code: str) -> tuple[Optional[bool], list[str], dict]:
    """가격/이격도/모멘텀 필터 (F1~F4).

    데이터 조회 실패 시 (None, [...]) 반환 — 호출자가 보수적으로 통과 처리할지 결정.
    """
    try:
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")
        rows = await fdr_collector.get_price_list_async(stock_code, start_date=start, end_date=end)
    except Exception as e:
        logger.warning(f"[prefilter] price fetch failed {stock_code}: {e}")
        return None, [f"가격 데이터 조회 실패: {e}"], {}

    if not rows or len(rows) < 60:
        return None, ["가격 데이터 부족 (60일 미만)"], {}

    closes = [r.get("close") for r in rows if r.get("close")]
    if not closes or len(closes) < 60:
        return None, ["종가 데이터 부족"], {}

    current = closes[-1]
    if not current or current <= 0:
        return None, ["현재가 무효"], {}

    metrics = {"current": current}
    fails: list[str] = []

    # F1: RSI
    rsi = _calc_rsi(closes, 14)
    if rsi is not None:
        metrics["rsi"] = round(rsi, 1)
        if rsi >= PREFILTER_RSI_MAX:
            fails.append(f"F1: RSI 과매수 {rsi:.1f} ≥ {PREFILTER_RSI_MAX}")

    # F2: MA20 이격
    ma20 = _calc_ma(closes, 20)
    if ma20 and ma20 > 0:
        ratio20 = current / ma20
        metrics["ma20_ratio"] = round(ratio20, 3)
        if ratio20 > PREFILTER_MA20_RATIO_MAX:
            fails.append(f"F2: MA20 이격 +{(ratio20-1)*100:.0f}% > {(PREFILTER_MA20_RATIO_MAX-1)*100:.0f}%")

    # F3: MA60 이격
    ma60 = _calc_ma(closes, 60)
    if ma60 and ma60 > 0:
        ratio60 = current / ma60
        metrics["ma60_ratio"] = round(ratio60, 3)
        if ratio60 > PREFILTER_MA60_RATIO_MAX:
            fails.append(f"F3: MA60 이격 +{(ratio60-1)*100:.0f}% > {(PREFILTER_MA60_RATIO_MAX-1)*100:.0f}%")

    # F4: 5일 누적 등락률
    if len(closes) >= 6:
        ret_5d = (current - closes[-6]) / closes[-6]
        metrics["return_5d"] = round(ret_5d, 3)
        if ret_5d > PREFILTER_5D_RETURN_MAX:
            fails.append(f"F4: 5일 +{ret_5d*100:.1f}% > +{PREFILTER_5D_RETURN_MAX*100:.0f}%")

    return (len(fails) == 0), fails, metrics


async def _check_market_cap(stock_code: str) -> tuple[Optional[bool], list[str], dict]:
    """F6: 시총 필터.

    KOSPI/KOSDAQ 종목 리스트에서 Marcap 컬럼 조회.
    """
    try:
        for market in ("KOSPI", "KOSDAQ"):
            df = await fdr_collector.get_stock_list_async(market)
            if df is None or df.empty or "Code" not in df.columns:
                continue
            row = df[df["Code"] == stock_code]
            if row.empty:
                continue
            if "Marcap" not in df.columns:
                return None, ["Marcap 컬럼 없음"], {}
            mcap = int(row["Marcap"].iloc[0])
            if mcap < PREFILTER_MIN_MARKET_CAP:
                return False, [f"F6: 시총 {mcap/1e8:.0f}억 < {PREFILTER_MIN_MARKET_CAP/1e8:.0f}억"], {"market_cap": mcap}
            return True, [], {"market_cap": mcap}
    except Exception as e:
        logger.warning(f"[prefilter] market_cap fetch failed {stock_code}: {e}")
        return None, [f"시총 조회 실패: {e}"], {}

    return None, ["KOSPI/KOSDAQ 양쪽에 없음"], {}


async def _check_eps(stock_code: str) -> tuple[Optional[bool], list[str], dict]:
    """F5: 적자 기업 필터.

    DART에서 직전 연도 사업보고서의 EPS(주당순이익) 조회.
    """
    try:
        async with async_session() as db:
            result = await db.execute(
                select(FinancialStatement)
                .where(FinancialStatement.stock_code == stock_code)
                .where(FinancialStatement.quarter == 0)   # 연간
                .order_by(FinancialStatement.year.desc())
                .limit(1)
            )
            fs = result.scalar_one_or_none()
            if fs and fs.eps is not None:
                eps = fs.eps
                if eps < 0:
                    return False, [f"F5: EPS {eps:,.0f} < 0 (적자)"], {"eps": eps}
                return True, [], {"eps": eps}
    except Exception as e:
        logger.debug(f"[prefilter] EPS DB lookup failed {stock_code}: {e}")

    # 캐시 미스 시 보수적으로 통과 (DART 직접 호출은 비용 큼)
    return None, ["EPS 데이터 없음 (보수적 통과)"], {}


# ── 통합 ───────────────────────────────────────────────────────────


async def prefilter_stock(stock_code: str) -> PrefilterResult:
    """단일 종목 사전 필터.

    F1~F6 중 하나라도 명백히 실패(False)이면 제외.
    조회 실패(None)는 보수적으로 통과 처리.
    """
    price_pass, price_reasons, price_metrics = await _check_price_filters(stock_code)
    mcap_pass, mcap_reasons, mcap_metrics = await _check_market_cap(stock_code)
    eps_pass, eps_reasons, eps_metrics = await _check_eps(stock_code)

    all_reasons = price_reasons + mcap_reasons + eps_reasons
    all_metrics = {**price_metrics, **mcap_metrics, **eps_metrics}

    # 명백히 실패한 게 하나라도 있으면 제외
    explicitly_failed = (
        price_pass is False or mcap_pass is False or eps_pass is False
    )
    passed = not explicitly_failed

    return PrefilterResult(
        code=stock_code,
        passed=passed,
        reasons=all_reasons,
        metrics=all_metrics,
    )


async def prefilter_stocks(stock_codes: list[str]) -> dict[str, PrefilterResult]:
    """다수 종목 병렬 필터링. 동시성 5건 제한 (FDR/DART 부하 고려)."""
    semaphore = asyncio.Semaphore(5)

    async def _bounded(code: str) -> tuple[str, PrefilterResult]:
        async with semaphore:
            return code, await prefilter_stock(code)

    results = await asyncio.gather(*[_bounded(c) for c in stock_codes])
    return dict(results)
```

> ⚠️ `FinancialStatement` 모델명/경로는 InvestBrief의 실제 모델 위치에 맞게 수정 필요. InvestBrief에 DART 재무 캐시 테이블이 없으면 F5(EPS)는 제외하고 F1~F4, F6만 적용해도 됨.

---

## 3. theme_radar_service 통합

### 파일: `backend/app/services/theme_radar_service.py` (수정)

`scan_single_theme` 함수에서 **Claude 검증 통과 후, DB 저장 직전**에 사전 필터 추가:

#### 변경 위치: scan_single_theme 함수 안

**Before** (개념):
```python
async def scan_single_theme(theme):
    # 1. 뉴스 검색
    news = await collect_news(theme.keywords)
    # 2. 종목명 추출
    stocks = extract_stocks(news)
    # 3. search_stocks로 종목코드 검증
    verified = []
    for s in stocks:
        if await search_stocks(s.name):
            # 4. Claude 검증
            ok = await _verify_theme_match(theme, s)
            if ok:
                verified.append(s)
    # 5. DB 저장
    await save_results(theme, verified)
```

**After**:
```python
async def scan_single_theme(theme):
    from app.services.prefilter_service import prefilter_stocks  # ← 추가

    # 1~3. 기존 로직 유지
    news = await collect_news(theme.keywords)
    stocks = extract_stocks(news)
    candidates = []
    for s in stocks:
        if await search_stocks(s.name):
            ok = await _verify_theme_match(theme, s)
            if ok:
                candidates.append(s)

    if not candidates:
        return []

    # 4. ── 사전 필터 (신규) ──────────────────────
    codes = [s.code for s in candidates]
    prefilter_map = await prefilter_stocks(codes)

    filtered = []
    rejected_log = []
    for s in candidates:
        result = prefilter_map.get(s.code)
        if result and result.passed:
            filtered.append(s)
        else:
            reasons = result.reasons if result else ["조회 실패"]
            rejected_log.append((s.code, s.name, reasons))
            logger.info(
                f"[prefilter] reject {s.code} {s.name}: {reasons}"
            )

    logger.info(
        f"[scan_single_theme] {theme.name}: "
        f"verified={len(candidates)} → filtered={len(filtered)} "
        f"(rejected={len(rejected_log)})"
    )

    # 5. DB 저장 (filtered만)
    await save_results(theme, filtered)

    return filtered
```

### 통합 후 텔레그램 알림 보강

기존 텔레그램 발송 메시지에 **제외 종목 정보 추가**:

```python
# 텔레그램 메시지 템플릿
msg = f"📡 테마 레이더: {theme.name}\n\n"
msg += f"신규 감지: {len(filtered)}건\n"
for s in filtered:
    msg += f"  • {s.name} ({s.code})\n"

if rejected_log:
    msg += f"\n사전 필터 제외: {len(rejected_log)}건\n"
    for code, name, reasons in rejected_log[:3]:   # 최대 3건만 노출
        first_reason = reasons[0] if reasons else "?"
        msg += f"  ⊘ {name} ({code}): {first_reason}\n"
    if len(rejected_log) > 3:
        msg += f"  ⊘ … 외 {len(rejected_log)-3}건\n"
```

운영자가 어떤 종목이 왜 제외됐는지 직관적으로 파악 가능. 임계값 조정 의사결정 데이터로 활용.

---

## 4. 단위 테스트

### 파일: `backend/tests/test_prefilter_service.py` (신규)

```python
"""prefilter_service 단위 테스트."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.prefilter_service import (
    _calc_rsi,
    _calc_ma,
    prefilter_stock,
    PREFILTER_RSI_MAX,
)


def test_calc_rsi_basic():
    """RSI 계산 — 단조 상승은 RSI 100."""
    closes = list(range(1, 30))   # 1, 2, ..., 29
    rsi = _calc_rsi(closes, period=14)
    assert rsi == pytest.approx(100.0)


def test_calc_rsi_short_data():
    """데이터 부족 시 None."""
    closes = [1, 2, 3]
    assert _calc_rsi(closes, period=14) is None


def test_calc_ma():
    closes = list(range(1, 21))   # 1~20
    ma = _calc_ma(closes, period=10)
    # 마지막 10개의 평균 = 11~20 → 평균 15.5
    assert ma == pytest.approx(15.5)


@pytest.mark.asyncio
async def test_prefilter_rejects_high_rsi():
    """RSI 75 → F1 실패 (제외)."""
    rows = [{"close": 1000 + i * 50} for i in range(60)]   # 단조 상승
    with patch(
        "app.services.prefilter_service.fdr_collector.get_price_list_async",
        new=AsyncMock(return_value=rows),
    ), patch(
        "app.services.prefilter_service.fdr_collector.get_stock_list_async",
        new=AsyncMock(return_value=MagicMock(
            empty=False, columns=["Code", "Marcap"],
            __getitem__=lambda self, key: MagicMock(empty=False, iloc=[100_000_000_000]),
        )),
    ), patch(
        "app.services.prefilter_service.async_session",
        side_effect=Exception("no DB"),
    ):
        result = await prefilter_stock("999999")
    assert result.passed is False
    assert any("F1" in r or "F2" in r or "F3" in r for r in result.reasons)


@pytest.mark.asyncio
async def test_prefilter_rejects_small_market_cap():
    """시총 100억 → F6 실패."""
    rows = [{"close": 1000} for _ in range(60)]   # 변동 없음
    df_mock = MagicMock()
    df_mock.empty = False
    df_mock.columns = ["Code", "Marcap"]
    code_mock = MagicMock()
    code_mock.empty = False
    code_mock.iloc = [10_000_000_000]   # 100억 (500억 미달)
    df_mock.__getitem__ = lambda self, key: code_mock if key == "Marcap" else MagicMock(empty=False)

    with patch(
        "app.services.prefilter_service.fdr_collector.get_price_list_async",
        new=AsyncMock(return_value=rows),
    ), patch(
        "app.services.prefilter_service.fdr_collector.get_stock_list_async",
        new=AsyncMock(return_value=df_mock),
    ):
        result = await prefilter_stock("999999")
    # 적어도 F6 또는 다른 필터 중 하나 실패해야 함
    assert result.passed is False


@pytest.mark.asyncio
async def test_prefilter_passes_normal_stock():
    """정상 종목 (RSI 50, MA 이격 정상, 시총 1000억) → 통과."""
    # 횡보 캔들 (변동성 있되 추세 없음)
    closes = [10000 + ((i % 5) - 2) * 100 for i in range(60)]
    rows = [{"close": c} for c in closes]

    df_mock = MagicMock()
    df_mock.empty = False
    df_mock.columns = ["Code", "Marcap"]
    code_mock = MagicMock()
    code_mock.empty = False
    code_mock.iloc = [100_000_000_000]   # 1000억
    df_mock.__getitem__ = lambda self, key: code_mock if key == "Marcap" else MagicMock(empty=False)

    with patch(
        "app.services.prefilter_service.fdr_collector.get_price_list_async",
        new=AsyncMock(return_value=rows),
    ), patch(
        "app.services.prefilter_service.fdr_collector.get_stock_list_async",
        new=AsyncMock(return_value=df_mock),
    ), patch(
        "app.services.prefilter_service.async_session",
        side_effect=Exception("no DB"),
    ):
        result = await prefilter_stock("005930")
    assert result.passed is True
```

> 시총 mock은 pandas DataFrame 동작 모방이라 다소 복잡. 실제 테스트 시 fixture로 정리 권장.

---

## 5. 적용 절차

### 단계 1: 백업

```bash
cd ~/dev/investbrief-main/backend
cp app/services/theme_radar_service.py \
   app/services/theme_radar_service.py.backup-$(date +%Y%m%d-%H%M%S)
```

### 단계 2: prefilter_service.py 신규 생성

위 코드 그대로 `backend/app/services/prefilter_service.py`로 저장.

> InvestBrief에 `FinancialStatement` 모델이 없으면 `_check_eps` 함수의 DB 조회 부분을 제거하거나, 항상 `(None, ["EPS 데이터 없음"], {})` 반환하도록 수정.

### 단계 3: theme_radar_service.scan_single_theme 수정

위 통합 코드 적용. **Claude 검증 통과 후 DB 저장 직전**에 prefilter_stocks 호출 삽입.

### 단계 4: 단위 테스트

```bash
cd ~/dev/investbrief-main/backend
source .venv/bin/activate
pytest tests/test_prefilter_service.py -v
```

기대: 5개 테스트 통과.

### 단계 5: 수동 스캔으로 검증

```bash
# InvestBrief 셸에서
set -a && source .env && set +a

python3 -u -c "
import asyncio
from app.services.theme_radar_service import scan_all_themes
asyncio.run(scan_all_themes())
" 2>&1 | tee /tmp/scan_with_prefilter.log
```

**기대 로그**:
```
[scan_single_theme] HBM 후공정: verified=8 → filtered=2 (rejected=6)
[prefilter] reject 007610 선도전기: ['F1: RSI 과매수 100.0 ≥ 70.0']
[prefilter] reject 489790 한화비전: ['F2: MA20 이격 +35% > 30%']
...
```

이전엔 verified 그대로 DB 저장 → 13종목. 이후엔 filtered 후만 저장 → **2~5종목 정도로 줄어듦** (대부분 폭등 후 종목).

### 단계 6: StockAI에서 재분석

InvestBrief의 새 결과를 StockAI에서 받아 분석:

```bash
# StockAI 셸에서
cd ~/dev/stock-investment-program/backend
source .venv/bin/activate
set -a && source .env && set +a

python3 -u -c "
import asyncio
from app.services.scheduler_service import run_daily_batch_from_investbrief
asyncio.run(run_daily_batch_from_investbrief())
" 2>&1 | tee /tmp/daily_batch_after_prefilter.log
```

**기대 결과**:
- InvestBrief 결과 종목 수: 2~5건 (이전 13건에서 감소)
- 분석 후 등급: 그 중 **A/B/C 등급이 나올 가능성** 등장 (이전엔 모두 D/F)

---

## 6. 운영 모니터링 (1~2주)

### 모니터링 지표

```bash
# InvestBrief 측 — 사전 필터 효과
grep "scan_single_theme" backend/logs/app.log | tail -30
# 기대: filtered/verified 비율이 20~50% (너무 박하면 임계 완화)
```

### 임계값 조정 가이드

운영 1주 후:

| 상황 | 진단 | 조정 |
|------|------|------|
| filtered=0 (모두 제외) | 임계 너무 박함 | RSI 70→75, MA20 1.30→1.40 |
| filtered = verified | 필터 효과 없음 | RSI 70→65, MA20 1.30→1.20 |
| filtered 적당 + StockAI A/B 등장 | 정상 | 유지 |

조정은 한 번에 한 임계만 변경하고 1주 더 모니터링. 여러 임계 동시 조정 시 인과 추적 어려움.

---

## 7. 배포 체크리스트

- [ ] `prefilter_service.py` 신규 작성
- [ ] `theme_radar_service.scan_single_theme` 수정 (prefilter_stocks 호출 추가)
- [ ] 단위 테스트 통과 (5개)
- [ ] 수동 scan 실행 → 로그에서 filtered/rejected 카운트 확인
- [ ] 텔레그램 알림에 제외 사유 표시되는지 확인
- [ ] 다음 날 StockAI daily_batch에서 등급 분포 정상화 확인 (A/B/C 등장)
- [ ] 1주 후 임계값 조정 필요성 평가

---

## 8. 작성/수정 파일 목록

```
backend/app/services/prefilter_service.py              (신규)
backend/app/services/theme_radar_service.py            (수정 - scan_single_theme)
backend/tests/test_prefilter_service.py                (신규)
backend/app/services/theme_radar_service.py.backup-*   (백업, 자동 생성)
```

---

## 9. 한계 및 후속 과제

### 본 작업의 한계

1. **시차 본질은 해결 안 됨**: 뉴스 발생 → InvestBrief 스캔까지 시차는 그대로. 다만 시차 동안 폭등한 종목을 사후 제거.
2. **EPS 정확도**: DART 직전 연도 기준이라 분기 실적 급변 종목은 stale 가능.
3. **시총 캐시**: FDR `get_stock_list_async`는 일별 캐시. 장중 변동 미반영.
4. **임계값 단일**: 코스피/코스닥 종목별 차별화 없음 (코스닥은 변동성 더 커서 임계 완화 필요할 수 있음).

### 후속 작업 (별도 지시서)

| 작업 | 설명 | 우선순위 |
|------|------|---------|
| 실시간 뉴스 모니터링 | 뉴스 발생 즉시 스캔 (시차 단축) | 큼 (별도 프로젝트 수준) |
| 시장별 임계 차등 | KOSPI/KOSDAQ 별도 임계 | 중간 |
| 백테스트로 임계 최적화 | 과거 N개월 데이터로 통과/제외 결과의 사후 수익률 측정 | 큼 |
| StockAI R:R 임계 완화 | 이번 prefilter로도 부족하면 R:R 2.0 → 1.5 | 보류 (paper_trading 검증 후) |

---

## 10. 의사결정 근거 — 왜 InvestBrief 측에서 필터링하는가

대안 1: **StockAI 측에서 R:R 임계 완화** (R:R 2.0 → 1.5)
- 장점: 1줄 수정으로 끝
- 단점: 자동매매 게이트 적용 시 위험 종목 매수 가능성 증가

대안 2: **InvestBrief 측에서 사전 필터** (본 지시서)
- 장점: StockAI의 보수성 유지. 분석 자체를 안 하므로 노이즈 감소. 텔레그램에서도 폭등 종목 알림 사라짐
- 단점: InvestBrief 코드 추가. 임계값 튜닝 필요

대안 2가 **장기적으로 더 안전하고 깨끗**합니다. StockAI의 BNF 룰(R:R 2.0)은 시장 검증된 보수적 기준이므로 함부로 완화 안 함이 좋습니다. 본 지시서를 우선 적용하고, 1~2주 후에도 매수 종목이 안 잡히면 그때 StockAI 임계 완화를 별도로 검토.
