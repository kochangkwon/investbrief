# InvestBrief — 미국 시장 동향 통합 (모닝브리프 강화) v1.1

**작성일**: 2026-05-06  
**버전**: v1.1 (v1 + 관계 설명 필드 추가)  
**적용대상**: InvestBrief (FastAPI + SQLite `investbrief.db`)  
**예상 작업시간**: 6~8시간 (하루)  
**선행 의존성**: 없음 (독립 적용 가능)

## v1.1 주요 변경점

v1 대비 추가된 사항:
- **BIG_NAMES 매핑에 `relation` 필드 추가** — 미국 빅네임과 한국 종목의 연관 관계를 명시 (왜 동조하는지)
- **ETF_MAPPING에 `note` 필드 추가** — 카테고리 부연 설명
- **MACRO_INDICATORS의 implication 구체화** — 한국 시장에 미치는 구체적 영향 명시
- **formatter에서 relation 출력 로직 추가** — 메시지 자체가 학습 자료가 되도록

**v1.1을 사용하는 이유**: Ko~님이 매번 "TSLA가 왜 LG에너지솔루션과 연관되지?" 같은 매핑 근거를 머릿속으로 검증하지 않고도, 메시지만 보고 자연스럽게 관계를 학습할 수 있게 하기 위함.

---

## 목표

모닝브리프에 미국 시장 동향(섹터 ETF + 빅네임 종목 + 매크로 지표)을 통합하여, 한국 시장 09:00 갭/방향성을 더 정확히 예측할 수 있는 정보를 제공한다.

- **대상 시점**: 매일 07:40 KST 모닝브리프 발송 시
- **데이터 소스**: yfinance (무료, 추가 비용 없음)
- **통합 위치**: 기존 모닝브리프의 "해외지수" 섹션 다음

---

## 배경 / 현재 문제

**현재 모닝브리프 한계:**
1. 미국 지수(S&P500, 나스닥) 등락률만 표시 — 섹터 디커플링 정보 없음
2. NVDA가 -10% 급락해도 나스닥 지수가 평탄하면 포착 불가
3. TSLA 단독 이벤트(LG에너지솔루션 직접 영향)가 LIT ETF에 묻힘
4. 매크로 지표(DXY, VIX, US10Y) 부재로 외인 자금 흐름 예측 불가

**해결 방향:**
- ETF: 섹터 전체 분위기 (5개)
- 빅네임: 한국 직격탄 종목 (7개)
- 매크로: 자금 흐름/위험도 (4개)

이 3축을 모두 7:40 시점에 yfinance로 한 번에 받아 통합 표시한다.

---

## 시간 변경: 7:00 → 7:40

### 변경 이유

1. **운영 편의**: 서버 가동 시점 고려
2. **데이터 신선도**: 7:40 시점에는 미국 시간외 거래 데이터 일부 반영됨
3. **버퍼 확보**: 09:00 정규장까지 1시간 20분 → 매수 준비 충분

### 적용 위치

기존 스케줄러에서 모닝브리프 cron 표현 변경:

```python
# 기존
"0 7 * * *"  # 매일 07:00

# 변경
"40 7 * * *"  # 매일 07:40
```

---

## 신규 파일 구조

```
investbrief/
├── services/
│   └── us_market/                 # 신규 패키지
│       ├── __init__.py
│       ├── mappings.py            # ETF/빅네임/매크로 매핑 테이블
│       ├── fetcher.py             # yfinance 데이터 수집
│       ├── formatter.py           # 텔레그램 출력 포맷
│       └── service.py             # 통합 인터페이스 (외부 호출용)
├── migrations/
│   └── 00X_us_market_cache.sql    # SQLite 캐시 테이블
└── tests/
    └── test_us_market.py          # 단위 테스트
```

기존 파일에서는 `services/morning_brief_service.py` (또는 동등 파일) 1곳만 수정한다.

---

## Step 1 — 매핑 테이블 정의

### 파일: `services/us_market/mappings.py` (신규)

