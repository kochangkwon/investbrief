# InvestBrief 전문가 업그레이드 — 실전 매매 어시스턴스 (Verified Plus Plus)

> **목적**: 옵션 C+(7개)에 매매 실행 정보(P0-6) + 점수 해석(P0-7) 추가하여 실전 어시스턴스 달성
> **작성일**: 2026-05-13
> **적용 대상**: InvestBrief
> **사전 의존성**: 없음 (단독 적용 가능)
> **StockAI 영향**: **없음**
>
> ---
>
> ## 옵션 C++의 추가 이유
>
> 옵션 C+ (정보 78점, 실전 55-60점)의 결정적 약점:
> - **TOP 10 발굴 후 "어떻게 매수할지" 정보 0** — 진입가/손절가/목표가 없음
> - **점수 의미 해석 불가** — "92점인데 왜?" 답할 수 없음
>
> → 1.5일 추가로 진짜 **실전 어시스턴스 65-70점** 달성.
>
> ## 적용 대상 (총 9개 항목)
>
> | 항목 | 작업량 | 옵션 C+ vs C++ |
> |------|:---:|:---:|
> | **P0-1**: AI 프롬프트 5섹션 재작성 | 1일 | 동일 |
> | **P0-2**: 외인/기관 수급 + TOP 종목 | 1일 | 동일 |
> | **P0-3**: 종목명 본문 추출 | 0.5일 | 동일 |
> | **P0-4**: 펀더멘털 최소 | 1일 | 동일 |
> | **P0-5**: 시장 위험 모드 | 0.5일 | 동일 |
> | **P0-6**: 진입가/손절가/목표가 (ATR 기반) | **1일** | 🆕 |
> | **P0-7**: 점수 해석 1줄 (룰 기반) | **0.5일** | 🆕 |
> | **P1-7**: 종목 4차원 점수 + TOP 10 | 2-3일 | P0-6/P0-7 통합 |
> | **테마 v2.1**: 테마 발굴 프롬프트 | 0.5일 | 동일 |
>
> **총 작업량**: 약 8-9일 (옵션 C+ 대비 +1.5일)
>
> ## 기대 점수 변화
>
> | 영역 | 현재 (v1) | 옵션 C | 옵션 C+ | **옵션 C++** |
> |------|:---:|:---:|:---:|:---:|
> | 정보 시스템 (브리프) | 45 | 75~78 | 78~80 | **78~80** |
> | 종목 발굴 | 40 | 70~73 | 73~76 | **75~78** |
> | 테마 발굴 | 35 | 70~75 | 70~75 | **70~75** |
> | **실전 어시스턴스** | 30 | 55~60 | 55~60 | **65~70** |
>
> ## 의도적 제외 (운영 후 재평가)
>
> | 항목 | 제외 이유 |
> |------|------|
> | P1-4 이벤트 캘린더 | 어닝은 휴리스틱 (정확도 낮음) |
> | P1-5 테마 점수화 | 가중치 추측 |
> | P1-6 키워드 확장 | 효과 작음 |
> | P1-8 FRED 선행지표 | API 키 발급 후 직접 테스트 |
> | P1-9 시장 국면 진단 (full) | **단순화한 P0-5로 대체** |
> | P2-7 펀더멘털 캐시 (full) | **단순화한 P0-4로 대체** |
> | P2-8 라이프사이클 | P1-5 선행 필요 |
> | P2-9 컨텍스트 연결 | 운영 데이터 누적 후 |
> | P2-10 성과 리포트 | v3 측정 데이터 누적 후 |
> | P2-11~15 | 외부 데이터 접근 불안정 |

---

## 📋 목차