```python
"""
미국 시장 데이터 → 한국 종목/테마 매핑 정의

3가지 카테고리:
- ETF_MAPPING: 섹터 평균 (5개)
- BIG_NAMES: 한국 직격 영향 빅네임 (7개)
- MACRO_INDICATORS: 매크로 지표 (4개)

운영하면서 학습된 결과로 매핑은 주기적으로 다듬을 것.
"""

# ============================================================
# 1. 섹터 ETF 매핑
# ============================================================
ETF_MAPPING = {
    "SOXX": {
        "name": "필라델피아 반도체",
        "category": "반도체",
        "kr_stocks": ["삼성전자", "SK하이닉스", "한미반도체", "HPSP", "이오테크닉스"],
        "kr_themes": ["AI 반도체", "HBM 후공정"],
        "note": "미국 반도체 30개 종목 평균 — 국내 반도체 섹터 전반과 동조",
    },
    "XLK": {
        "name": "기술주",
        "category": "빅테크",
        "kr_stocks": ["네이버", "카카오"],
        "kr_themes": ["인터넷 플랫폼"],
        "note": "AAPL/MSFT 비중 높음 — 직접 영향 약함, 시장 분위기 시그널",
    },
    "XBI": {
        "name": "바이오 (소형주 중심)",
        "category": "바이오",
        "kr_stocks": ["셀트리온", "알테오젠", "한미약품", "유한양행"],
        "kr_themes": ["K-바이오"],
        "note": "임상/FDA 이벤트 동조 — 국내 바이오 위험선호 시그널",
    },
    "LIT": {
        "name": "리튬/배터리",
        "category": "2차전지",
        "kr_stocks": ["LG에너지솔루션", "삼성SDI", "에코프로비엠"],
        "kr_themes": ["2차전지"],
        "note": "전기차 수요 + 리튬 가격 종합 → 2차전지 셀/소재 동조",
    },
    "XLE": {
        "name": "에너지/정유",
        "category": "정유/에너지",
        "kr_stocks": ["SK이노베이션", "S-Oil", "GS"],
        "kr_themes": [],
        "note": "WTI 유가와 함께 봐야 정확 — 단독으로는 약한 시그널",
    },
}

# ============================================================
# 2. 빅네임 매핑 (한국 직격 영향)
# ============================================================
BIG_NAMES = {
    "NVDA": {
        "name": "엔비디아",
        "kr_stocks": ["한미반도체", "이수페타시스", "SK하이닉스"],
        "relation": "HBM 후공정 장비 / AI 가속기용 PCB / HBM 메모리 직접 공급",
        "kr_themes": ["AI 반도체", "HBM 후공정"],
        "alert_threshold": 5.0,  # ±5% 이상 시 ⚠️ 강조
    },
    "TSM": {
        "name": "TSMC",
        "kr_stocks": ["삼성전자", "동진쎄미켐", "솔브레인"],
        "relation": "삼성 파운드리 직접 경쟁사 / 반도체 공정소재 공급",
        "kr_themes": ["반도체", "파운드리"],
        "alert_threshold": 5.0,
    },
    "TSLA": {
        "name": "테슬라",
        "kr_stocks": ["LG에너지솔루션", "삼성SDI", "에코프로비엠"],
        "relation": "테슬라 배터리 셀 공급사 / 양극재 공급사",
        "kr_themes": ["2차전지", "전기차"],
        "alert_threshold": 5.0,
    },
    "AAPL": {
        "name": "애플",
        "kr_stocks": ["LG이노텍", "삼성전기"],
        "relation": "아이폰 카메라 모듈 / MLCC·기판 직접 공급",
        "kr_themes": ["애플 부품"],
        "alert_threshold": 4.0,
    },
    "META": {
        "name": "메타",
        "kr_stocks": ["네이버", "카카오"],
        "relation": "광고/플랫폼 동조 흐름 (직접 거래 X, 시장 분위기 동조)",
        "kr_themes": ["인터넷 플랫폼", "AI 광고"],
        "alert_threshold": 5.0,
    },
    "AMD": {
        "name": "AMD",
        "kr_stocks": ["SK하이닉스", "한미반도체"],
        "relation": "MI300 시리즈 HBM 메모리 채택 / 후공정 장비 동조",
        "kr_themes": ["HBM 후공정"],
        "alert_threshold": 5.0,
    },
    "MU": {
        "name": "마이크론",
        "kr_stocks": ["삼성전자", "SK하이닉스"],
        "relation": "메모리 직접 경쟁사 — 가격/수요 시그널 동조 (실적 가이던스 영향 큼)",
        "kr_themes": ["메모리 반도체"],
        "alert_threshold": 5.0,
    },
}

# ============================================================
# 3. 매크로 지표
# ============================================================
MACRO_INDICATORS = {
    "DX-Y.NYB": {
        "name": "달러 인덱스 (DXY)",
        "category": "환율",
        "implication_up": "달러 강세 → 외인 코스피 매도 압력, 환율 1400원대 진입 시 수출주 부담",
        "implication_down": "달러 약세 → 외인 매수 우호, 신흥국 자금 유입",
        "alert_threshold": 0.5,  # 일일 ±0.5% 이상 변동 시 강조
        "format": "{value:.2f}",
    },
    "^TNX": {
        "name": "미국 10년물 금리",
        "category": "금리",
        "implication_up": "성장주(반도체/바이오/플랫폼) 부담 — 4.5% 이상 시 약세 가속",
        "implication_down": "성장주 호재 — 4.0% 이하 진입 시 반등 모멘텀",
        "alert_threshold": 0.05,  # 5bp 이상 변동
        "format": "{value:.2f}%",
        "is_yield": True,  # 절대값 표시
    },
    "^VIX": {
        "name": "VIX 변동성 지수",
        "category": "위험도",
        "implication_up": "위험 회피 강화 → 외인 매도 증가, 성장주 약세, 안전자산 선호",
        "implication_down": "위험 자산 선호 → 외인 매수 회복, 시클리컬·반도체 강세",
        "alert_threshold": 2.0,  # 2 이상 변동
        "format": "{value:.2f}",
        "is_yield": True,  # 절대값 표시
        "warning_levels": {
            20: "주의 구간 진입",
            25: "패닉 임계 — 매수 자제 권고",
        },
    },
    "CL=F": {
        "name": "WTI 유가",
        "category": "원자재",
        "implication_up": "정유주(SK이노/S-Oil/GS) 호재, 인플레 부담 → 금리 상승 압력",
        "implication_down": "정유주 부담, 인플레 완화 → 성장주 우호적",
        "alert_threshold": 2.0,
        "format": "${value:.2f}",
        "kr_related": ["SK이노베이션", "S-Oil", "GS"],
    },
}

# ============================================================
# 4. S&P500 선물 (한국 갭 직접 예측)
# ============================================================
SP500_FUTURES = {
    "ES=F": {
        "name": "S&P500 선물",
        "category": "선물",
        "implication": "한국 09:00 갭 방향성 직접 시그널",
    },
}
```

---

## Step 2 — 데이터 수집 모듈

### 파일: `services/us_market/fetcher.py` (신규)

```python
"""
yfinance를 사용한 미국 시장 데이터 수집.

핵심 설계 원칙:
- fail-soft: 한 종목/지표 실패해도 나머지는 진행
- 시간외 거래 포함 (prepost=True)
- 휴장일/주말 자동 처리 (period="5d"로 충분한 윈도우 확보)
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime
import yfinance as yf
import pandas as pd

from .mappings import ETF_MAPPING, BIG_NAMES, MACRO_INDICATORS, SP500_FUTURES

logger = logging.getLogger(__name__)


def _calc_change_pct(close: pd.Series) -> Optional[float]:
    """전일 종가 대비 변화율 계산. 데이터 부족 시 None 반환."""
    if close is None or len(close.dropna()) < 2:
        return None
    valid = close.dropna()
    return float((valid.iloc[-1] - valid.iloc[-2]) / valid.iloc[-2] * 100)


def _fetch_single(ticker: str, prepost: bool = False) -> Optional[Dict]:
    """단일 ticker 정규장 + 시간외 데이터 수집."""
    try:
        t = yf.Ticker(ticker)
        # 정규장 종가 (5일치 → 휴장 안전)
        hist = t.history(period="5d", interval="1d", prepost=False)
        if hist.empty:
            logger.warning(f"[us_market] {ticker} no regular history")
            return None
        
        regular_close = float(hist["Close"].iloc[-1])
        regular_prev = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else regular_close
        regular_change_pct = (regular_close - regular_prev) / regular_prev * 100
        
        # 시간외/프리마켓 (선택적)
        prepost_change_pct = None
        prepost_price = None
        if prepost:
            try:
                fast = t.fast_info
                last_price = fast.get("last_price")
                if last_price and last_price != regular_close:
                    prepost_price = float(last_price)
                    prepost_change_pct = (prepost_price - regular_close) / regular_close * 100
            except Exception as e:
                logger.debug(f"[us_market] {ticker} prepost fetch skip: {e}")
        
        return {
            "ticker": ticker,
            "regular_close": regular_close,
            "regular_change_pct": round(regular_change_pct, 2),
            "prepost_price": prepost_price,
            "prepost_change_pct": round(prepost_change_pct, 2) if prepost_change_pct is not None else None,
            "fetched_at": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"[us_market] {ticker} fetch failed: {e}")
        return None


def fetch_etf_sectors() -> List[Dict]:
    """ETF 섹터 데이터 수집."""
    results = []
    for ticker in ETF_MAPPING.keys():
        data = _fetch_single(ticker, prepost=False)
        if data is None:
            continue
        mapping = ETF_MAPPING[ticker]
        results.append({
            **data,
            "name": mapping["name"],
            "category": mapping["category"],
            "kr_stocks": mapping["kr_stocks"],
            "kr_themes": mapping["kr_themes"],
            "note": mapping.get("note", ""),  # 신규 (v1.1)
            "type": "etf",
        })
    # 변동 큰 순 정렬
    results.sort(key=lambda x: abs(x["regular_change_pct"]), reverse=True)
    return results


def fetch_big_names() -> List[Dict]:
    """빅네임 종목 데이터 수집 (시간외 포함)."""
    results = []
    for ticker in BIG_NAMES.keys():
        data = _fetch_single(ticker, prepost=True)
        if data is None:
            continue
        mapping = BIG_NAMES[ticker]
        # 강조 여부 결정
        regular_abs = abs(data["regular_change_pct"])
        prepost_abs = abs(data["prepost_change_pct"] or 0)
        is_alert = regular_abs >= mapping["alert_threshold"] or prepost_abs >= mapping["alert_threshold"]
        
        results.append({
            **data,
            "name": mapping["name"],
            "kr_stocks": mapping["kr_stocks"],
            "relation": mapping.get("relation", ""),  # 신규 (v1.1)
            "kr_themes": mapping["kr_themes"],
            "alert_threshold": mapping["alert_threshold"],
            "is_alert": is_alert,
            "type": "big_name",
        })
    results.sort(key=lambda x: abs(x["regular_change_pct"]), reverse=True)
    return results


def fetch_macro_indicators() -> List[Dict]:
    """매크로 지표 수집."""
    results = []
    for ticker, mapping in MACRO_INDICATORS.items():
        data = _fetch_single(ticker, prepost=False)
        if data is None:
            continue
        results.append({
            **data,
            "name": mapping["name"],
            "category": mapping["category"],
            "implication_up": mapping["implication_up"],
            "implication_down": mapping["implication_down"],
            "alert_threshold": mapping["alert_threshold"],
            "format": mapping["format"],
            "is_yield": mapping.get("is_yield", False),
            "warning_levels": mapping.get("warning_levels"),
            "kr_related": mapping.get("kr_related", []),
            "type": "macro",
        })
    return results


def fetch_sp500_futures() -> Optional[Dict]:
    """S&P500 선물 (한국 갭 예측 시그널)."""
    ticker = "ES=F"
    data = _fetch_single(ticker, prepost=True)
    if data is None:
        return None
    mapping = SP500_FUTURES[ticker]
    return {
        **data,
        "name": mapping["name"],
        "category": mapping["category"],
        "implication": mapping["implication"],
        "type": "futures",
    }


def fetch_all() -> Dict:
    """모든 데이터 한 번에 수집 (모닝브리프에서 호출)."""
    return {
        "etf": fetch_etf_sectors(),
        "big_names": fetch_big_names(),
        "macro": fetch_macro_indicators(),
        "sp500_futures": fetch_sp500_futures(),
        "fetched_at": datetime.now().isoformat(),
    }
```