- [1. 사전 준비](#1-사전-준비)
- [2. P0-1: AI 프롬프트 5섹션 재작성](#2-p0-1-ai-프롬프트-5섹션-재작성)
- [3. P0-2: 외인/기관 수급 + TOP 종목](#3-p0-2-외인기관-수급--top-종목)
- [4. P0-3: 종목명 본문 추출](#4-p0-3-종목명-본문-추출)
- [5. P0-4: 펀더멘털 최소](#5-p0-4-펀더멘털-최소-신규)
- [6. P0-5: 시장 위험 모드](#6-p0-5-시장-위험-모드-단순-진단-신규)
- [**7. P0-6: 진입가/손절가/목표가 (ATR 기반) 🆕**](#7-p0-6-진입가손절가목표가-신규)
- [**8. P0-7: 점수 해석 1줄 (룰 기반) 🆕**](#8-p0-7-점수-해석-1줄-신규)
- [9. P1-7: 종목 4차원 점수 + TOP 10 알림](#9-p1-7-종목-4차원-점수--top-10-알림)
- [10. 테마 v2.1: 테마 발굴 프롬프트](#10-테마-v21-테마-발굴-프롬프트-강화)
- [11. 통합 검증 체크리스트](#11-통합-검증-체크리스트)
- [12. 적용 순서 & 일정](#12-적용-순서--일정)
- [13. 롤백 가이드](#13-롤백-가이드)

---

## 1. 사전 준비

### 1-1. 환경 확인 및 백업

```bash
cd ~/dev/investbrief  # 본인 경로
git status            # clean 상태 확인

# DB 백업
cp backend/data/investbrief.db backend/data/investbrief.db.backup_$(date +%Y%m%d)

# Git 백업 브랜치
git checkout -b backup/before-verified-upgrade
git push -u origin backup/before-verified-upgrade 2>/dev/null || true
git checkout -

# 새 작업 브랜치
git checkout -b feature/verified-upgrade
```

### 1-2. .env 추가 (1줄만)

```bash
# 기존 .env 끝에 추가 (선택)
AI_BRIEF_SECTIONS_ENABLED=true
```

### 1-3. 의존성 추가

```bash
cd backend
echo "" >> requirements.txt
echo "# === Verified Upgrade ===" >> requirements.txt
echo "pykrx==1.0.45" >> requirements.txt
pip3 install -r requirements.txt

# 검증
python3 -c "from pykrx import stock; print('pykrx OK')"
```

### 1-4. 공통 원칙

1. 모든 신규 호출은 `try-except`로 감싸 실패해도 기존 브리프 정상 발송
2. fail-soft: AI 실패 시 기존 로직으로 폴백
3. KST 통일: `ZoneInfo("Asia/Seoul")`
4. async/await 일관: blocking 호출은 `asyncio.to_thread`로 위임
5. 임계값/가중치는 모듈 상수로 (추후 ENV 이전 가능)

---

## 2. P0-1: AI 프롬프트 5섹션 재작성

### 목적

`ai_summarizer.summarize_news()`의 일반론적 요약을 5섹션 전문가 디리프로 교체:

1. 시장 컨텍스트 (전일 흐름 + 오늘 기대)
2. 카탈리스트 (수주/실적/임상/규제 + 영향 종목)
3. 섹터 로테이션 시그널
4. 이번주 D-N 이벤트
5. 리스크 시그널

### 변경 파일

- **신규**: `backend/app/services/ai_prompts.py`
- **수정**: `backend/app/services/ai_summarizer.py` (함수 추가, 기존 함수 유지)
- **수정**: `backend/app/services/brief_service.py` (호출 변경)

### 신규 파일: `backend/app/services/ai_prompts.py`

```python
"""AI 프롬프트 정의 — 전문가용 브리프 출력 구조 통일."""
from __future__ import annotations

from typing import Any


EXPERT_BRIEF_SYSTEM = """당신은 한국 주식 시장 분석 전문가이며, 매일 아침 기관 투자자에게 모닝브리프를 작성합니다.
독자는 이미 시장의 기본 흐름을 알고 있는 프로페셔널입니다. 일반 뉴스 요약이 아니라,
의사결정에 직접 쓸 수 있는 인사이트만 제공하세요. 어휘는 간결·정확·실무적으로."""


EXPERT_BRIEF_USER_TEMPLATE = """다음은 오늘의 시장 데이터와 뉴스입니다.

━━━━━━━━━━━━━━━━━━━━━━━━━
🌍 글로벌 시장 (전일)
{global_market_text}

📊 국내 시장 (전일)
{domestic_market_text}

💰 수급 (전일 종가 기준)
{flow_text}

📰 주요 뉴스 ({news_count}건)
{news_text}

📋 주요 공시 ({disclosure_count}건)
{disclosure_text}
━━━━━━━━━━━━━━━━━━━━━━━━━

다음 **5개 섹션**으로 정확히 작성하세요. 각 섹션 헤더는 그대로 사용.

## 🎯 1. 시장 컨텍스트
- 전일 시장을 한 줄로 요약 (지수 + 외인 수급 + 주도 섹터)
- 오늘 시장 기대 한 줄
- **반드시** 외인/기관 net flow 수치 언급

## 💥 2. 오늘의 카탈리스트 (3~5개)
각 항목 형식 (단 한 줄):
- **[종목명/섹터]** — 사건/뉴스 (수치 명시) → 예상 영향
예시: "한미반도체 — 2분기 매출 가이던스 +30% 상회 → HBM 후공정 비중 확대 모멘텀 강화"
**규칙:**
- 수주 공시 → 매출 대비 비중 추정
- 임상 → 단계와 발표 일정 명시
- 실적 → 컨센서스 대비 +/-
- 추측 금지, 데이터에 명시된 것만

## 🔄 3. 섹터 로테이션 시그널
- 강한 섹터 (3개 이내) + 약한 섹터 (2개 이내)
- 미국 섹터 ETF 동향과 한국 매칭 (예: SOXX +3% → 반도체 동조 예상)
- 외인/기관 매수 상위 섹터 명시

## 📅 4. 이번주 주요 일정
입력 데이터에 명시된 일정 위주, 최대 5개:
- **MM/DD** — 이벤트명 [영향 섹터/종목]
없으면 "특이 일정 없음"

## ⚠️ 5. 리스크 시그널
다음 항목 중 **현재 발현된 것만** (없으면 "특이 시그널 없음"):
- VIX > 20 또는 5일 변동
- 미국 10년물 4.5% 이상 또는 급변
- 환율 1380원 이상 또는 5일 +1% 이상
- 외인 5일 연속 순매도
- 미국 시장과 한국 디커플링 (전일 나스닥 +1% 인데 코스피 약세 등)

━━━━━━━━━━━━━━━━━━━━━━━━━
**원칙**:
- 추측·일반론 금지. 데이터·뉴스에 근거한 것만.
- 종목명 언급 시 종목코드 함께 (예: "한미반도체(042700)")
- 한 섹션이 비어있어도 헤더는 유지, 본문에 "특이 사항 없음" 표기."""


def build_expert_brief_prompt(
    global_market: dict[str, Any],
    domestic_market: dict[str, Any],
    investor_flow: dict[str, Any],
    news_items: list[dict[str, Any]],
    disclosure_items: list[dict[str, Any]],
) -> tuple[str, str]:
    """(system_prompt, user_prompt) 튜플 반환."""
    global_text = _format_market_for_prompt(global_market) or "데이터 없음"
    domestic_text = _format_market_for_prompt(domestic_market) or "데이터 없음"
    flow_text = _format_flow_for_prompt(investor_flow) or "수급 데이터 없음"
    news_text = _format_news_for_prompt(news_items) or "뉴스 없음"
    disc_text = _format_disclosure_for_prompt(disclosure_items) or "주요 공시 없음"

    user_prompt = EXPERT_BRIEF_USER_TEMPLATE.format(
        global_market_text=global_text,
        domestic_market_text=domestic_text,
        flow_text=flow_text,
        news_count=len(news_items),
        news_text=news_text,
        disclosure_count=len(disclosure_items),
        disclosure_text=disc_text,
    )
    return EXPERT_BRIEF_SYSTEM, user_prompt


def _format_market_for_prompt(data: dict[str, Any]) -> str:
    if not data:
        return ""
    lines = []
    for v in data.values():
        sign = "+" if v.get("change_pct", 0) > 0 else ""
        lines.append(
            f"- {v.get('label', '?')}: {v.get('close', 0):,.2f} ({sign}{v.get('change_pct', 0):.2f}%)"
        )
    return "\n".join(lines)


def _format_flow_for_prompt(flow: dict[str, Any]) -> str:
    if not flow:
        return ""
    parts = []
    foreign = flow.get("foreign_net_billion")
    inst = flow.get("institution_net_billion")
    if foreign is not None:
        sign = "+" if foreign >= 0 else ""
        parts.append(f"외국인 순매수: {sign}{foreign:,.0f}억원")
    if inst is not None:
        sign = "+" if inst >= 0 else ""
        parts.append(f"기관 순매수: {sign}{inst:,.0f}억원")

    buy_sectors = flow.get("top_buy_sectors", [])
    sell_sectors = flow.get("top_sell_sectors", [])
    if buy_sectors:
        parts.append(f"외인 매수 상위 섹터: {', '.join(buy_sectors[:3])}")
    if sell_sectors:
        parts.append(f"외인 매도 상위 섹터: {', '.join(sell_sectors[:3])}")

    return "\n".join(f"- {p}" for p in parts)


def _format_news_for_prompt(news: list[dict[str, Any]]) -> str:
    if not news:
        return ""
    lines = []
    for n in news[:20]:
        title = n.get("title", "")
        desc = n.get("description", "")
        if desc:
            lines.append(f"- {title}\n  ({desc[:150]})")
        else:
            lines.append(f"- {title}")
    return "\n".join(lines)


def _format_disclosure_for_prompt(disc: list[dict[str, Any]]) -> str:
    if not disc:
        return ""
    important = [d for d in disc if d.get("importance") in ("🔴", "🟡", "🟢")]
    if not important:
        return ""
    lines = []
    for d in important[:15]:
        lines.append(
            f"- {d.get('importance', '')} [{d.get('corp_name', '?')}] {d.get('title', '?')}"
        )
    return "\n".join(lines)
```

### 수정: `backend/app/services/ai_summarizer.py`

기존 `summarize_news()` 함수는 **유지**(폴백용), 신규 함수 추가:

```python
"""Claude API 뉴스 요약 + 전문가 브리프"""
from __future__ import annotations

import logging
from typing import Any

import anthropic

from app.config import settings
from app.services import ai_prompts

logger = logging.getLogger(__name__)

_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


# 기존 함수 유지 (폴백용)
async def summarize_news(news_items: list[dict[str, Any]]) -> str:
    """뉴스 → AI 요약 (구버전, 폴백용)"""
    # ... 기존 코드 그대로
    ...


# 신규: 전문가 브리프
async def generate_expert_brief(
    global_market: dict[str, Any],
    domestic_market: dict[str, Any],
    investor_flow: dict[str, Any],
    news_items: list[dict[str, Any]],
    disclosure_items: list[dict[str, Any]],
) -> str:
    """전문가용 5섹션 브리프 생성. fail-soft 폴백."""
    if not settings.anthropic_api_key:
        logger.warning("Anthropic API 키 미설정 — 구버전 요약으로 폴백")
        return await summarize_news(news_items)

    system_prompt, user_prompt = ai_prompts.build_expert_brief_prompt(
        global_market=global_market,
        domestic_market=domestic_market,
        investor_flow=investor_flow,
        news_items=news_items,
        disclosure_items=disclosure_items,
    )

    try:
        client = _get_client()
        response = await client.messages.create(
            model=settings.ai_model,
            max_tokens=2500,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = response.content[0].text
        logger.info(
            "전문가 브리프 생성 완료 (in=%d, out=%d)",
            response.usage.input_tokens, response.usage.output_tokens,
        )
        return text
    except anthropic.RateLimitError:
        logger.warning("AI Rate limit — 구버전 요약으로 폴백")
        return await summarize_news(news_items)
    except Exception:
        logger.exception("전문가 브리프 생성 실패 — 구버전 요약으로 폴백")
        return await summarize_news(news_items)
```

### 수정: `backend/app/services/brief_service.py`

`generate_daily_brief()` 의 AI 요약 호출 변경:

```python
# 기존
news_summary = await _safe_collect(
    "ai_summary", ai_summarizer.summarize_news(news_items), "AI 요약을 생성하지 못했습니다."
)

# 변경 (P0-2의 investor_flow는 다음 섹션에서 추가됨)
investor_flow = await _safe_collect(
    "investor_flow",
    investor_flow_service.get_today_flow_summary(target_date=target_date),
    {},
)
news_summary = await _safe_collect(
    "ai_summary",
    ai_summarizer.generate_expert_brief(
        global_market=global_market,
        domestic_market=domestic_market,
        investor_flow=investor_flow,
        news_items=news_items,
        disclosure_items=dart_items,
    ),
    "AI 요약을 생성하지 못했습니다.",
)
```

`investor_flow_service` import는 P0-2 적용 후 추가됩니다.

### 검증

```bash
cd backend
python3 -c "
from app.services.ai_prompts import build_expert_brief_prompt
system, user = build_expert_brief_prompt(
    global_market={'sp500': {'label': 'S&P 500', 'close': 5234.5, 'change_pct': 0.5}},
    domestic_market={'kospi': {'label': 'KOSPI', 'close': 2700, 'change_pct': -0.3}},
    investor_flow={'foreign_net_billion': -3200, 'institution_net_billion': 1500},
    news_items=[{'title': '테스트 뉴스', 'description': 'desc'}],
    disclosure_items=[{'corp_name': '삼성전자', 'title': '수주', 'importance': '🟢'}],
)
print('=== SYSTEM ===')
print(system[:300])
print('=== USER (앞 1500자) ===')
print(user[:1500])
"
```

**예상**: 5섹션 구조 프롬프트 출력.

---

## 3. P0-2: 외인/기관 수급 + TOP 종목

### 목적

한국 시장 가장 중요한 일일 시그널: 외인·기관 수급. 현재 시스템에 없음. pykrx로 무료 수집.

### 변경 파일

- **신규**: `backend/app/collectors/investor_flow_collector.py`
- **신규**: `backend/app/services/investor_flow_service.py`
- **수정**: `backend/app/services/telegram_service.py` (수급 섹션 포맷 추가)
- **수정**: `backend/app/models/brief.py` (investor_flow JSON 컬럼 추가)
- **수정**: `backend/app/services/brief_service.py` (P0-1에서 이미 통합)

### 신규 파일: `backend/app/collectors/investor_flow_collector.py`

```python
"""KRX 투자자별 매매 + 외인 매수/매도 TOP 종목 (pykrx)."""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _fetch_market_flow_sync(target_date: date) -> Optional[dict[str, float]]:
    """전체 시장(KOSPI+KOSDAQ) 투자자별 순매수 (단위: 억원)."""
    try:
        from pykrx import stock
        date_str = target_date.strftime("%Y%m%d")

        kospi_df = stock.get_market_trading_value_by_investor(
            date_str, date_str, "KOSPI"
        )
        kosdaq_df = stock.get_market_trading_value_by_investor(
            date_str, date_str, "KOSDAQ"
        )

        def _net(df, label: str) -> float:
            try:
                return float(df.loc[label, "순매수"]) / 1e8
            except (KeyError, IndexError):
                return 0.0

        foreign = _net(kospi_df, "외국인") + _net(kosdaq_df, "외국인")
        inst = _net(kospi_df, "기관합계") + _net(kosdaq_df, "기관합계")
        retail = _net(kospi_df, "개인") + _net(kosdaq_df, "개인")

        return {
            "foreign_net_billion": round(foreign, 0),
            "institution_net_billion": round(inst, 0),
            "retail_net_billion": round(retail, 0),
            "trade_date": target_date.isoformat(),
        }
    except Exception:
        logger.exception("KRX 시장 수급 조회 실패 (%s)", target_date)
        return None


def _fetch_top_foreign_traders_sync(
    target_date: date, limit_buy: int = 10, limit_sell: int = 5
) -> list[dict[str, Any]]:
    """외국인 순매수/매도 상위 종목.

    Returns: 매수 TOP + 매도 TOP 통합 리스트
    """
    try:
        from pykrx import stock
        date_str = target_date.strftime("%Y%m%d")

        df_kospi = stock.get_market_net_purchases_of_equities(
            date_str, date_str, "KOSPI", "외국인"
        )
        df_kosdaq = stock.get_market_net_purchases_of_equities(
            date_str, date_str, "KOSDAQ", "외국인"
        )

        items: list[dict[str, Any]] = []
        for df in (df_kospi, df_kosdaq):
            if df is None or df.empty:
                continue
            value_col = None
            for c in df.columns:
                if "순매수" in c and "대금" in c:
                    value_col = c
                    break
            if value_col is None:
                continue
            for code, row in df.iterrows():
                items.append({
                    "stock_code": str(code).zfill(6),
                    "stock_name": str(row.get("종목명", "")),
                    "net_billion": round(float(row[value_col]) / 1e8, 0),
                })

        items.sort(key=lambda x: x["net_billion"], reverse=True)
        buys = items[:limit_buy]
        sells = [i for i in items if i["net_billion"] < 0]
        sells.sort(key=lambda x: x["net_billion"])
        sells = sells[:limit_sell]

        return buys + sells
    except Exception:
        logger.exception("KRX 외인 매수/매도 조회 실패 (%s)", target_date)
        return []


async def get_market_flow(target_date: date) -> Optional[dict[str, float]]:
    return await asyncio.to_thread(_fetch_market_flow_sync, target_date)


async def get_top_foreign_traders(
    target_date: date, limit_buy: int = 10, limit_sell: int = 5
) -> list[dict[str, Any]]:
    return await asyncio.to_thread(
        _fetch_top_foreign_traders_sync, target_date, limit_buy, limit_sell
    )


def latest_trading_date(today: Optional[date] = None) -> date:
    """주말 회피한 직전 거래일."""
    d = today or date.today()
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d - timedelta(days=2)
    yesterday = d - timedelta(days=1)
    if yesterday.weekday() == 6:
        return yesterday - timedelta(days=2)
    if yesterday.weekday() == 5:
        return yesterday - timedelta(days=1)
    return yesterday
```

### 신규 파일: `backend/app/services/investor_flow_service.py`

```python
"""투자자 수급 요약 — 브리프용 가공."""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

from app.collectors import investor_flow_collector

logger = logging.getLogger(__name__)


# 간이 종목 → 섹터 매핑 (운영하며 확장)
SECTOR_HINTS = {
    # 반도체
    "삼성전자": "반도체", "SK하이닉스": "반도체", "한미반도체": "반도체",
    "이오테크닉스": "반도체", "HPSP": "반도체", "리노공업": "반도체",
    "동진쎄미켐": "반도체소재", "솔브레인": "반도체소재", "원익IPS": "반도체장비",
    "이수페타시스": "반도체PCB", "심텍": "반도체PCB",
    # 2차전지
    "삼성SDI": "2차전지", "LG에너지솔루션": "2차전지", "SK이노베이션": "2차전지",
    "에코프로비엠": "2차전지소재", "엘앤에프": "2차전지소재", "포스코퓨처엠": "2차전지소재",
    # 바이오/제약
    "셀트리온": "바이오", "유한양행": "바이오", "한미약품": "바이오",
    "알테오젠": "바이오", "삼성바이오로직스": "바이오", "SK바이오팜": "바이오",
    "리가켐바이오": "바이오",
    # IT/플랫폼
    "네이버": "플랫폼", "카카오": "플랫폼", "크래프톤": "게임",
    "엔씨소프트": "게임", "넷마블": "게임", "펄어비스": "게임",
    # 자동차
    "현대차": "자동차", "기아": "자동차", "현대모비스": "자동차",
    "한온시스템": "자동차부품", "HL만도": "자동차부품",
    # 철강/소재
    "POSCO홀딩스": "철강", "고려아연": "비철금속", "현대제철": "철강",
    # 조선
    "HD현대중공업": "조선", "삼성중공업": "조선", "한화오션": "조선",
    "HD한국조선해양": "조선",
    # 방산
    "한화에어로스페이스": "방산", "LIG넥스원": "방산", "현대로템": "방산",
    "한화시스템": "방산",
    # 금융
    "KB금융": "금융", "신한지주": "금융", "하나금융지주": "금융",
    "메리츠금융지주": "금융", "우리금융지주": "금융", "기업은행": "금융",
    # 기타 대형주
    "LG화학": "화학", "LG전자": "가전", "삼성전기": "전자부품",
    "LG이노텍": "전자부품", "SK스퀘어": "지주", "두산에너빌리티": "에너지",
}


def _classify_sector(stock_name: str) -> str:
    return SECTOR_HINTS.get(stock_name, "기타")


async def get_today_flow_summary(
    target_date: Optional[date] = None,
) -> dict[str, Any]:
    """브리프용 수급 요약. 실패 시 빈 dict."""
    trade_date = (
        target_date if target_date else investor_flow_collector.latest_trading_date()
    )

    market_flow = await investor_flow_collector.get_market_flow(trade_date)
    if market_flow is None:
        logger.warning("수급 데이터 조회 실패 (%s)", trade_date)
        return {}

    top_traders = await investor_flow_collector.get_top_foreign_traders(
        trade_date, limit_buy=10, limit_sell=5
    )

    # 섹터별 net 집계 (매수 종목 기준)
    buyers = [t for t in top_traders if t["net_billion"] > 0]
    sector_net: dict[str, float] = {}
    for b in buyers:
        sector = _classify_sector(b["stock_name"])
        sector_net[sector] = sector_net.get(sector, 0) + b["net_billion"]

    sorted_sectors = sorted(sector_net.items(), key=lambda x: x[1], reverse=True)
    buy_sectors = [s for s, v in sorted_sectors if v > 0 and s != "기타"][:5]

    # 매도 섹터
    sellers = [t for t in top_traders if t["net_billion"] < 0]
    sell_sector_net: dict[str, float] = {}
    for s in sellers:
        sector = _classify_sector(s["stock_name"])
        sell_sector_net[sector] = sell_sector_net.get(sector, 0) + s["net_billion"]
    sorted_sell = sorted(sell_sector_net.items(), key=lambda x: x[1])
    sell_sectors = [s for s, v in sorted_sell if v < 0 and s != "기타"][:5]

    return {
        **market_flow,
        "top_buy_sectors": buy_sectors,
        "top_sell_sectors": sell_sectors,
        "top_foreign_traders": top_traders[:15],  # 매수 + 매도
    }
```

### 수정: `backend/app/services/telegram_service.py`

`format_brief()` 안에 수급 섹션 추가. 위치는 DART 공시 섹션 위:

```python
def _format_flow_section(flow: dict[str, Any]) -> str:
    """수급 데이터 텔레그램 포맷."""
    if not flow:
        return ""

    lines = ["<b>💰 수급 (전일)</b>"]

    foreign = flow.get("foreign_net_billion")
    inst = flow.get("institution_net_billion")
    retail = flow.get("retail_net_billion")

    def _fmt(label: str, val: Optional[float]) -> str:
        if val is None:
            return f"  {label}: 데이터 없음"
        emoji = "🟢" if val > 0 else "🔴" if val < 0 else "⚪"
        sign = "+" if val > 0 else ""
        return f"  {emoji} {label}: {sign}{val:,.0f}억"

    lines.append(_fmt("외국인", foreign))
    lines.append(_fmt("기관", inst))
    if retail is not None:
        lines.append(_fmt("개인", retail))

    buy_sectors = flow.get("top_buy_sectors", [])
    sell_sectors = flow.get("top_sell_sectors", [])
    if buy_sectors:
        lines.append(f"  외인 매수 우위: {', '.join(buy_sectors[:3])}")
    if sell_sectors:
        lines.append(f"  외인 매도 우위: {', '.join(sell_sectors[:3])}")

    # 외인 매수 TOP 5
    top_traders = flow.get("top_foreign_traders", [])
    buys = [t for t in top_traders if t["net_billion"] > 0][:5]
    if buys:
        lines.append("")
        lines.append("  <b>외인 매수 TOP 5</b>")
        for b in buys:
            net = b["net_billion"]
            lines.append(
                f"    • {escape_html(b['stock_name'])} ({b['stock_code']}) "
                f"+{net:,.0f}억"
            )

    # 외인 매도 TOP 3
    sells = [t for t in top_traders if t["net_billion"] < 0][:3]
    if sells:
        lines.append("")
        lines.append("  <b>외인 매도 TOP 3</b>")
        for s in sells:
            net = s["net_billion"]
            lines.append(
                f"    • {escape_html(s['stock_name'])} ({s['stock_code']}) "
                f"{net:,.0f}억"
            )

    return "\n".join(lines)
```

`format_brief()` 안에서 호출 (DART 공시 섹션 위):

```python
# 수급
flow = getattr(brief, "investor_flow", None) or {}
flow_section = _format_flow_section(flow)
if flow_section:
    parts.append(flow_section)
    parts.append("")
```

### 모델 변경: `backend/app/models/brief.py`

```python
investor_flow: Mapped[dict] = mapped_column(JSON, default=dict, nullable=True)
```

`brief_service.py` 의 DailyBrief 생성 시 `investor_flow=investor_flow` 추가.

### DB 마이그레이션

```bash
# SQLite
sqlite3 backend/data/investbrief.db <<'SQL'
ALTER TABLE daily_briefs ADD COLUMN investor_flow JSON DEFAULT '{}';
SQL

# PostgreSQL (운영 환경 — 사용 중인 경우만)
psql "$DATABASE_URL" <<'SQL'
ALTER TABLE daily_briefs ADD COLUMN IF NOT EXISTS investor_flow JSONB DEFAULT '{}'::jsonb;
SQL

# 검증
sqlite3 backend/data/investbrief.db ".schema daily_briefs" | grep investor_flow
```

### 검증

```bash
cd backend
python3 -c "
import asyncio
from app.services.investor_flow_service import get_today_flow_summary

async def test():
    result = await get_today_flow_summary()
    print(result)

asyncio.run(test())
"
```

**예상**: 외인/기관 순매수 + 매수/매도 TOP 종목 출력.

---

## 4. P0-3: 종목명 본문 추출

### 목적

`theme_radar_service` 와 `theme_discovery_service` 의 종목명 추출이 헤드라인만 사용. 본문(`description`)도 활용하면 종목 발굴 폭 2~3배 확대.

### 변경 파일

- **수정**: `backend/app/services/theme_radar_service.py` (1개 함수)
- **수정**: `backend/app/services/theme_discovery_service.py` (1개 함수)

### theme_radar_service.py 수정

`_scan_single_theme()` 내부:

**기존**:
```python
for news in all_news:
    title = news.get("title", "")
    candidates = set(STOCK_NAME_PATTERN.findall(title))
```

**변경**:
```python
for news in all_news:
    title = news.get("title", "")
    description = news.get("description", "")
    combined_text = f"{title} {description[:200]}"
    candidates = set(STOCK_NAME_PATTERN.findall(combined_text))
```

### theme_discovery_service.py 수정

`_analyze_stock_frequency_with_titles()` 도 동일 패턴 적용 (찾기는 같은 함수).

### candidate 수 제한 (Claude 검증 비용 통제)

`theme_radar_service.py` 상단에 상수 추가:

```python
MAX_CANDIDATES_PER_THEME = 30
```

`_scan_single_theme()` 내부, detected_stocks 빌드 후:

```python
if len(detected_stocks) > MAX_CANDIDATES_PER_THEME:
    # 헤드라인 매칭 우선
    headline_first = {
        k: v for k, v in detected_stocks.items()
        if v["stock_name"] in v.get("headline", "")
    }
    body_only = {
        k: v for k, v in detected_stocks.items()
        if k not in headline_first
    }
    limited: dict[str, dict] = dict(headline_first)
    for k, v in body_only.items():
        if len(limited) >= MAX_CANDIDATES_PER_THEME:
            break
        limited[k] = v
    detected_stocks = limited
    logger.info(
        "테마 %s: candidate 초과 → %d개로 제한",
        theme.name, MAX_CANDIDATES_PER_THEME,
    )
```

### 검증

운영 로그에서 "테마 검증" 로그 라인 증가 추이 모니터링.

---

## 5. P0-4: 펀더멘털 최소 (신규)

### 목적

P1-7 종목 4차원 점수의 펀더멘털 항목이 기본 50점(중립) → **흑/적자, 영업이익률만 추가**해도 종목 점수 신뢰도 큰 향상.

**제외한 것** (P2-7 full 대비):
- ❌ corp_code 매핑 캐시 (전체 DART 다운로드)
- ❌ market_cap TTL 캐싱
- ❌ PER/PBR/ROE 계산
- ❌ 분기별 EPS 추이

**포함한 것** (P0-4 최소):
- ✅ DART 단일 분기 매출/영업이익/당기순이익만 조회
- ✅ 흑자/적자 분류 + 영업이익률 계산
- ✅ 14일 freshness 캐시 (분기 발표 후 자주 안 바뀜)

⚠️ **솔직한 한계**:
- corp_code는 P0-2의 DART 공시 응답에 함께 옴 → 별도 매핑 인프라 불필요
- 단, **DART 공시에 등장 안 한 종목**은 corp_code 모름 → 점수 50점 중립 유지
- 운영 후 corp_code 캐시 누적되면 커버리지 확대

### 변경 파일

- **신규**: `backend/app/models/fundamental_cache.py`
- **신규**: `backend/app/collectors/dart_financial_simple.py`
- **신규**: `backend/app/services/fundamental_simple_service.py`
- **수정**: `backend/app/collectors/dart_collector.py` (corp_code 캐시 추가)
- **수정**: `backend/app/services/stock_scoring_service.py` (P1-7에서 호출, **P0-4 적용 전엔 미존재**)
- **수정**: `backend/app/models/__init__.py`
- **수정**: `backend/app/database.py`

### 모델: `backend/app/models/fundamental_cache.py`

```python
"""펀더멘털 최소 캐시 — 분기별 흑/적자 + 영업이익률."""
import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import Date, DateTime, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

_KST = ZoneInfo("Asia/Seoul")


class FundamentalSimple(Base):
    """종목별 분기 손익 캐시 (DART 직접 조회).

    매출/영업이익/당기순이익만 저장.
    PER/ROE 등은 P2-7 도입 시 별도 컬럼 추가.
    """
    __tablename__ = "fundamental_simple"
    __table_args__ = (
        UniqueConstraint("stock_code", "year", "quarter", name="uq_fs_code_year_q"),
        Index("ix_fs_stock_code", "stock_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(6), nullable=False)
    corp_code: Mapped[str] = mapped_column(String(8), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    quarter: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-4

    # 손익 (단위: 억원)
    revenue: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    operating_profit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    net_income: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 계산 지표
    operating_margin_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_profitable: Mapped[Optional[bool]] = mapped_column(nullable=True)

    fetched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.datetime.now(_KST)
    )


class StockCorpMap(Base):
    """stock_code ↔ corp_code 단순 매핑 캐시.
    
    DART 공시 응답에서 함께 오는 정보를 누적 저장.
    별도 전체 다운로드 없이 운영하며 자연스럽게 커버리지 확대.
    """
    __tablename__ = "stock_corp_map"
    __table_args__ = (
        Index("ix_stock_corp_code", "stock_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(6), unique=True, nullable=False)
    corp_code: Mapped[str] = mapped_column(String(8), nullable=False)
    corp_name: Mapped[str] = mapped_column(String(200), nullable=False)
    last_seen: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.datetime.now(_KST)
    )
```

### 신규: `backend/app/collectors/dart_financial_simple.py`

```python
"""DART 분기 재무 단순 조회 — 매출/영업이익/당기순이익만.

corp_code는 DART 공시 응답에서 자연스럽게 캐시되는 stock_corp_map 활용.
별도 전체 corp_code 다운로드는 P2-7 도입 시 추가.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

DART_SINGL_ACNT_URL = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"


def _current_year_quarter() -> tuple[int, int]:
    """가장 최근 발표 가능 분기."""
    today = date.today()
    y, m = today.year, today.month
    if m >= 11:
        return y, 3
    if m >= 8:
        return y, 2
    if m >= 5:
        return y, 1
    return y - 1, 4


async def fetch_quarterly_simple(
    corp_code: str, year: Optional[int] = None, quarter: Optional[int] = None
) -> Optional[dict[str, Any]]:
    """분기 매출/영업이익/당기순이익 조회.

    Returns:
        {"revenue": float, "operating_profit": float, "net_income": float}
        (단위: 억원)
        실패 시 None.
    """
    if not settings.dart_api_key:
        return None

    if year is None or quarter is None:
        year, quarter = _current_year_quarter()

    reprt_code_map = {1: "11013", 2: "11012", 3: "11014", 4: "11011"}
    reprt_code = reprt_code_map.get(quarter)
    if not reprt_code:
        return None

    params = {
        "crtfc_key": settings.dart_api_key,
        "corp_code": corp_code,
        "bsns_year": str(year),
        "reprt_code": reprt_code,
        "fs_div": "CFS",  # 연결, 없으면 OFS 폴백
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(DART_SINGL_ACNT_URL, params=params)
            resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "000":
            # CFS 없으면 OFS 재시도
            params["fs_div"] = "OFS"
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(DART_SINGL_ACNT_URL, params=params)
            data = resp.json()
            if data.get("status") != "000":
                logger.debug(
                    "DART 재무 없음: %s %d Q%d (status=%s)",
                    corp_code, year, quarter, data.get("status"),
                )
                return None

        return _parse_simple(data.get("list", []))
    except Exception:
        logger.exception("DART 재무 조회 실패: %s %d Q%d", corp_code, year, quarter)
        return None


def _parse_simple(items: list[dict[str, Any]]) -> dict[str, Optional[float]]:
    """3개 항목만 추출."""
    result: dict[str, Optional[float]] = {
        "revenue": None,
        "operating_profit": None,
        "net_income": None,
    }

    def _to_billion(s: str) -> Optional[float]:
        try:
            return round(float(s.replace(",", "")) / 1e8, 2)
        except (ValueError, AttributeError):
            return None

    matchers = {
        "revenue": ["매출액", "수익(매출액)", "영업수익"],
        "operating_profit": ["영업이익", "영업이익(손실)"],
        "net_income": ["당기순이익", "당기순이익(손실)"],
    }

    for item in items:
        account_nm = item.get("account_nm", "")
        amount_str = item.get("thstrm_amount", "")
        for key, candidates in matchers.items():
            if result[key] is None and account_nm in candidates:
                result[key] = _to_billion(amount_str)
                break

    return result
```

### 신규: `backend/app/services/fundamental_simple_service.py`

```python
"""펀더멘털 최소 서비스 — 캐시 우선, 14일 freshness."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import select

from app.collectors import dart_financial_simple
from app.database import async_session
from app.models.fundamental_cache import FundamentalSimple, StockCorpMap

logger = logging.getLogger(__name__)


FUNDAMENTAL_FRESH_DAYS = 14


async def get_corp_code(stock_code: str) -> Optional[str]:
    """stock_code → corp_code (DART 공시 누적 캐시에서 조회).

    캐시 miss 시 None — 해당 종목 펀더 점수는 중립(50점) 처리.
    운영하며 공시 발생 시 자연스럽게 캐시 누적.
    """
    async with async_session() as session:
        result = await session.execute(
            select(StockCorpMap).where(StockCorpMap.stock_code == stock_code)
        )
        row = result.scalar_one_or_none()
        return row.corp_code if row else None


async def update_corp_map(
    stock_code: str, corp_code: str, corp_name: str
) -> None:
    """DART 공시에서 corp_code 발견 시 호출 — idempotent."""
    if not stock_code or not corp_code:
        return
    async with async_session() as session:
        result = await session.execute(
            select(StockCorpMap).where(StockCorpMap.stock_code == stock_code)
        )
        row = result.scalar_one_or_none()
        if row:
            row.corp_code = corp_code
            row.corp_name = corp_name
            row.last_seen = datetime.now()
        else:
            session.add(StockCorpMap(
                stock_code=stock_code, corp_code=corp_code, corp_name=corp_name,
            ))
        await session.commit()


async def get_or_fetch_fundamental(
    stock_code: str,
) -> Optional[FundamentalSimple]:
    """캐시 우선, miss/stale 시 DART 직접 조회."""
    corp_code = await get_corp_code(stock_code)
    if not corp_code:
        return None  # corp_code 모름 → 펀더 점수 중립 처리

    today = date.today()
    async with async_session() as session:
        result = await session.execute(
            select(FundamentalSimple)
            .where(FundamentalSimple.stock_code == stock_code)
            .order_by(
                FundamentalSimple.year.desc(),
                FundamentalSimple.quarter.desc(),
            )
            .limit(1)
        )
        cached = result.scalar_one_or_none()
        if cached and (today - cached.fetched_at.date()).days < FUNDAMENTAL_FRESH_DAYS:
            return cached

    # DART 조회
    data = await dart_financial_simple.fetch_quarterly_simple(corp_code)
    if not data or not any(data.values()):
        return cached  # 실패 → stale라도 반환

    revenue = data.get("revenue")
    operating_profit = data.get("operating_profit")
    net_income = data.get("net_income")

    operating_margin = None
    if revenue and revenue > 0 and operating_profit is not None:
        operating_margin = round((operating_profit / revenue) * 100, 2)

    is_profitable = None
    if net_income is not None:
        is_profitable = net_income > 0

    from app.collectors.dart_financial_simple import _current_year_quarter
    year, quarter = _current_year_quarter()

    async with async_session() as session:
        existing = await session.execute(
            select(FundamentalSimple)
            .where(FundamentalSimple.stock_code == stock_code)
            .where(FundamentalSimple.year == year)
            .where(FundamentalSimple.quarter == quarter)
        )
        row = existing.scalar_one_or_none()
        if row:
            row.revenue = revenue
            row.operating_profit = operating_profit
            row.net_income = net_income
            row.operating_margin_pct = operating_margin
            row.is_profitable = is_profitable
            row.fetched_at = datetime.now()
        else:
            row = FundamentalSimple(
                stock_code=stock_code,
                corp_code=corp_code,
                year=year,
                quarter=quarter,
                revenue=revenue,
                operating_profit=operating_profit,
                net_income=net_income,
                operating_margin_pct=operating_margin,
                is_profitable=is_profitable,
            )
            session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


def calculate_score(fs: Optional[FundamentalSimple]) -> float:
    """펀더멘털 점수 0-100.

    데이터 없음 → 50 (중립)
    적자 → 20
    흑자 + 영업이익률 미상 → 60
    흑자 + 영업이익률 0-5% → 65
    흑자 + 영업이익률 5-10% → 75
    흑자 + 영업이익률 10-20% → 85
    흑자 + 영업이익률 20%+ → 95
    """
    if fs is None:
        return 50.0

    if fs.is_profitable is False:
        return 20.0

    if fs.is_profitable is True:
        if fs.operating_margin_pct is None:
            return 60.0
        margin = fs.operating_margin_pct
        if margin >= 20:
            return 95.0
        if margin >= 10:
            return 85.0
        if margin >= 5:
            return 75.0
        if margin >= 0:
            return 65.0
        return 40.0  # 영업적자지만 당기순이익 흑자 (이례)

    return 50.0
```

### 수정: `backend/app/collectors/dart_collector.py`

`get_today_disclosures()` 안에서 corp_code 자동 캐시:

```python
# 기존 items 빌드 루프 끝부분에 추가
for item in data.get("list", []):
    items.append({...})  # 기존
    
# 신규: corp_code 자연스러운 캐시 누적
try:
    from app.services import fundamental_simple_service
    for item in data.get("list", []):
        stock_code = item.get("stock_code", "")
        corp_code = item.get("corp_code", "")
        corp_name = item.get("corp_name", "")
        if stock_code and corp_code and len(stock_code) == 6:
            await fundamental_simple_service.update_corp_map(
                stock_code, corp_code, corp_name
            )
except Exception:
    logger.exception("corp_code 캐시 업데이트 실패 (무시)")
```

⚠️ **이게 핵심**: 별도 전체 corp_code 다운로드 없이 **운영하면서 자연스럽게 누적**. 6개월이면 활발한 종목 90%+ 커버리지 달성.

### P1-7 통합 변경

`stock_scoring_service._calculate_for_stock()` 의 다음 줄:

```python
# 옵션 C 원래 (P0-4 없으면)
fundamental_score = 50.0
```

→

```python
# 옵션 C+ (P0-4 적용 후)
fs = await fundamental_simple_service.get_or_fetch_fundamental(stock_code)
fundamental_score = fundamental_simple_service.calculate_score(fs)
```

### 모델 export

```python
# app/models/__init__.py
from app.models.fundamental_cache import FundamentalSimple, StockCorpMap

__all__ = [
    # ... 기존
    "FundamentalSimple", "StockCorpMap",
]

# app/database.py init_db()
async def init_db():
    from app.models import (
        # ... 기존
        FundamentalSimple, StockCorpMap,
    )
    ...
```

### DB 마이그레이션

```bash
cd backend
python3 -c "
import asyncio
from app.database import init_db
asyncio.run(init_db())
print('✅ fundamental_simple + stock_corp_map 테이블 생성')
"

sqlite3 backend/data/investbrief.db ".tables" | tr ' ' '\n' | grep -E "fundamental_simple|stock_corp_map"
```

### 검증

```bash
cd backend
python3 << 'EOF'
import asyncio
from app.services import fundamental_simple_service

async def test():
    # 삼성전자 (corp_code: 00126380) 직접 등록 후 조회 테스트
    await fundamental_simple_service.update_corp_map(
        "005930", "00126380", "삼성전자"
    )
    
    fs = await fundamental_simple_service.get_or_fetch_fundamental("005930")
    if fs:
        print(f"매출: {fs.revenue:,.0f}억")
        print(f"영업이익: {fs.operating_profit:,.0f}억")
        print(f"당기순이익: {fs.net_income:,.0f}억")
        print(f"영업이익률: {fs.operating_margin_pct}%")
        print(f"흑자: {fs.is_profitable}")
        print(f"점수: {fundamental_simple_service.calculate_score(fs)}")
    else:
        print("재무 데이터 없음")

asyncio.run(test())
EOF
```

**예상**: 삼성전자 흑자 + 영업이익률 10%+ → 85점 정도.

---

## 6. P0-5: 시장 위험 모드 단순 진단 (신규)

### 목적

전문가가 모닝브리프에서 가장 먼저 보는 정보: **"오늘 시장 위험 모드인가 정상인가"**

P1-9 full (7개 변수, 자산배분 권고)은 임계값 추측 문제 있으므로 **3개 변수 단순화**:

1. **VIX** (전일 종가)
2. **환율 5일 변동** (USD/KRW)
3. **외인 5일 연속 순매도** 여부

→ 3단계 분류: **정상 / 주의 / 위험**

⚠️ **임계값은 여전히 추측이지만**:
- 변수 적어서 디버깅 쉬움
- 자산배분 권고 같은 위험한 조언 없음
- 단순 표시만 ("⚠️ 주의 모드") — 사용자 판단 우선

### 변경 파일

- **신규**: `backend/app/services/market_risk_simple.py`
- **수정**: `backend/app/services/brief_service.py` (모닝브리프 호출 추가)
- **수정**: `backend/app/services/telegram_service.py` (헤더 표시)
- **수정**: `backend/app/services/ai_prompts.py` (프롬프트에 주입)

### 신규: `backend/app/services/market_risk_simple.py`

```python
"""시장 위험 모드 단순 진단 — 3개 변수 종합.

⚠️ 임계값(VIX 25, 환율 +2%, 외인 5일 매도)은 운영 데이터로 보정 필요.
보수적으로 설정 (false positive 적게).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ⚠️ 운영 후 보정 (현재는 보수적 임계값)
VIX_WARNING = 22
VIX_CRITICAL = 28
USDKRW_5D_PCT_WARNING = 1.5
USDKRW_5D_PCT_CRITICAL = 3.0
FOREIGN_SELL_DAYS_WARNING = 3
FOREIGN_SELL_DAYS_CRITICAL = 5


async def diagnose_simple(
    global_market: dict[str, Any],
    investor_flow_history: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """시장 위험 단순 진단.

    Args:
        global_market: P0-1 입력의 글로벌 시장 데이터
        investor_flow_history: 최근 5일 외인 net_billion (None이면 외인 시그널 스킵)

    Returns:
        {
            "level": "정상" | "주의" | "위험",
            "factors": [str, ...],
            "score": int,  # 0-100 (debug용)
        }
    """
    score = 0
    factors: list[str] = []

    # 1. VIX
    vix_data = global_market.get("vix") or global_market.get("VIX")
    if vix_data:
        vix = vix_data.get("close", 0)
        if vix >= VIX_CRITICAL:
            score += 50
            factors.append(f"VIX {vix:.1f} (위험 임계 {VIX_CRITICAL}+)")
        elif vix >= VIX_WARNING:
            score += 25
            factors.append(f"VIX {vix:.1f} (주의 임계 {VIX_WARNING}+)")

    # 2. 환율 5일 변동
    usdkrw_data = global_market.get("usdkrw") or global_market.get("USDKRW")
    if usdkrw_data:
        # 5일 변동률 (단순화: 단일 일변동을 대용으로 사용, 추후 보강 가능)
        # 5일 데이터가 있으면 활용, 없으면 일변동 ×3 추정
        chg = usdkrw_data.get("change_pct", 0)
        # 일변동 1% = 5일 +2~3% 추정 (러프)
        est_5d = abs(chg) * 2.5
        if est_5d >= USDKRW_5D_PCT_CRITICAL:
            score += 30
            factors.append(f"USD/KRW 급변 {chg:+.2f}% (위험)")
        elif est_5d >= USDKRW_5D_PCT_WARNING:
            score += 15
            factors.append(f"USD/KRW 변동 {chg:+.2f}% (주의)")

    # 3. 외인 5일 연속 매도
    if investor_flow_history:
        sells_in_row = 0
        for day in investor_flow_history[:5]:  # 최근 5일
            net = day.get("foreign_net_billion", 0)
            if net < 0:
                sells_in_row += 1
            else:
                break
        if sells_in_row >= FOREIGN_SELL_DAYS_CRITICAL:
            score += 30
            factors.append(f"외인 {sells_in_row}일 연속 순매도 (위험)")
        elif sells_in_row >= FOREIGN_SELL_DAYS_WARNING:
            score += 15
            factors.append(f"외인 {sells_in_row}일 연속 순매도 (주의)")

    # 분류
    if score >= 50:
        level = "위험"
    elif score >= 20:
        level = "주의"
    else:
        level = "정상"

    if not factors and level == "정상":
        factors = ["특이 위험 시그널 없음"]

    return {
        "level": level,
        "factors": factors,
        "score": score,
    }


async def get_investor_flow_history(days: int = 5) -> list[dict[str, Any]]:
    """최근 N일 외인 net 흐름 (P0-2 collector 활용).

    조회 부하 큼 — P0-5에서는 옵션. 없으면 외인 시그널 스킵.
    """
    try:
        from app.collectors import investor_flow_collector
        results = []
        end_date = investor_flow_collector.latest_trading_date()
        check_date = end_date
        for _ in range(days * 2):  # 휴장일 흡수
            if len(results) >= days:
                break
            flow = await investor_flow_collector.get_market_flow(check_date)
            if flow:
                results.append({
                    "date": check_date.isoformat(),
                    "foreign_net_billion": flow.get("foreign_net_billion", 0),
                })
            check_date -= timedelta(days=1)
            if check_date.weekday() >= 5:
                check_date -= timedelta(days=2)
        return results
    except Exception:
        logger.exception("외인 5일 흐름 조회 실패")
        return []
```

### `brief_service.py` 통합

```python
# generate_daily_brief() 안 (P0-1 통합 다음)
from app.services import market_risk_simple

market_risk = await _safe_collect(
    "market_risk",
    _diagnose_market_risk(global_market),
    {"level": "정상", "factors": [], "score": 0},
)


async def _diagnose_market_risk(global_market: dict) -> dict:
    """위험 진단 헬퍼."""
    flow_history = await market_risk_simple.get_investor_flow_history(days=5)
    return await market_risk_simple.diagnose_simple(
        global_market=global_market,
        investor_flow_history=flow_history,
    )
```

### `ai_prompts.py` 변경

`EXPERT_BRIEF_USER_TEMPLATE` 의 시장 컨텍스트 섹션 위에 추가:

```python
EXPERT_BRIEF_USER_TEMPLATE = """다음은 오늘의 시장 데이터와 뉴스입니다.

━━━━━━━━━━━━━━━━━━━━━━━━━
🚦 시장 위험 모드
{market_risk_text}

━━━━━━━━━━━━━━━━━━━━━━━━━
🌍 글로벌 시장 (전일)
{global_market_text}
...
"""
```

`build_expert_brief_prompt()` 시그니처에 `market_risk` 매개변수 추가:

```python
def build_expert_brief_prompt(
    global_market, domestic_market, investor_flow,
    news_items, disclosure_items,
    market_risk: dict = None,  # 신규
) -> tuple[str, str]:
    risk_text = "정상 모드 (특이 시그널 없음)"
    if market_risk:
        level = market_risk.get("level", "정상")
        factors = market_risk.get("factors", [])
        if factors:
            risk_text = f"{level} — {'; '.join(factors[:3])}"
        else:
            risk_text = f"{level} 모드"
    
    user_prompt = EXPERT_BRIEF_USER_TEMPLATE.format(
        market_risk_text=risk_text,
        # ... 기존
    )
```

시스템 프롬프트에 1줄 추가:

```python
EXPERT_BRIEF_SYSTEM = """... (기존)

특별 지시: "시장 위험 모드"가 제공되면 섹션 1(시장 컨텍스트) 첫 줄에서
모드를 명시하고, 섹션 5(리스크 시그널)에서 위험 요인을 활용하세요."""
```

### 텔레그램 헤더 표시: `telegram_service.py`

`format_brief()` 의 헤더에 위험 모드 1줄 추가:

```python
def _format_risk_header(market_risk: dict) -> str:
    """위험 모드 헤더 (1줄)."""
    if not market_risk:
        return ""
    level = market_risk.get("level", "정상")
    factors = market_risk.get("factors", [])
    
    emoji_map = {"정상": "🟢", "주의": "🟠", "위험": "🔴"}
    emoji = emoji_map.get(level, "⚪")
    
    if level == "정상":
        return f"{emoji} <b>시장 위험 모드: 정상</b>"
    
    factor_str = "; ".join(factors[:2])
    return (
        f"{emoji} <b>시장 위험 모드: {level}</b>\n"
        f"<i>{escape_html(factor_str)}</i>"
    )


# format_brief() 헤더 직후에 추가
risk = getattr(brief, "market_risk", None) or {}
risk_section = _format_risk_header(risk)
if risk_section:
    parts.append(risk_section)
    parts.append("")
```

### 모델 변경: `brief.py`

```python
market_risk: Mapped[dict] = mapped_column(JSON, default=dict, nullable=True)
```

### DB 마이그레이션

```bash
# SQLite
sqlite3 backend/data/investbrief.db <<'SQL'
ALTER TABLE daily_briefs ADD COLUMN market_risk JSON DEFAULT '{}';
SQL

# PostgreSQL
psql "$DATABASE_URL" <<'SQL'
ALTER TABLE daily_briefs ADD COLUMN IF NOT EXISTS market_risk JSONB DEFAULT '{}'::jsonb;
SQL
```

### 검증

```bash
cd backend
python3 << 'EOF'
import asyncio
from app.services import market_risk_simple

async def test():
    # 시나리오 1: 정상 모드
    result = await market_risk_simple.diagnose_simple(
        global_market={
            "vix": {"close": 15, "change_pct": 0.3},
            "usdkrw": {"close": 1380, "change_pct": 0.2},
        },
        investor_flow_history=[
            {"foreign_net_billion": 500},
            {"foreign_net_billion": 200},
        ],
    )
    print("정상:", result)
    
    # 시나리오 2: 주의 모드
    result = await market_risk_simple.diagnose_simple(
        global_market={
            "vix": {"close": 24, "change_pct": 0.5},
            "usdkrw": {"close": 1410, "change_pct": 0.8},
        },
        investor_flow_history=[
            {"foreign_net_billion": -300},
            {"foreign_net_billion": -200},
            {"foreign_net_billion": -100},
        ],
    )
    print("주의:", result)
    
    # 시나리오 3: 위험 모드
    result = await market_risk_simple.diagnose_simple(
        global_market={
            "vix": {"close": 30, "change_pct": 2.5},
            "usdkrw": {"close": 1450, "change_pct": 1.5},
        },
        investor_flow_history=[
            {"foreign_net_billion": -500},
            {"foreign_net_billion": -400},
            {"foreign_net_billion": -600},
            {"foreign_net_billion": -300},
            {"foreign_net_billion": -700},
        ],
    )
    print("위험:", result)

asyncio.run(test())
EOF
```

**예상 출력**:
```
정상: {'level': '정상', 'factors': ['특이 위험 시그널 없음'], 'score': 0}
주의: {'level': '주의', 'factors': ['VIX 24.0 (주의 임계 22+)', ...], 'score': 40+}
위험: {'level': '위험', 'factors': [...], 'score': 100+}
```

---

## 7. P0-6: 진입가/손절가/목표가 (신규)

### 목적

종목 발굴 후 가장 중요한 정보: **얼마에 사고, 언제 팔지**. 옵션 C+에는 점수만 있고 매매 실행 정보 0.

ATR(Average True Range) 기반 표준 기법으로 자동 산출:
- **진입가**: 현재가 (시장가) + 조정 진입 (-1%)
- **손절가**: 현재가 - 1.5×ATR
- **1차 목표가**: 현재가 + 3×ATR (R:R 1:2)
- **2차 목표가**: 60일 고가

⚠️ **솔직한 한계**:
- ATR 1.5배 손절은 일반적 기법 (Wilder, Chande 등이 1.5-2배 권장)
- **개인 트레이딩 스타일에 따라 조정 필요** (단기 트레이더는 1배, 장기는 3배)
- 절대 권고가 아니라 **참고 가격대** 제공

### 검증된 의존성

✅ `price_collector.fetch_close_history()` 반환 컬럼: `Open/High/Low/Close/Volume` (검증 완료)
→ ATR 계산에 필요한 High/Low 모두 사용 가능.

### 변경 파일

- **신규**: `backend/app/services/entry_levels_service.py`
- **수정**: `backend/app/services/stock_scoring_service.py` (P1-7 통합)

### 신규: `backend/app/services/entry_levels_service.py`

```python
"""ATR 기반 진입가/손절가/목표가 자동 산출.

⚠️ 절대 권고가 아닌 참고 가격대. 사용자 트레이딩 스타일에 따라 조정.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any, Optional

from app.collectors import price_collector

logger = logging.getLogger(__name__)


# 표준 ATR 기법 — 운영 후 보정 가능
ATR_PERIOD = 14
STOP_LOSS_ATR_MULTIPLIER = 1.5  # 손절: 1.5×ATR (Wilder 권장 범위)
TARGET_1_ATR_MULTIPLIER = 3.0   # 1차 목표: 3×ATR (R:R 1:2)
DIP_ENTRY_PCT = 0.99            # 조정 진입: 현재가 -1%
TARGET_2_LOOKBACK_DAYS = 60     # 2차 목표: 60일 고가


def _calculate_atr_sync(stock_code: str) -> Optional[dict[str, Any]]:
    """ATR 기반 진입/손절/목표 계산.

    Returns:
        {
            "current": float,
            "atr": float,
            "entry_market": float,
            "entry_dip": float,
            "stop_loss": float,
            "stop_loss_pct": float,
            "target_1": float,
            "target_1_pct": float,
            "target_2": float,
            "target_2_pct": float,
            "risk_reward": float,
        }
        실패 시 None.
    """
    try:
        start = date.today() - timedelta(days=TARGET_2_LOOKBACK_DAYS + 30)
        df = price_collector.fetch_close_history(stock_code, start=start)
        if df is None or len(df) < ATR_PERIOD + 1:
            return None

        # ATR 계산 (True Range = max(H-L, |H-prev_close|, |L-prev_close|))
        high = df["High"]
        low = df["Low"]
        close = df["Close"]
        prev_close = close.shift(1)

        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()

        # max를 행 단위로 계산
        import pandas as pd
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = float(tr.rolling(ATR_PERIOD).mean().iloc[-1])

        if atr <= 0 or atr != atr:  # NaN 체크
            return None

        current = float(close.iloc[-1])

        # 진입가
        entry_market = current
        entry_dip = round(current * DIP_ENTRY_PCT, 0)

        # 손절가
        stop_loss = round(current - atr * STOP_LOSS_ATR_MULTIPLIER, 0)
        stop_loss_pct = round((stop_loss - current) / current * 100, 2)

        # 1차 목표가 (R:R 1:2)
        target_1 = round(current + atr * TARGET_1_ATR_MULTIPLIER, 0)
        target_1_pct = round((target_1 - current) / current * 100, 2)

        # 2차 목표가 (60일 고가)
        target_2 = round(float(close.iloc[-min(TARGET_2_LOOKBACK_DAYS, len(close)):].max()), 0)
        # 만약 60일 고가가 현재가보다 낮으면 (계단형 하락 중) → 1차 목표×1.5 사용
        if target_2 <= current:
            target_2 = round(target_1 * 1.2, 0)
        target_2_pct = round((target_2 - current) / current * 100, 2)

        # R:R 비율
        risk = current - stop_loss
        reward_1 = target_1 - current
        risk_reward = round(reward_1 / risk, 2) if risk > 0 else 0.0

        return {
            "current": round(current, 0),
            "atr": round(atr, 2),
            "entry_market": round(entry_market, 0),
            "entry_dip": entry_dip,
            "stop_loss": stop_loss,
            "stop_loss_pct": stop_loss_pct,
            "target_1": target_1,
            "target_1_pct": target_1_pct,
            "target_2": target_2,
            "target_2_pct": target_2_pct,
            "risk_reward": risk_reward,
        }
    except Exception:
        logger.exception("진입/손절/목표 계산 실패: %s", stock_code)
        return None


async def get_entry_levels(stock_code: str) -> Optional[dict[str, Any]]:
    """비동기 래퍼."""
    return await asyncio.to_thread(_calculate_atr_sync, stock_code)


def format_levels_oneline(levels: Optional[dict[str, Any]]) -> str:
    """1줄 포맷 (텔레그램용).

    예: "📍 진입 95,200 / 손절 92,000 (-3.4%) / 목표 101,700 (R:R 1:2)"
    """
    if not levels:
        return ""

    return (
        f"📍 진입 {levels['entry_market']:,.0f} "
        f"/ 손절 {levels['stop_loss']:,.0f} ({levels['stop_loss_pct']:+.1f}%) "
        f"/ 목표 {levels['target_1']:,.0f} (R:R 1:{levels['risk_reward']:.1f})"
    )


def format_levels_detail(levels: Optional[dict[str, Any]]) -> list[str]:
    """상세 포맷 (브리프 등 여러 줄).

    Returns: 줄 단위 리스트 (있을 때만)
    """
    if not levels:
        return []

    lines = [
        f"📍 진입가: 시장가 {levels['entry_market']:,.0f} / "
        f"조정 매수 {levels['entry_dip']:,.0f}",
        f"⛔ 손절가: {levels['stop_loss']:,.0f} ({levels['stop_loss_pct']:+.1f}%, "
        f"ATR×{STOP_LOSS_ATR_MULTIPLIER})",
        f"🎯 1차 목표: {levels['target_1']:,.0f} ({levels['target_1_pct']:+.1f}%, "
        f"R:R 1:{levels['risk_reward']:.1f})",
        f"🎯 2차 목표: {levels['target_2']:,.0f} ({levels['target_2_pct']:+.1f}%, "
        f"60일 고가)",
    ]
    return lines
```

### P1-7 통합 (P0-6 활용)

`stock_scoring_service.py` 의 `_calculate_for_stock()` 끝부분에 추가:

```python
# entry levels 함께 저장 (옵션 C++)
from app.services import entry_levels_service
levels = await entry_levels_service.get_entry_levels(stock_code)
if levels:
    return {
        "theme_score": ...,
        # ... 기존 키
        "entry_levels": levels,  # 신규
    }
```

`StockScore` 모델에 JSON 컬럼 추가:

```python
# app/models/stock_score.py
entry_levels: Mapped[dict] = mapped_column(JSON, default=dict, nullable=True)
```

### DB 마이그레이션

```bash
# SQLite
sqlite3 backend/data/investbrief.db <<'SQL'
ALTER TABLE stock_score ADD COLUMN entry_levels JSON DEFAULT '{}';
SQL

# PostgreSQL
psql "$DATABASE_URL" <<'SQL'
ALTER TABLE stock_score ADD COLUMN IF NOT EXISTS entry_levels JSONB DEFAULT '{}'::jsonb;
SQL
```

### 검증

```bash
cd backend
python3 << 'EOF'
import asyncio
from app.services import entry_levels_service

async def test():
    # 삼성전자 005930
    levels = await entry_levels_service.get_entry_levels("005930")
    if levels:
        print("=== 삼성전자 진입/손절/목표 ===")
        for k, v in levels.items():
            print(f"  {k}: {v}")
        print()
        print("1줄 포맷:", entry_levels_service.format_levels_oneline(levels))
        print()
        print("상세 포맷:")
        for line in entry_levels_service.format_levels_detail(levels):
            print(f"  {line}")
    else:
        print("계산 실패")

asyncio.run(test())
EOF
```

**예상 출력**:
```
current: 75000
atr: 1250.5
entry_market: 75000
entry_dip: 74250
stop_loss: 73125 (-2.5%)
target_1: 78750 (+5.0%, R:R 1:2.0)
target_2: 82000 (+9.3%, 60일 고가)

1줄: 📍 진입 75,000 / 손절 73,125 (-2.5%) / 목표 78,750 (R:R 1:2.0)
```

---

## 8. P0-7: 점수 해석 1줄 (신규)

### 목적

4차원 점수(`T95/F85/S90/C85`)만 보면 의미 불명. 룰 기반으로 1줄 해석 자동 생성.

⚠️ **솔직한 한계**:
- 단순 임계값 룰 → "왜 그 점수인지" 디테일은 부족
- Claude API 호출 X (비용 0, 즉시 생성)
- 운영 후 더 정교한 룰 필요 시 보강

### 변경 파일

- **신규**: `backend/app/services/score_explainer.py`
- **수정**: `backend/app/services/scheduler.py` (TOP 10 알림에 통합)
- **수정**: `backend/app/services/telegram_bot.py` (`/top-picks` 명령에 통합)

### 신규: `backend/app/services/score_explainer.py`

```python
"""점수 해석 1줄 — 룰 기반. Claude API 호출 X."""
from __future__ import annotations

from typing import Any


def explain_score_brief(score_data: dict[str, Any]) -> str:
    """4차원 점수를 1줄 해석으로.

    Args:
        score_data: {
            "theme_score": float,
            "fundamental_score": float,
            "flow_score": float,
            "chart_score": float,
            "matched_themes": str | None,
        }

    Returns: 해석 문자열 (예: "AI 반도체 강함 / 영업이익률 10%+ / 외인 매수 / 차트 양호")
    """
    parts: list[str] = []

    # 테마
    theme_score = score_data.get("theme_score", 0)
    themes = score_data.get("matched_themes", "")
    if theme_score >= 90:
        themes_short = themes.split(",")[0].strip() if themes else "테마"
        parts.append(f"{themes_short} 강세")
    elif theme_score >= 70:
        themes_short = themes.split(",")[0].strip() if themes else "테마"
        parts.append(f"{themes_short} 부상")
    elif theme_score >= 50:
        parts.append("테마 약함")

    # 펀더멘털
    fundamental = score_data.get("fundamental_score", 50)
    if fundamental >= 85:
        parts.append("영업이익률 10%+")
    elif fundamental >= 65:
        parts.append("흑자")
    elif fundamental >= 50:
        pass  # 중립은 표시 안 함
    elif fundamental <= 30:
        parts.append("⚠️ 적자")

    # 수급 (외인)
    flow = score_data.get("flow_score", 50)
    if flow >= 80:
        parts.append("외인 매수")
    elif flow >= 65:
        parts.append("외인 매수 약함")
    elif flow <= 30:
        parts.append("⚠️ 외인 매도")

    # 차트
    chart = score_data.get("chart_score", 50)
    if chart >= 75:
        parts.append("차트 양호")
    elif chart >= 60:
        pass  # 평이한 차트는 표시 안 함
    elif chart <= 30:
        parts.append("⚠️ 차트 약함")

    return " / ".join(parts) if parts else "특이사항 없음"


def explain_score_detail(score_data: dict[str, Any]) -> list[str]:
    """상세 해석 (여러 줄, 종목 페이지나 확장 뷰용).

    Returns: 줄 단위 리스트
    """
    lines = []

    theme_score = score_data.get("theme_score", 0)
    themes = score_data.get("matched_themes", "")
    if theme_score >= 70:
        lines.append(f"📈 테마: {theme_score:.0f}점 — {themes or '복수 테마 감지'}")
    elif theme_score > 0:
        lines.append(f"📈 테마: {theme_score:.0f}점 — 약한 매칭")

    fundamental = score_data.get("fundamental_score", 50)
    if fundamental >= 85:
        lines.append(f"💼 펀더: {fundamental:.0f}점 — 흑자 + 영업이익률 10%+ 우량")
    elif fundamental >= 65:
        lines.append(f"💼 펀더: {fundamental:.0f}점 — 흑자")
    elif fundamental <= 30:
        lines.append(f"💼 펀더: {fundamental:.0f}점 — ⚠️ 적자 (주의)")
    else:
        lines.append(f"💼 펀더: {fundamental:.0f}점 — 데이터 부족 (중립)")

    flow = score_data.get("flow_score", 50)
    if flow >= 80:
        lines.append(f"💰 수급: {flow:.0f}점 — 외인 강한 매수")
    elif flow >= 65:
        lines.append(f"💰 수급: {flow:.0f}점 — 외인 매수")
    elif flow <= 30:
        lines.append(f"💰 수급: {flow:.0f}점 — ⚠️ 외인 매도")
    else:
        lines.append(f"💰 수급: {flow:.0f}점 — 중립")

    chart = score_data.get("chart_score", 50)
    if chart >= 75:
        lines.append(f"📊 차트: {chart:.0f}점 — 추세 + 거래량 양호")
    elif chart <= 30:
        lines.append(f"📊 차트: {chart:.0f}점 — ⚠️ 추세 약함 또는 과열")
    else:
        lines.append(f"📊 차트: {chart:.0f}점 — 보통")

    return lines
```

### 스케줄러 TOP 10 알림 변경

`scheduler.py` 의 `_send_top_picks_alert()` 강화:

```python
async def _send_top_picks_alert(top_picks: list[dict]) -> None:
    from app.services import telegram_service, score_explainer, entry_levels_service
    escape = telegram_service.escape_html
    today = date.today()
    parts = [
        f"🎯 <b>오늘의 TOP 10 종목</b> ({today.strftime('%m/%d')})",
        "<i>4차원 점수: 테마+펀더+수급+차트</i>",
        "",
    ]
    for i, s in enumerate(top_picks, 1):
        # 종목명 + 점수
        parts.append(
            f"<b>{i}. {escape(s['stock_name'])}</b> ({s['stock_code']}) "
            f"— {s['composite_score']:.0f}/100"
        )
        # 4차원 점수 한 줄
        parts.append(
            f"   T{s['theme_score']:.0f}/F{s['fundamental_score']:.0f}/"
            f"S{s['flow_score']:.0f}/C{s['chart_score']:.0f}"
        )
        # P0-7: 해석 1줄
        explanation = score_explainer.explain_score_brief(s)
        if explanation and explanation != "특이사항 없음":
            parts.append(f"   💡 {escape(explanation)}")
        # P0-6: 진입/손절/목표 1줄
        levels = s.get("entry_levels")
        if levels:
            parts.append(f"   {escape(entry_levels_service.format_levels_oneline(levels))}")
        parts.append("")  # 종목 간 공백
    
    await telegram_service.send_long_text("\n".join(parts))
```

### `/top-picks` 명령도 동일하게 강화

`telegram_bot.py`:

```python
async def _handle_top_picks(_: str) -> str:
    """/top-picks — 오늘 TOP 10 종목 + 진입/손절/목표 + 해석"""
    from app.services import (
        stock_scoring_service, score_explainer, entry_levels_service, telegram_service
    )
    
    top_picks = await stock_scoring_service.get_top_picks(top_n=10)
    if not top_picks:
        return "오늘 계산된 종목 점수가 없습니다.\n매일 17:00 자동 계산됩니다."

    escape = telegram_service.escape_html
    parts = ["🎯 <b>오늘의 TOP 10 종목</b>", ""]
    for i, s in enumerate(top_picks, 1):
        parts.append(
            f"<b>{i}. {escape(s['stock_name'])}</b> ({s['stock_code']}) "
            f"— {s['composite_score']:.0f}/100"
        )
        parts.append(
            f"   T{s['theme_score']:.0f}/F{s['fundamental_score']:.0f}/"
            f"S{s['flow_score']:.0f}/C{s['chart_score']:.0f}"
        )
        explanation = score_explainer.explain_score_brief(s)
        if explanation and explanation != "특이사항 없음":
            parts.append(f"   💡 {escape(explanation)}")
        levels = s.get("entry_levels")
        if levels:
            parts.append(f"   {escape(entry_levels_service.format_levels_oneline(levels))}")
        parts.append("")
    
    return "\n".join(parts).rstrip()
```

`get_top_picks()` 의 반환 dict에 `entry_levels` 포함되어야 함:

```python
# stock_scoring_service.get_top_picks() 변경
return [
    {
        "stock_code": s.stock_code,
        "stock_name": s.stock_name,
        "composite_score": s.composite_score,
        "theme_score": s.theme_score,
        "fundamental_score": s.fundamental_score,
        "flow_score": s.flow_score,
        "chart_score": s.chart_score,
        "matched_themes": s.matched_themes,
        "entry_levels": s.entry_levels or {},  # 신규
    }
    for s in result.scalars().all()
]
```

### 검증

```bash
cd backend
python3 << 'EOF'
from app.services.score_explainer import explain_score_brief, explain_score_detail

# 시나리오 1: 우량 종목
s1 = {
    "theme_score": 95, "fundamental_score": 85,
    "flow_score": 90, "chart_score": 80,
    "matched_themes": "AI 반도체, HBM"
}
print("우량:", explain_score_brief(s1))
print("상세:")
for line in explain_score_detail(s1):
    print(f"  {line}")
print()

# 시나리오 2: 적자 종목 + 외인 매도
s2 = {
    "theme_score": 60, "fundamental_score": 20,
    "flow_score": 25, "chart_score": 40,
    "matched_themes": "바이오"
}
print("경계:", explain_score_brief(s2))
print("상세:")
for line in explain_score_detail(s2):
    print(f"  {line}")
EOF
```

**예상 출력**:
```
우량: AI 반도체 강세 / 영업이익률 10%+ / 외인 매수 / 차트 양호

경계: 바이오 약함 / ⚠️ 적자 / ⚠️ 외인 매도
```

---

## 9. P1-7: 종목 4차원 점수 + TOP 10 알림

### 목적

테마/펀더/수급/차트 4차원으로 종목 점수 매기고 매일 17:00 TOP 10 알림.

⚠️ **주의**: 가중치(T35% F20% S25% C20%)는 운영 데이터 없이는 추측값이지만, **P0-4 펀더 통합으로 점수 의미는 분명**. 운영 1-2개월 후 ThemeAlert.return_30d로 보정 권장.

### 변경 파일

- **신규**: `backend/app/models/stock_score.py`
- **신규**: `backend/app/services/stock_scoring_service.py`
- **수정**: `backend/app/services/scheduler.py`
- **수정**: `backend/app/services/telegram_bot.py`
- **수정**: `backend/app/models/__init__.py`
- **수정**: `backend/app/database.py`

### 모델: `backend/app/models/stock_score.py`

```python
"""종목별 4차원 종합 점수 — 일일 누적."""
import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import Date, DateTime, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

_KST = ZoneInfo("Asia/Seoul")


class StockScore(Base):
    """일별 종목 종합 점수 — 매일 17:00 계산."""
    __tablename__ = "stock_score"
    __table_args__ = (
        UniqueConstraint("score_date", "stock_code", name="uq_stock_score_date_code"),
        Index("ix_stock_score_date", "score_date"),
        Index("ix_stock_score_composite", "composite_score"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    score_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    stock_code: Mapped[str] = mapped_column(String(6), nullable=False)
    stock_name: Mapped[str] = mapped_column(String(100), nullable=False)

    # 4차원 점수 (각 0-100)
    theme_score: Mapped[float] = mapped_column(Float, default=0.0)
    fundamental_score: Mapped[float] = mapped_column(Float, default=0.0)
    flow_score: Mapped[float] = mapped_column(Float, default=0.0)
    chart_score: Mapped[float] = mapped_column(Float, default=0.0)
    composite_score: Mapped[float] = mapped_column(Float, default=0.0)

    matched_themes: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.datetime.now(_KST)
    )
```

### 신규: `backend/app/services/stock_scoring_service.py`

```python
"""종목별 4차원 종합 점수 계산.

⚠️ 가중치(WEIGHT_*)는 운영 데이터로 보정 필요.
운영 1-2개월 후 ThemeAlert.return_30d 데이터로 회귀분석 권장.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional

from sqlalchemy import select

from app.collectors import investor_flow_collector, price_collector
from app.database import async_session
from app.models.stock_score import StockScore
from app.models.theme import ThemeDetection

logger = logging.getLogger(__name__)


# ⚠️ 운영 데이터로 보정 예정 (초기 추측값)
WEIGHT_THEME = 0.35
WEIGHT_FUNDAMENTAL = 0.20
WEIGHT_FLOW = 0.25
WEIGHT_CHART = 0.20

CANDIDATE_LOOKBACK_DAYS = 14


async def calculate_daily_stock_scores(target_date: Optional[date] = None) -> int:
    today = target_date or date.today()
    candidates = await _get_candidate_stocks()
    logger.info("종목 점수 계산 시작: %d 종목", len(candidates))

    saved = 0
    for stock_code, stock_name in candidates:
        try:
            scores = await _calculate_for_stock(stock_code, stock_name, today)
            if scores is None:
                continue
            await _save_score(today, stock_code, stock_name, scores)
            saved += 1
        except Exception:
            logger.exception("종목 점수 계산 실패: %s", stock_code)

    logger.info("종목 점수 계산 완료: %d/%d", saved, len(candidates))
    return saved


async def _get_candidate_stocks() -> list[tuple[str, str]]:
    """최근 N일 테마 감지 + 관심종목."""
    from app.models.watchlist import Watchlist

    cutoff = datetime.now() - timedelta(days=CANDIDATE_LOOKBACK_DAYS)
    candidates: dict[str, str] = {}

    async with async_session() as session:
        result = await session.execute(
            select(ThemeDetection.stock_code, ThemeDetection.stock_name)
            .where(ThemeDetection.detected_at >= cutoff)
            .distinct()
        )
        for code, name in result.all():
            candidates[code] = name

        result = await session.execute(select(Watchlist))
        for w in result.scalars().all():
            candidates[w.stock_code] = w.stock_name

    return list(candidates.items())


async def _calculate_for_stock(
    stock_code: str, stock_name: str, score_date: date
) -> Optional[dict[str, Any]]:
    """단일 종목 4차원 점수.
    
    옵션 C+: 펀더멘털은 P0-4 활용 (흑/적자 + 영업이익률).
    """
    theme_score, matched_themes = await _calc_theme_score(stock_code, score_date)
    fundamental_score = await _calc_fundamental_score_v2(stock_code)  # P0-4 통합
    flow_score = await _calc_flow_score(stock_code, score_date)
    chart_score = await _calc_chart_score(stock_code)

    if all(s == 0 for s in [theme_score, flow_score, chart_score]):
        return None

    composite = (
        theme_score * WEIGHT_THEME
        + fundamental_score * WEIGHT_FUNDAMENTAL
        + flow_score * WEIGHT_FLOW
        + chart_score * WEIGHT_CHART
    )

    return {
        "theme_score": round(theme_score, 1),
        "fundamental_score": round(fundamental_score, 1),
        "flow_score": round(flow_score, 1),
        "chart_score": round(chart_score, 1),
        "composite_score": round(composite, 1),
        "matched_themes": ", ".join(matched_themes[:3]) if matched_themes else None,
    }


async def _calc_fundamental_score_v2(stock_code: str) -> float:
    """P0-4 통합 펀더 점수.
    
    corp_code 모르면 50점 중립.
    분기 재무 있으면 흑/적자 + 영업이익률 기반 20-95점.
    """
    try:
        from app.services import fundamental_simple_service
        fs = await fundamental_simple_service.get_or_fetch_fundamental(stock_code)
        return fundamental_simple_service.calculate_score(fs)
    except Exception:
        logger.exception("펀더 점수 계산 실패: %s", stock_code)
        return 50.0


async def _calc_theme_score(
    stock_code: str, score_date: date
) -> tuple[float, list[str]]:
    """최근 14일 감지된 테마 수 기반 점수.

    P1-5 ThemeScore 미적용 → 단순화: 감지된 테마 수 + 횟수.
    """
    cutoff = datetime.now() - timedelta(days=CANDIDATE_LOOKBACK_DAYS)
    async with async_session() as session:
        from app.models.theme import Theme
        from sqlalchemy import func

        result = await session.execute(
            select(
                ThemeDetection.theme_id,
                func.count(ThemeDetection.id).label("count"),
            )
            .where(ThemeDetection.stock_code == stock_code)
            .where(ThemeDetection.detected_at >= cutoff)
            .group_by(ThemeDetection.theme_id)
        )
        rows = result.all()
        if not rows:
            return 0.0, []

        # 테마 이름 조회
        theme_ids = [r[0] for r in rows]
        result = await session.execute(
            select(Theme.id, Theme.name).where(Theme.id.in_(theme_ids))
        )
        id_to_name = {r[0]: r[1] for r in result.all()}
        theme_names = [id_to_name.get(tid, "?") for tid in theme_ids]

        # 점수: 테마당 30점, 최대 100
        # 다중 테마 보너스: 2개 이상 시 +15, 3개 이상 +25
        base = min(100.0, len(rows) * 30)
        if len(rows) >= 3:
            base = min(100.0, base + 25)
        elif len(rows) >= 2:
            base = min(100.0, base + 15)
        return base, theme_names


async def _calc_flow_score(stock_code: str, score_date: date) -> float:
    """외인 매수 TOP 종목 여부 → 점수."""
    try:
        trade_date = investor_flow_collector.latest_trading_date()
        top_traders = await investor_flow_collector.get_top_foreign_traders(
            trade_date, limit_buy=50, limit_sell=50
        )
        for t in top_traders:
            if t["stock_code"] == stock_code:
                net = t["net_billion"]
                if net >= 100:
                    return 90.0
                elif net >= 50:
                    return 80.0
                elif net >= 10:
                    return 70.0
                elif net > 0:
                    return 60.0
                elif net > -10:
                    return 40.0
                else:
                    return 20.0
        return 50.0
    except Exception:
        return 50.0


async def _calc_chart_score(stock_code: str) -> float:
    """RSI, MA20, 거래량 종합."""
    def _sync() -> Optional[dict[str, float]]:
        start = date.today() - timedelta(days=120)
        df = price_collector.fetch_close_history(stock_code, start=start)
        if df is None or len(df) < 30:
            return None

        closes = df["Close"]
        current = float(closes.iloc[-1])

        # RSI
        delta = closes.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.rolling(14).mean().iloc[-1]
        avg_loss = loss.rolling(14).mean().iloc[-1]
        rsi = 100 - (100 / (1 + avg_gain / avg_loss)) if avg_loss > 0 else 100

        # MA20
        ma20 = float(closes.rolling(20).mean().iloc[-1])
        ma_gap = (current - ma20) / ma20 if ma20 > 0 else 0

        # 거래량
        volumes = df["Volume"]
        today_vol = float(volumes.iloc[-1])
        avg_vol_5 = float(volumes.iloc[-6:-1].mean()) if len(volumes) >= 6 else 0
        vol_ratio = today_vol / avg_vol_5 if avg_vol_5 > 0 else 1.0

        return {"rsi": float(rsi), "ma_gap": float(ma_gap), "vol_ratio": float(vol_ratio)}

    try:
        data = await asyncio.to_thread(_sync)
        if data is None:
            return 50.0

        score = 50.0
        rsi = data["rsi"]
        if 40 <= rsi <= 65:
            score += 25
        elif 30 <= rsi < 40 or 65 < rsi <= 75:
            score += 10
        elif rsi > 75:
            score -= 20
        elif rsi < 30:
            score += 5

        ma_gap = data["ma_gap"]
        if 0 <= ma_gap <= 0.10:
            score += 15
        elif ma_gap > 0.20:
            score -= 15
        elif -0.05 <= ma_gap < 0:
            score += 5

        vol = data["vol_ratio"]
        if 1.2 <= vol <= 3.0:
            score += 10
        elif vol > 5:
            score -= 10

        return max(0.0, min(100.0, score))
    except Exception:
        return 50.0


async def _save_score(
    score_date: date, stock_code: str, stock_name: str, scores: dict[str, Any]
) -> None:
    async with async_session() as session:
        existing = await session.execute(
            select(StockScore)
            .where(StockScore.score_date == score_date)
            .where(StockScore.stock_code == stock_code)
        )
        row = existing.scalar_one_or_none()
        if row:
            for k, v in scores.items():
                setattr(row, k, v)
        else:
            session.add(StockScore(
                score_date=score_date, stock_code=stock_code,
                stock_name=stock_name, **scores,
            ))
        await session.commit()


async def get_top_picks(
    score_date: Optional[date] = None, top_n: int = 10
) -> list[dict[str, Any]]:
    today = score_date or date.today()
    async with async_session() as session:
        result = await session.execute(
            select(StockScore)
            .where(StockScore.score_date == today)
            .order_by(StockScore.composite_score.desc())
            .limit(top_n)
        )
        return [
            {
                "stock_code": s.stock_code,
                "stock_name": s.stock_name,
                "composite_score": s.composite_score,
                "theme_score": s.theme_score,
                "fundamental_score": s.fundamental_score,
                "flow_score": s.flow_score,
                "chart_score": s.chart_score,
                "matched_themes": s.matched_themes,
            }
            for s in result.scalars().all()
        ]
```

### 스케줄러 등록: `backend/app/services/scheduler.py`

⚠️ **옵션 C++ 적용 시**: 아래 기본 버전 후 **P0-6/P0-7 섹션에서 `_send_top_picks_alert`를 강화 버전으로 덮어쓰기**. 본 섹션은 골격만:

```python
async def _calculate_stock_scores():
    """매일 17:00 종목 점수 + TOP 10 알림"""
    try:
        from app.services import stock_scoring_service
        
        saved = await stock_scoring_service.calculate_daily_stock_scores()
        logger.info("종목 점수: %d 종목", saved)

        top_picks = await stock_scoring_service.get_top_picks(top_n=10)
        if top_picks:
            await _send_top_picks_alert(top_picks)
    except Exception:
        logger.exception("종목 점수 계산 실패")


# 기본 버전 (옵션 C++에서 P0-7에 의해 강화 버전으로 교체됨)
async def _send_top_picks_alert(top_picks: list[dict]) -> None:
    """⚠️ 옵션 C++: P0-7 섹션의 강화 버전 사용 권장 (해석 + 진입가 포함)"""
    from app.services import telegram_service
    escape = telegram_service.escape_html
    today = date.today()
    parts = [
        f"🎯 <b>오늘의 TOP 10 종목</b> ({today.strftime('%m/%d')})",
        "<i>4차원 점수: 테마+펀더+수급+차트</i>",
        "",
    ]
    for i, s in enumerate(top_picks, 1):
        themes = f" | {escape(s['matched_themes'])}" if s.get('matched_themes') else ""
        parts.append(
            f"<b>{i}. {escape(s['stock_name'])}</b> ({s['stock_code']}) "
            f"— {s['composite_score']:.0f}/100"
        )
        parts.append(
            f"   T{s['theme_score']:.0f}/F{s['fundamental_score']:.0f}/"
            f"S{s['flow_score']:.0f}/C{s['chart_score']:.0f}{themes}"
        )
    await telegram_service.send_long_text("\n".join(parts))


# start_scheduler() 내부에 추가
scheduler.add_job(
    _calculate_stock_scores, "cron",
    day_of_week="mon-fri", hour=17, minute=0,
    id="daily_stock_scores", replace_existing=True,
    misfire_grace_time=3600,
)
```

### 텔레그램 명령: `backend/app/services/telegram_bot.py`

```python
async def _handle_top_picks(_: str) -> str:
    """/top-picks — 오늘 TOP 10 종목 즉시 조회"""
    from app.services import stock_scoring_service
    top_picks = await stock_scoring_service.get_top_picks(top_n=10)
    if not top_picks:
        return "오늘 계산된 종목 점수가 없습니다.\n매일 17:00 자동 계산됩니다."

    escape = telegram_service.escape_html
    parts = ["🎯 <b>오늘의 TOP 10 종목</b>", ""]
    for i, s in enumerate(top_picks, 1):
        parts.append(
            f"<b>{i}. {escape(s['stock_name'])}</b> ({s['stock_code']}) "
            f"— {s['composite_score']:.0f}/100"
        )
        parts.append(
            f"   T{s['theme_score']:.0f}/F{s['fundamental_score']:.0f}/"
            f"S{s['flow_score']:.0f}/C{s['chart_score']:.0f}"
        )
    return "\n".join(parts)


# COMMAND_HANDLERS dict에 등록
COMMAND_HANDLERS = {
    # ... 기존
    "/top-picks": _handle_top_picks,
}
```

### 모델 export 추가: `backend/app/models/__init__.py`

```python
from app.models.stock_score import StockScore

__all__ = [
    # ... 기존
    "StockScore",
]
```

### init_db() 에 추가: `backend/app/database.py`

```python
async def init_db():
    from app.models import (  # noqa: F401
        # ... 기존
        StockScore,
    )
    ...
```

### DB 마이그레이션

```bash
cd backend
python3 -c "
import asyncio
from app.database import init_db
asyncio.run(init_db())
print('✅ stock_score 테이블 생성')
"

# 확인
sqlite3 backend/data/investbrief.db ".tables" | tr ' ' '\n' | grep stock_score
```

### 검증

```bash
cd backend
python3 -c "
import asyncio
from app.services import stock_scoring_service

async def test():
    saved = await stock_scoring_service.calculate_daily_stock_scores()
    print(f'계산 완료: {saved} 종목')
    top = await stock_scoring_service.get_top_picks(top_n=5)
    for s in top:
        print(f'  {s[\"stock_name\"]} {s[\"composite_score\"]:.1f}')

asyncio.run(test())
"
```

---

## 10. 테마 v2.1: 테마 발굴 프롬프트 강화

### 목적

주간 테마 발굴(`/theme-discover`)의 출력을 4 항목 → 8 필수 + 4 선택으로 강화. 분석가 리포트 수준.

### 변경 파일

- **수정**: `backend/app/services/theme_discovery_service.py` (함수 1개 + 호출부)

### `_build_theme_discovery_prompt()` 전체 교체

```python
def _build_theme_discovery_prompt(
    days: int,
    news_titles: list[str],
    disclosure_titles: list[str],
    ai_summaries: list[str],
    events_text: str = "",  # 옵션 (P1-4 적용 환경에서만 활용)
) -> str:
    """테마 발굴용 Claude 프롬프트 (v2.1)."""
    news_section = "\n".join(news_titles[:300])
    disclosure_section = "\n".join(disclosure_titles[:100])
    summary_section = "\n\n".join(ai_summaries[:30])

    events_block = ""
    if events_text and events_text.strip():
        events_block = f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📅 향후 30일 예정 이벤트:
{events_text}

"""

    return f"""당신은 한국 주식 시장 테마 분석 전문가입니다.

다음은 최근 {days}일간 한국 증시 관련 데이터입니다.

이 데이터에서 **부상 중인 투자 테마를 3~4개** 발굴하고,
**깊이 우선** 원칙으로 분석가 리포트 수준의 분석을 제공하세요.
(테마 수보다 분석 깊이가 더 중요)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📰 뉴스 제목 (최근 {days}일):
{news_section}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 DART 공시 제목:
{disclosure_section}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🤖 일일 AI 요약:
{summary_section}

{events_block}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

다음 형식으로 답변하세요:

## 📈 부상 중인 테마 (3~4개)

### 1. [테마명]

**필수 항목** (모든 테마에 작성):
- **부상 근거**: 왜 이 테마가 주목받는지 (2~3줄)
- **핵심 키워드**: 해당 테마를 관통하는 키워드 3~5개 (쉼표 구분)
- **핵심 드라이버**: 정책 / 기술 / 수요 중 무엇이 추진력인지 (1줄)
- **밸류체인 위치**: 상류(소재/장비) / 중류(제조) / 하류(서비스/유통) 중 한국 강세
- **라이프 스테이지**: 초기 부상 / 가속 성장 / 성숙 / 조정 중 하나 + 1줄 근거
- **수혜 종목**: 뉴스/공시에 명시적으로 등장한 종목 (최대 5개)
- **깨질 시나리오**: 이 테마가 끝날 수 있는 리스크 (1~2줄)
- **모멘텀 강도**: 🔥🔥🔥 / 🔥🔥 / 🔥

**선택 항목** (입력 데이터에서 추출 가능한 경우만, 불확실하면 생략):
- **시장 규모 (TAM)**: 추정 규모 + 연 성장률
- **한국 노출도**: 글로벌 시장 대비 한국 점유율
- **과거 유사 사례**: 비슷한 흐름의 과거 테마
- **다음 카탈리스트**: 7~30일 내 예정 일정

## ⚠️ 주의 섹터 (1~2개)
- **섹터명**: 하방 압력 이유 (1줄) + 깨질/지속 시나리오 (1줄)

## 💡 한 줄 인사이트
이 {days}일간 시장을 관통하는 핵심 스토리를 한 줄로.

## 🔄 테마 간 관계 (선택)
상호 보강/반비례 관계 1~2쌍:
- "테마 A ↔ 테마 B: 관계 (1줄)"

---

**중요 규칙:**

1. **양보다 깊이**: 테마는 3~4개. 5개는 깊이가 떨어지므로 지양.
2. **선택 항목은 진짜 있을 때만**: 추측 금지. 불확실하면 항목 자체 생략. "데이터 부족" 표기 불필요.
3. **다음 카탈리스트**: 위 이벤트 섹션 우선 활용. 없으면 뉴스/공시에서. 둘 다 없으면 생략.
4. **수혜 종목**: 뉴스에 실제로 등장한 종목만.
5. **이미 누구나 아는 테마**(예: "반도체 수혜")는 제외. 새롭게 부상 중인 것 중심.
6. 서론/결론 없이 위 형식대로 바로 작성."""
```

### `discover_themes()` 호출부 수정

`max_tokens` 변경 + 이벤트 캘린더 옵션:

```python
# 이벤트 캘린더 조회 (P1-4 미적용 환경에서는 빈 문자열)
events_text = ""
try:
    from app.services import event_calendar_service
    events = await event_calendar_service.get_upcoming_events(days=30)
    if events:
        events_lines = []
        for e in events[:15]:
            events_lines.append(
                f"[{e.get('date', '?')}] {e.get('title', '?')} "
                f"({e.get('category', '?')})"
            )
        events_text = "\n".join(events_lines)
except ImportError:
    pass  # P1-4 미적용 — 정상
except Exception:
    logger.exception("이벤트 캘린더 조회 실패 (무시)")

# 프롬프트 빌드
prompt = _build_theme_discovery_prompt(
    days, news_titles, disclosure_titles, ai_summaries,
    events_text=events_text,
)

# max_tokens 2000 → 3500
response = await client.messages.create(
    model=settings.ai_model,
    max_tokens=3500,  # v2.1: 8 필수 + 4 선택 안전 출력
    messages=[{"role": "user", "content": prompt}],
)
```

### 검증 (시나리오 B: 빈 DB 대응)

```bash
cd backend
python3 << 'EOF'
import asyncio
from app.services.theme_discovery_service import _build_theme_discovery_prompt

# 가짜 입력으로 프롬프트 빌더만 테스트
prompt = _build_theme_discovery_prompt(
    days=30,
    news_titles=["[2026-05-12] 한미반도체 1Q 영업이익 3배 증가"],
    disclosure_titles=["[2026-05-12] 한미반도체: 단일판매·공급계약체결"],
    ai_summaries=["반도체 섹터 강세, AI 반도체 후공정 종목 부각"],
    events_text="[2026-05-22] 한미반도체 1Q 실적 발표",
)
print(f"프롬프트 길이: {len(prompt)} 문자, ~{len(prompt)//4} 토큰")
print(prompt[:1000])
EOF
```

---

## 11. 통합 검증 체크리스트

### 각 항목 적용 후 (개별)

**P0-1 AI 프롬프트**:
- [ ] 신규 모닝브리프가 5섹션 구조로 출력
- [ ] 기존 매일 아침 발송 정상 (장애 없음)
- [ ] 시장 위험 모드 1줄이 헤더 직후 표시 (P0-5 통합 후)

**P0-2 수급**:
- [ ] 텔레그램 수급 섹션에 외인/기관 net + 매수/매도 TOP 종목 표시
- [ ] DB에 `daily_briefs.investor_flow` 컬럼 존재
- [ ] pykrx 호출 실패 시 빈 dict로 안전 폴백

**P0-3 본문 추출**:
- [ ] theme_radar 로그에 candidate 수 증가 확인
- [ ] candidate가 30개 초과 시 자동 제한

**P0-4 펀더멘털 최소**:
- [ ] `fundamental_simple` + `stock_corp_map` 테이블 생성 확인
- [ ] DART 공시 발생 시 corp_code 자동 캐시 (`stock_corp_map` 증가)
- [ ] 삼성전자 등 대형주 dry-run 결과 정상 (흑자 + 영업이익률)
- [ ] corp_code 모르는 종목은 50점 중립 폴백

**P0-5 시장 위험 모드**:
- [ ] `daily_briefs.market_risk` 컬럼 생성 확인
- [ ] 정상/주의/위험 3단계 분류 정상 작동
- [ ] 모닝브리프 헤더에 1줄 표시
- [ ] AI 프롬프트의 시장 컨텍스트 섹션에 반영
- [ ] 외인 5일 흐름 조회 실패 시 시그널 스킵 (VIX/환율만 사용)

**P0-6 진입가/손절가/목표가**:
- [ ] `stock_score.entry_levels` 컬럼 생성 확인
- [ ] 삼성전자 dry-run 결과 정상 (ATR 양수, 진입/손절/목표 합리적 범위)
- [ ] 1줄 포맷 / 상세 포맷 둘 다 정상 출력
- [ ] R:R 비율 약 1:2 (3×ATR / 1.5×ATR)
- [ ] 종목 데이터 부족 시 None 반환 (계산 실패 무시)

**P0-7 점수 해석 1줄**:
- [ ] 우량 종목 시나리오: "테마 강세 / 영업이익률 10%+ / 외인 매수 / 차트 양호"
- [ ] 경계 종목 시나리오: "⚠️ 적자 / ⚠️ 외인 매도" 표시
- [ ] 중립 데이터: "특이사항 없음" 반환
- [ ] Claude API 호출 없음 (즉시 응답, 비용 0)

**P1-7 종목 점수** (P0-4/P0-6/P0-7 통합 후):
- [ ] 매일 17:00 (평일) TOP 10 알림 정상 발송
- [ ] `/top-picks` 명령 작동
- [ ] stock_score 테이블에 데이터 누적
- [ ] **펀더 점수가 실제로 차별화됨** (전 종목 50점 아님)
- [ ] **알림에 진입/손절/목표 1줄 포함** (P0-6 통합)
- [ ] **알림에 점수 해석 1줄 포함** (P0-7 통합)

**테마 v2.1**:
- [ ] `/theme-discover` 출력이 8 필수 + 4 선택 형식
- [ ] 테마 3~4개 추출
- [ ] 기존 파싱(`_extract_themes_from_analysis`) 정상 작동

### 운영 1주 후

- [ ] 매일 아침 브리프 정상 발송 (7일 연속)
- [ ] AI 토큰 사용량 이전 대비 폭증 안 했는지 확인
- [ ] 텔레그램 발송 실패율 < 1%
- [ ] DB 크기 증가율 정상 (1MB 이하/일 예상)
- [ ] stock_corp_map 캐시 누적 30개+ 도달 (DART 공시 활발 시)
- [ ] TOP 10 알림에 진입가/손절가가 모든 종목에 표시되는지 확인

### 운영 1개월 후

- [ ] P1-7 가중치 보정 검토 (ThemeAlert.return_30d 데이터 활용)
- [ ] P0-5 임계값 보정 검토 (false positive 빈도 확인)
- [ ] P0-6 ATR 배수 보정 검토 (실제 손절 도달율 분석)
- [ ] P0-7 해석 룰 보정 검토 (실제 종목 패턴과 일치도)
- [ ] 누락 종목 / 과잉 종목 패턴 파악
- [ ] 운영 데이터 기반 추가 항목 (P1-4 이벤트, P1-5 테마점수 등) 적용 여부 결정

---

## 12. 적용 순서 & 일정

### 권장 순서 (2주)

```
Day 1   사전 준비 (백업, pykrx 설치)
        P0-1 AI 프롬프트 적용
        검증

Day 2   P0-2 외인/기관 수급 적용
        DB 마이그레이션
        검증 (텔레그램 실전)

Day 3   P0-3 본문 추출 적용
        candidate 수 모니터링

Day 4   P0-4 펀더멘털 최소 적용
        DB 마이그레이션 (fundamental_simple + stock_corp_map)
        삼성전자 등 dry-run

Day 5   P0-5 시장 위험 모드 적용
        DB 마이그레이션 (market_risk 컬럼)
        시나리오 3개 dry-run (정상/주의/위험)
        모닝브리프 헤더 표시 확인

Day 6   P0-6 진입/손절/목표 적용 🆕
        DB 마이그레이션 (stock_score.entry_levels 컬럼)
        삼성전자 dry-run (ATR 양수, R:R 1:2)
        포맷 확인

Day 7   P0-7 점수 해석 1줄 적용 🆕
        룰 기반 (Claude API 호출 0)
        시나리오 dry-run (우량/경계/중립)

Day 8-9 P1-7 종목 4차원 점수 (P0-4/P0-6/P0-7 통합)
        DB 마이그레이션 + 스케줄러 등록
        17:00 첫 자동 실행 확인
        TOP 10 알림에 진입/손절/해석 포함 확인

Day 10  테마 v2.1 프롬프트 적용
        `/theme-discover` 테스트

Day 11-14 운영 모니터링
         AI 토큰 사용량 추이
         텔레그램 발송 정상 확인
         사용자 만족도 평가
```

### 한 번에 다 적용? 또는 단계별?

**권장**: **단계별** (Day 1, 2, 3, 4, 5, 6, 7, 8-9, 10 각각 commit)

이유:
- 문제 발생 시 어느 항목이 원인인지 식별 쉬움
- 운영 시작 전부터 실제 동작 확인하며 진행 가능
- 롤백 시 영향 범위 최소화

---

## 13. 롤백 가이드

### Phase 단위 (개별 commit)

```bash
git log --oneline -10
git revert <commit hash>
```

### DB 롤백

```bash
sqlite3 backend/data/investbrief.db <<'SQL'
DROP TABLE IF EXISTS stock_score;       -- entry_levels 컬럼 포함하여 통째 삭제
DROP TABLE IF EXISTS fundamental_simple;
DROP TABLE IF EXISTS stock_corp_map;
SQL
```

`daily_briefs.investor_flow`, `daily_briefs.market_risk` 컬럼은 SQLite에서 제거가 어려우므로 그대로 두는 게 안전 (NULL 허용).

### 긴급 폴백 (모닝브리프 중단)

```python
# brief_service.py 1줄 변경으로 즉시 폴백
# news_summary = await ai_summarizer.generate_expert_brief(...)
news_summary = await ai_summarizer.summarize_news(news_items)
```

---

## 14. 변경 이력

- **2026-05-13 (옵션 C)**: 최초 작성. v3.1의 ✅ 검증 항목 5개 추출.
- **2026-05-13 (옵션 C+)**: 전문가 재검토 후 2개 항목 추가.
  - **P0-4 신규**: 펀더멘털 최소 (흑/적자 + 영업이익률). 
    - corp_code는 DART 공시 응답에서 자연스럽게 캐시 (별도 다운로드 X)
    - 매출/영업이익/당기순이익만 조회 (PER/ROE는 P2-7로 보류)
    - 14일 freshness 캐시
  - **P0-5 신규**: 시장 위험 모드 단순 진단 (3변수).
    - VIX, 환율 5일 변동, 외인 5일 연속 매도
    - 3단계 분류: 정상/주의/위험
    - 자산배분 권고 같은 위험한 조언 없음 (단순 표시)
  - **P1-7 변경**: 펀더멘털 점수 50점 중립 → P0-4 활용으로 20-95점 차별화
  - **작업 분량**: 옵션 C(5-7일) → 옵션 C+(6-8일, +1.5일)
  - **기대 점수**: 정보 78~80 / 종목 73~76 / 실전 어시스턴스 65~70
- **2026-05-13 (옵션 C++)**: 실전 매매 어시스턴스 강화 2개 추가.
  - **P0-6 신규**: 진입가/손절가/목표가 (ATR 기반).
    - 표준 ATR 14일 + 1.5×ATR 손절 + 3×ATR 목표 (R:R 1:2)
    - 60일 고가를 2차 목표로
    - 종목 데이터 부족 시 None 폴백
    - 검증된 `fetch_close_history()` Open/High/Low/Close/Volume 활용
  - **P0-7 신규**: 점수 해석 1줄 (룰 기반).
    - Claude API 호출 0 (비용 0)
    - 4차원 점수 → 자연어 해석 ("AI 반도체 강세 / 영업이익률 10%+ / 외인 매수")
    - 적자/외인매도/차트약함 등 경고 자동 표시
  - **P1-7 변경**: TOP 10 알림에 entry_levels + score_explanation 통합
  - **작업 분량**: 옵션 C+(6-8일) → 옵션 C++(8-9일, +1.5일)
  - **기대 점수**: 정보 78~80 / 종목 75~78 / 실전 어시스턴스 **65~70**

---

**끝.**