---

## Step 3 — 텔레그램 출력 포맷터

### 파일: `services/us_market/formatter.py` (신규)

```python
"""
모닝브리프 텔레그램 출력 포맷.

원칙:
- 변동 작은 항목(절대값 < threshold)은 표시 생략 또는 간소화
- 빅네임은 변동 큰 순으로 정렬, ⚠️ 강조 적용
- VIX 같은 절대값 지표는 현재값 + 변동 함께 표시
"""

from typing import Dict, List, Optional


# 변동 표시 임계값 (작은 변동은 생략)
ETF_DISPLAY_THRESHOLD = 0.3      # ETF는 ±0.3% 이상만 표시
MACRO_NOISE_THRESHOLD = 0.1      # 매크로는 ±0.1% 이상만 표시


def _emoji_for_change(change_pct: Optional[float], threshold: float = 0.5) -> str:
    """변동률에 따른 이모지."""
    if change_pct is None:
        return "⚪"
    if change_pct >= threshold:
        return "🟢"
    if change_pct <= -threshold:
        return "🔴"
    return "⚪"


def _format_pct(change_pct: Optional[float]) -> str:
    """+5.23% 형태."""
    if change_pct is None:
        return "N/A"
    sign = "+" if change_pct >= 0 else ""
    return f"{sign}{change_pct:.2f}%"


def format_big_names_section(big_names: List[Dict]) -> str:
    """빅네임 섹션."""
    if not big_names:
        return ""
    lines = ["📊 *빅네임 (변동 큰 순)*"]
    
    for item in big_names:
        change = item["regular_change_pct"]
        prepost = item.get("prepost_change_pct")
        emoji = _emoji_for_change(change, threshold=1.0)
        change_str = _format_pct(change)
        
        # 시간외 정보 추가
        prepost_str = ""
        if prepost is not None and abs(prepost) >= 0.5:
            prepost_str = f" (시간외 {_format_pct(prepost)})"
        
        # 알림 강조
        alert_mark = " ⚠️" if item.get("is_alert") else ""
        
        lines.append(f"{emoji} {item['ticker']} {change_str}{prepost_str}{alert_mark}")
        
        # 변동이 클 때만 한국 종목 + 관계 표시
        if abs(change) >= 2.0 or (prepost is not None and abs(prepost) >= 2.0):
            stocks = ", ".join(item["kr_stocks"][:3])
            direction = "주목" if change >= 0 else "갭하락 주의"
            lines.append(f"   국내 {direction}: {stocks}")
            # v1.1: 관계 설명 추가 — 메시지 자체가 학습 자료
            relation = item.get("relation")
            if relation:
                lines.append(f"   ({relation})")
    
    return "\n".join(lines)


def format_etf_section(etfs: List[Dict]) -> str:
    """ETF 섹션."""
    if not etfs:
        return ""
    
    # 임계값 이하 필터링
    filtered = [e for e in etfs if abs(e["regular_change_pct"]) >= ETF_DISPLAY_THRESHOLD]
    if not filtered:
        return "📈 *섹터 ETF*: 큰 변동 없음"
    
    lines = ["📈 *섹터 ETF*"]
    for item in filtered:
        change = item["regular_change_pct"]
        emoji = _emoji_for_change(change, threshold=0.5)
        change_str = _format_pct(change)
        
        if change >= 1.0:
            sentiment = f"{item['category']} 강세"
        elif change <= -1.0:
            sentiment = f"{item['category']} 약세"
        else:
            sentiment = f"{item['category']} 중립"
        
        lines.append(f"{emoji} {item['ticker']} {change_str} → {sentiment}")
    
    return "\n".join(lines)


def format_macro_section(macros: List[Dict]) -> str:
    """매크로 섹션."""
    if not macros:
        return ""
    lines = ["🌡️ *매크로*"]
    
    for item in macros:
        change = item["regular_change_pct"]
        if change is None:
            continue
        
        # 표시 포맷 적용 (값 + 변동)
        value = item["regular_close"]
        value_str = item["format"].format(value=value)
        change_str = _format_pct(change)
        
        # 카테고리별 이모지
        cat_emoji = {
            "환율": "💵",
            "금리": "📈",
            "위험도": "😨" if value > 20 else "😌",
            "원자재": "🛢️",
        }.get(item["category"], "📊")
        
        line = f"{cat_emoji} {item['name']}: {value_str} ({change_str})"
        
        # VIX 같은 경고 레벨 처리
        if item.get("warning_levels"):
            for threshold, msg in sorted(item["warning_levels"].items(), reverse=True):
                if value >= threshold:
                    line += f" — {msg}"
                    break
        
        lines.append(line)
    
    return "\n".join(lines)


def format_sp500_futures_section(fut: Optional[Dict]) -> str:
    """S&P500 선물 (한국 갭 예측)."""
    if not fut:
        return ""
    
    change = fut.get("prepost_change_pct") or fut.get("regular_change_pct")
    if change is None:
        return ""
    
    change_str = _format_pct(change)
    
    if change >= 0.3:
        signal = "한국 갭상승 가능성"
    elif change <= -0.3:
        signal = "한국 갭하락 가능성"
    else:
        signal = "한국 보합 출발 예상"
    
    return f"📊 *S&P500 선물*: {change_str} → {signal}"


def format_full_section(data: Dict) -> str:
    """전체 미국 시장 섹션 통합 포맷."""
    sections = []
    
    # 헤더
    sections.append("🌎 *어제 미국 시장* (07:40 KST 기준)")
    sections.append("")
    
    # 빅네임 (가장 중요 → 맨 위)
    big_names_text = format_big_names_section(data.get("big_names", []))
    if big_names_text:
        sections.append(big_names_text)
        sections.append("")
    
    # ETF
    etf_text = format_etf_section(data.get("etf", []))
    if etf_text:
        sections.append(etf_text)
        sections.append("")
    
    # 매크로
    macro_text = format_macro_section(data.get("macro", []))
    if macro_text:
        sections.append(macro_text)
        sections.append("")
    
    # S&P500 선물 (마지막 — 한국 갭 직격 시그널)
    fut_text = format_sp500_futures_section(data.get("sp500_futures"))
    if fut_text:
        sections.append(fut_text)
    
    return "\n".join(sections).strip()
```

---

## Step 4 — 통합 서비스 인터페이스

### 파일: `services/us_market/service.py` (신규)

```python
"""
모닝브리프에서 호출하는 단일 진입점.

외부에서는 get_us_market_section()만 호출하면 됨.
캐싱은 여기서 처리.
"""

import logging
from typing import Optional
from datetime import datetime, timedelta

from .fetcher import fetch_all
from .formatter import format_full_section

logger = logging.getLogger(__name__)


# 메모리 캐시 (간단 버전 — 1회 fetch 후 1시간 유효)
_cache = {
    "data": None,
    "expires_at": None,
}
_CACHE_TTL_MINUTES = 60


def _is_cache_valid() -> bool:
    if _cache["data"] is None or _cache["expires_at"] is None:
        return False
    return datetime.now() < _cache["expires_at"]


def get_us_market_data(use_cache: bool = True) -> dict:
    """미국 시장 raw 데이터 (테스트/디버깅용)."""
    if use_cache and _is_cache_valid():
        return _cache["data"]
    
    try:
        data = fetch_all()
        _cache["data"] = data
        _cache["expires_at"] = datetime.now() + timedelta(minutes=_CACHE_TTL_MINUTES)
        return data
    except Exception as e:
        logger.error(f"[us_market] fetch_all failed: {e}", exc_info=True)
        return {"etf": [], "big_names": [], "macro": [], "sp500_futures": None}


def get_us_market_section(use_cache: bool = True) -> str:
    """
    모닝브리프에 삽입할 미국 시장 섹션 텍스트.
    
    Returns:
        포맷된 텔레그램 마크다운 문자열. 실패 시 빈 문자열.
    """
    try:
        data = get_us_market_data(use_cache=use_cache)
        return format_full_section(data)
    except Exception as e:
        logger.error(f"[us_market] section build failed: {e}", exc_info=True)
        return ""  # fail-soft: 빈 문자열 반환 → 모닝브리프 본체는 발송


def clear_cache():
    """수동 캐시 비우기 (테스트용)."""
    _cache["data"] = None
    _cache["expires_at"] = None
```

### 파일: `services/us_market/__init__.py` (신규)

```python
from .service import get_us_market_section, get_us_market_data, clear_cache

__all__ = ["get_us_market_section", "get_us_market_data", "clear_cache"]
```

---

## Step 5 — 모닝브리프 통합

### 파일: `services/morning_brief_service.py` (기존 — **1줄 import + 1개 섹션 추가**)

기존 `generate_morning_brief()` 함수에 다음을 추가한다:

```python
# 파일 상단 import 영역
from services.us_market import get_us_market_section


async def generate_morning_brief():
    # ... 기존 코드 (헤더, 해외지수 섹션 등) ...
    
    # ============================================
    # 신규: 미국 시장 동향 섹션
    # ============================================
    us_market_section = get_us_market_section()  # fail-soft 내장
    
    # 모닝브리프 조립
    sections = [
        header_section,
        overseas_indices_section,
        us_market_section,                    # ← 추가 (해외지수 다음, 국내시장 앞)
        domestic_market_section,
        ai_news_section,
        dart_section,
        watchlist_section,
    ]
    
    # 빈 섹션 제거
    brief = "\n\n".join(filter(None, sections))
    return brief
```

**중요**: 기존 코드 흐름은 절대 변경하지 말 것. import 1줄 + 변수 1개 + sections 리스트에 1줄 추가가 전부.

---

## Step 6 — SQLite 캐시 테이블 (선택, 권장)

메모리 캐시만으로도 충분하지만, 서버 재시작 후에도 캐시 유지하려면 DB 캐시 추가.

### 파일: `migrations/00X_us_market_cache.sql` (신규)

```sql
CREATE TABLE IF NOT EXISTS us_market_daily (
    date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    type TEXT NOT NULL,           -- 'etf' | 'big_name' | 'macro' | 'futures'
    regular_close REAL,
    regular_change_pct REAL,
    prepost_price REAL,
    prepost_change_pct REAL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (date, ticker)
);

CREATE INDEX IF NOT EXISTS idx_us_market_date ON us_market_daily(date);
```

마이그레이션 적용 명령:

```bash
sqlite3 investbrief.db < migrations/00X_us_market_cache.sql
```

DB 캐시 추가는 v2에서 진행해도 무방. v1은 메모리 캐시로 충분.

---

## Step 7 — 스케줄 변경

기존 모닝브리프 스케줄러에서 cron 표현 변경. (정확한 파일 위치는 InvestBrief 코드에서 확인 필요)

```python
# 예시 — APScheduler 사용 시
scheduler.add_job(
    generate_morning_brief,
    trigger="cron",
    hour=7,
    minute=40,    # ← 0 → 40 변경
    id="morning_brief_daily",
    replace_existing=True,
)
```

또는 cron 문자열:

```
# 기존
"0 7 * * *"

# 변경
"40 7 * * *"
```

---

## Step 8 — 단위 테스트

### 파일: `tests/test_us_market.py` (신규)

```python
"""us_market 모듈 단위 테스트."""

import pytest
from services.us_market import get_us_market_section, get_us_market_data, clear_cache
from services.us_market.formatter import (
    format_etf_section,
    format_big_names_section,
    format_macro_section,
)


class TestFetcher:
    """실제 yfinance 호출 — 네트워크 의존."""
    
    def setup_method(self):
        clear_cache()
    
    def test_get_us_market_data_returns_all_keys(self):
        """fetch_all 결과에 4개 키 모두 존재."""
        data = get_us_market_data(use_cache=False)
        assert "etf" in data
        assert "big_names" in data
        assert "macro" in data
        assert "sp500_futures" in data
    
    def test_etf_data_has_required_fields(self):
        data = get_us_market_data(use_cache=False)
        if data["etf"]:
            sample = data["etf"][0]
            assert "ticker" in sample
            assert "regular_close" in sample
            assert "regular_change_pct" in sample
            assert "kr_stocks" in sample


class TestFormatter:
    """포맷터 단위 테스트 — 네트워크 무관."""
    
    def test_etf_section_empty(self):
        assert format_etf_section([]) == ""
    
    def test_etf_section_filters_small_changes(self):
        """작은 변동(±0.3% 미만)은 표시 안 함."""
        small = [{
            "ticker": "SOXX", "regular_change_pct": 0.1,
            "category": "반도체", "name": "필라델피아 반도체",
        }]
        result = format_etf_section(small)
        assert "큰 변동 없음" in result
    
    def test_big_names_section_marks_alert(self):
        """alert_threshold 초과 시 ⚠️ 표시."""
        big = [{
            "ticker": "NVDA", "regular_change_pct": -7.5,
            "prepost_change_pct": None,
            "name": "엔비디아",
            "kr_stocks": ["한미반도체", "이수페타시스"],
            "relation": "HBM 후공정 장비 / AI 가속기용 PCB / HBM 메모리 직접 공급",
            "is_alert": True,
        }]
        result = format_big_names_section(big)
        assert "⚠️" in result
        assert "한미반도체" in result  # 변동 ≥2% → 한국 종목 표시
        assert "HBM 후공정 장비" in result  # v1.1: relation 표시 검증
    
    def test_big_names_section_no_relation_for_small_changes(self):
        """변동 작은 종목은 한국 종목/관계 표시 안 함."""
        small = [{
            "ticker": "AAPL", "regular_change_pct": 0.4,
            "prepost_change_pct": None,
            "name": "애플",
            "kr_stocks": ["LG이노텍"],
            "relation": "아이폰 카메라 모듈",
            "is_alert": False,
        }]
        result = format_big_names_section(small)
        assert "AAPL" in result
        assert "LG이노텍" not in result  # 2% 미만 → 종목 생략
        assert "아이폰" not in result    # 종목 생략 시 relation도 생략
    
    def test_section_integration(self):
        """전체 섹션 빌드 정상 동작."""
        section = get_us_market_section(use_cache=False)
        # 빈 문자열이거나 헤더 포함
        assert section == "" or "🌎" in section


class TestFailSoft:
    def test_section_returns_empty_on_total_failure(self):
        """모든 데이터 수집 실패해도 빈 문자열 반환 (예외 안 던짐)."""
        # fetcher를 mock해서 모두 실패시키는 테스트는 별도 mock 필요
        # 여기서는 API 호출 실패 시 빈 결과 반환만 확인
        clear_cache()
        result = get_us_market_section()
        assert isinstance(result, str)  # 예외 X
```

### 수동 통합 테스트

```bash
cd /path/to/investbrief

# 단독 실행
python3 -c "
from services.us_market import get_us_market_section
print(get_us_market_section())
"

# 단위 테스트
pytest tests/test_us_market.py -v
```

---

## 출력 예시 (실제 텔레그램 모양)

```
🌎 어제 미국 시장 (07:40 KST 기준)

📊 빅네임 (변동 큰 순)
🔴 NVDA -7.20% (시간외 -1.50%) ⚠️
   국내 갭하락 주의: 한미반도체, 이수페타시스, SK하이닉스
   (HBM 후공정 장비 / AI 가속기용 PCB / HBM 메모리 직접 공급)
🟢 TSLA +5.30% ⚠️
   국내 주목: LG에너지솔루션, 삼성SDI, 에코프로비엠
   (테슬라 배터리 셀 공급사 / 양극재 공급사)
🟢 TSM +3.10%
   국내 주목: 삼성전자, 동진쎄미켐, 솔브레인
   (삼성 파운드리 직접 경쟁사 / 반도체 공정소재 공급)
🔴 META -2.80%
   국내 갭하락 주의: 네이버, 카카오
   (광고/플랫폼 동조 흐름 (직접 거래 X, 시장 분위기 동조))
🔴 AMD -2.10%
   국내 갭하락 주의: SK하이닉스, 한미반도체
   (MI300 시리즈 HBM 메모리 채택 / 후공정 장비 동조)
⚪ AAPL +0.40%
⚪ MU -0.30%

📈 섹터 ETF
🔴 SOXX -3.20% → 반도체 약세
🟢 LIT +2.10% → 2차전지 강세
⚪ XLK -0.50% → 빅테크 중립

🌡️ 매크로
💵 달러 인덱스 (DXY): 105.80 (+0.30%)
📈 미국 10년물 금리: 4.52% (+1.13%)
😨 VIX 변동성 지수: 21.50 (+8.59%) — 주의 구간 진입
🛢️ WTI 유가: $73.20 (-1.62%)

📊 S&P500 선물: -0.40% → 한국 갭하락 가능성
```

**v1.1 핵심 개선**: 변동 큰 빅네임마다 "왜 한국 종목과 동조하는지" 1줄 부연 설명이 따라옵니다. Ko~님이 매핑 근거를 머릿속으로 검증하지 않고도 자연스럽게 학습 가능.

---

## 절대 하지 말 것

1. **기존 모닝브리프 핵심 흐름 변경 금지** — 추가만, 수정 X
2. **미국 데이터 실패 시 전체 모닝브리프 차단 금지** — fail-soft 필수
3. **유료 API 도입 금지** — yfinance만 사용 (Bloomberg, Refinitiv 등 X)
4. **텔레그램 발송 로직 수정 금지** — 메시지 빌드 결과만 변경
5. **기존 yfinance 호출 코드와 충돌 회피** — 기존 해외지수 섹션은 그대로 유지
6. **매핑 테이블에 수십 종목 추가 금지** — v1은 빅네임 7개로 시작, 운영하며 학습 후 v2에서 확장
7. **시간외 데이터 미존재를 에러로 처리 금지** — None 반환은 정상 (휴장/거래없음)

---

## 알려진 한계 / 솔직히 짚어둘 것

1. **상관관계는 변동적이다.** 국내 단독 이슈(정책, 외인 매도, 환율 쇼크)가 강할 때 미국 매핑이 어긋날 수 있다. 매핑은 "참고 시그널"일 뿐 매매 결정 근거가 아니다.

2. **삼성전자 ≠ SOXX 추종주.** 삼성전자는 자체 파운드리/AI 칩/HBM 이슈가 더 클 때가 많다. 매핑은 약한 신호로만 활용.

3. **yfinance는 가끔 멈춘다.** Yahoo가 API를 막거나 응답이 느려질 수 있다. fail-soft 설계로 모닝브리프 본체는 보호됨.

4. **시간외 데이터는 누락 가능.** 새벽 시간대(미국 EST 16:00 직후)에는 시간외 거래가 거의 없을 수 있다. None 처리 정상.

5. **매크로 알림 레벨은 운영 데이터로 보정 필요.** VIX 20 진입 알림은 일반론이고, 한국 시장에서 실제 영향은 다를 수 있다. 한 달 운영 후 실효성 평가하여 임계값 조정.

6. **매핑 검증은 운영하면서 다듬는다.** 처음 만든 매핑은 교과서적이라, "SOXX +3% 떴는데 한미반도체 -1%" 같은 디커플링이 종종 나온다. 한 달 데이터 쌓이면 어떤 매핑이 진짜 잘 맞는지 보일 것. **v1.1의 relation 필드도 시간이 지나면서 정확도 점검 필요** — 예: "META → 네이버" 매핑은 직접 거래 관계 없는 시장 분위기 동조라 노이즈가 클 수 있음.

7. **relation 필드는 사실 검증된 정보로 유지.** 운영 학습 결과로 매핑을 추가/제거할 때 relation도 같이 수정하지 않으면 잘못된 정보가 사용자에게 노출됨. 매핑 변경 시 relation 동기화 필수.

---

## 작업 체크리스트

### Phase 1-A: 코드 구현
- [ ] `services/us_market/mappings.py` 작성
- [ ] `services/us_market/fetcher.py` 작성
- [ ] `services/us_market/formatter.py` 작성
- [ ] `services/us_market/service.py` 작성
- [ ] `services/us_market/__init__.py` 작성
- [ ] `tests/test_us_market.py` 작성

### Phase 1-B: 통합
- [ ] `morning_brief_service.py`에 import + 섹션 호출 추가
- [ ] 스케줄 07:00 → 07:40 변경
- [ ] (선택) SQLite 캐시 테이블 마이그레이션

### Phase 1-C: 검증
- [ ] `pytest tests/test_us_market.py -v` 통과
- [ ] 수동 실행으로 텔레그램 출력 확인
- [ ] 다음 날 07:40 자동 발송 정상 동작 확인
- [ ] 1주일 운영 후 매핑 정확도 점검

### Phase 1-D: 후속 (v1 안정 후)
- [ ] 매핑 테이블 학습 결과 반영 (한 달 후)
- [ ] DB 캐시 도입 (메모리 → SQLite)
- [ ] Theme Radar와 연결 (Phase 2)
- [ ] 웹 대시보드 카드 추가 (Phase 3)

---

## 향후 확장 (이번 작업 범위 밖)

| 항목 | 시기 |
|---|---|
| 매핑 테이블 운영 학습 결과 반영 | 한 달 후 |
| Theme Radar 14개 테마와 자동 연결 (us_proxies 필드) | v2 |
| 웹 대시보드에 미국 시장 카드 추가 | v2 |
| 매크로 임계값 알림 (VIX 25+ 시 텔레그램 별도 알림) | v2 |
| ADR 추적 (한국 기업 미국 상장) | 가치 낮음 — 보류 |
| 중국 인터넷 ETF (KWEB) → 한국 대중국 익스포저 매핑 | v3 |

---

## 다른 지시서와의 관계

- **InvestBrief↔StockAI 자동화 지시서 (5/4 작성)**: 본 지시서 적용 후, StockAI batch-analyze에서 미국 시장 컨텍스트도 활용 가능. 단, 본 지시서가 선행되어야 함.
- **DEV Worktree 격리 지시서 (5/5 작성)**: InvestBrief는 격리 대상 외이므로 무관.

---

## 변경 이력

- **v1.1 (2026-05-06)**: BIG_NAMES에 `relation` 필드 추가 (각 빅네임과 한국 종목의 연관 관계 명시). ETF_MAPPING에 `note` 필드 추가. MACRO_INDICATORS의 implication 한국 시장 영향 구체화. formatter에 relation 출력 로직 추가. 메시지 자체가 학습 자료가 되도록 강화.
- **v1 (2026-05-06)**: 최초 작성. ETF 5개 + 빅네임 7개 + 매크로 4개 + S&P500 선물 통합. 7:00 → 7:40 시간 변경 포함.
