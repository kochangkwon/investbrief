# InvestBrief — 통합 개선 지시서

## 개요

InvestBrief 시스템의 버그 수정 + 고도화 작업 10건.
우선순위 순서로 작성.

---

## 수정 1: 관심종목 뉴스 오매칭 (🔴 버그)

### 문제
네이버 뉴스 검색 API에 종목명을 그대로 넣어 무관한 기사가 표시됨.
(삼영무역 관심종목에 보원케미칼 기사 노출)

### 수정 파일 2개

**파일 A: `backend/app/collectors/news_collector.py` 55행**

현재:
```python
params = {"query": keyword, "display": 5, "sort": "date"}
```

수정:
```python
params = {"query": f'"{keyword}"', "display": 10, "sort": "date"}
```

**파일 B: `backend/app/services/watchlist_service.py` 101~104행**

현재:
```python
# 2. 뉴스 (네이버 검색 — 상위 2건)
try:
    news = await news_collector._fetch_naver_news(w.stock_name)
    check["news"] = [n["title"] for n in news[:2]]
except Exception:
    check["news"] = []
```

수정:
```python
# 2. 뉴스 (네이버 검색 — 종목명 포함 기사만 필터)
try:
    news = await news_collector._fetch_naver_news(w.stock_name)
    filtered = [n for n in news if w.stock_name in n["title"]]
    if not filtered:
        filtered = [n for n in news if w.stock_code in n["title"]]
    check["news"] = [n["title"] for n in filtered[:2]]
except Exception:
    check["news"] = []
```

**파일 C: `backend/app/services/daily_report_service.py` 97~100행 (동일 문제)**

현재:
```python
# 뉴스
try:
    news = await news_collector._fetch_naver_news(w.stock_name)
    news_titles = [n["title"] for n in news[:2]]
except Exception:
    news_titles = []
```

수정:
```python
# 뉴스 (종목명 포함 기사만 필터)
try:
    news = await news_collector._fetch_naver_news(w.stock_name)
    filtered = [n for n in news if w.stock_name in n["title"]]
    if not filtered:
        filtered = [n for n in news if w.stock_code in n["title"]]
    news_titles = [n["title"] for n in filtered[:2]]
except Exception:
    news_titles = []
```

---

## 수정 2: 스케줄러 주말/공휴일 미처리 (🔴 버그)

### 문제
모닝브리프와 점심 체크가 주말에도 실행됨. 시장 데이터 없어 의미 없는 브리프 생성.

### 수정 파일

**파일: `backend/app/services/scheduler.py`**

상단에 헬퍼 함수 추가 (import 아래):

```python
from datetime import date, timedelta
import calendar

def _is_weekday() -> bool:
    """평일 여부 (토/일 제외)"""
    return date.today().weekday() < 5
```

`_generate_and_send` 함수 시작 부분에 추가:

```python
async def _generate_and_send():
    """매일 아침 브리프 생성 + 텔레그램 발송"""
    if not _is_weekday():
        logger.info("스케줄: 주말 — 모닝브리프 스킵")
        return
    # ... 기존 코드
```

`_midday_watchlist_check` 함수 시작 부분에 추가:

```python
async def _midday_watchlist_check():
    """12:00 점심 — 관심종목 변동 알림"""
    if not _is_weekday():
        logger.info("스케줄: 주말 — 점심 체크 스킵")
        return
    # ... 기존 코드
```

---

## 수정 3: 데이터 수집 병렬화 (🟡 고도화)

### 문제
브리프 생성 시 4개 데이터 소스를 순차 수집. 전체 시간이 합산됨.

### 수정 파일

**파일: `backend/app/services/brief_service.py`**
위치: `generate_daily_brief` 함수 내부

현재:
```python
global_market = await _safe_collect("global_market", market_collector.get_global_summary(), {})
domestic_market = await _safe_collect("domestic_market", stock_collector.get_domestic_summary(), {})
news_items = await _safe_collect("news", news_collector.get_today_news(limit=20), [])
dart_items = await _safe_collect("dart", dart_collector.get_today_disclosures(), [])
```

수정:
```python
import asyncio

global_market, domestic_market, news_items, dart_items = await asyncio.gather(
    _safe_collect("global_market", market_collector.get_global_summary(), {}),
    _safe_collect("domestic_market", stock_collector.get_domestic_summary(), {}),
    _safe_collect("news", news_collector.get_today_news(limit=20), []),
    _safe_collect("dart", dart_collector.get_today_disclosures(), []),
)
```

---

## 수정 4: 관심종목 시세 조회 병렬화 (🟡 고도화)

### 문제
관심종목 체크 시 FDR 시세 조회가 종목별 순차 실행. 10종목이면 10배 느림.

### 수정 파일

**파일: `backend/app/services/watchlist_service.py`**
위치: `check_watchlist` 함수 내부

현재 (for 루프 내 순차 호출):
```python
for w in items:
    # ...
    price = await _get_stock_price(w.stock_code)
```

수정 — for 루프 전에 일괄 조회:
```python
async def check_watchlist(session: AsyncSession) -> list[dict[str, Any]]:
    """관심종목별 오늘의 변동사항 체크"""
    items = await list_all(session)
    if not items:
        return []

    # DART 공시 한 번만 조회
    all_disclosures = await dart_collector.get_today_disclosures()

    # ★ 시세 일괄 병렬 조회
    import asyncio
    price_results = await asyncio.gather(
        *[_get_stock_price(w.stock_code) for w in items],
        return_exceptions=True,
    )
    price_map: dict[str, dict | None] = {}
    for w, result in zip(items, price_results):
        price_map[w.stock_code] = result if not isinstance(result, Exception) else None

    results: list[dict[str, Any]] = []
    for w in items:
        check: dict[str, Any] = {
            "stock_code": w.stock_code,
            "stock_name": w.stock_name,
        }

        # 1. 주가 등락 (이미 조회 완료)
        price = price_map.get(w.stock_code)
        check["price"] = price if price else None

        # 2. 뉴스 (이하 기존 코드 동일)
        # ...
```

---

## 수정 5: 텔레그램 HTML 특수문자 이스케이프 (🔴 버그)

### 문제
뉴스 제목에 `<`, `>`, `&` 같은 HTML 특수문자가 있으면 텔레그램 파싱 실패.

### 수정 파일

**파일: `backend/app/services/telegram_service.py`**
상단 import 추가:

```python
import html
```

`_format_market` 함수에서 label 이스케이프:

```python
def _format_market(data: dict[str, Any], title: str) -> str:
    if not data:
        return ""
    lines = [f"<b>{html.escape(title)}</b>"]
    for v in data.values():
        sign = "+" if v["change_pct"] > 0 else ""
        emoji = "🔴" if v["change_pct"] > 0 else "🔵" if v["change_pct"] < 0 else "⚪"
        lines.append(f"  {emoji} {html.escape(v['label'])}: {v['close']:,.2f} ({sign}{v['change_pct']:.2f}%)")
    return "\n".join(lines)
```

`format_brief` 함수에서 뉴스 요약/공시 제목 이스케이프:

```python
# AI 뉴스 요약
parts.append("<b>📰 AI 뉴스 브리핑</b>")
parts.append(html.escape(brief.news_summary))

# DART 공시
for d in important[:10]:
    parts.append(f"  {d['importance']} {html.escape(d['corp_name'])}: {html.escape(d['title'])}")

# 관심종목
for w in watchlist:
    parts.append(f"  • {html.escape(w.get('stock_name', ''))}: {html.escape(w.get('summary', ''))}")
```

**파일: `backend/app/services/daily_report_service.py`**
상단 import 추가:

```python
import html
```

`generate_daily_report` 함수에서 종목명 이스케이프:

```python
lines.append(f"<b>{html.escape(w.stock_name)}</b> ({w.stock_code})")
```

---

## 수정 6: /watch 종목코드 자동 검색 (🟡 고도화)

### 문제
`/watch 삼성전자` 입력 시 "종목코드도 함께 입력해주세요" 반환.
`stock_search.py`가 있는데 활용하지 않음.

### 수정 파일

**파일: `backend/app/services/telegram_bot.py`**
위치: `_handle_watch` 함수

현재:
```python
async def _handle_watch(args: str) -> str:
    if not args.strip():
        return "사용법: /watch 종목명 종목코드\n예) /watch 삼성전자 005930"

    parts = args.strip().split()
    if len(parts) == 1:
        return f"종목코드도 함께 입력해주세요.\n예) /watch {parts[0]} 005930"
    # ...
```

수정:
```python
async def _handle_watch(args: str) -> str:
    if not args.strip():
        return "사용법: /watch 종목명\n예) /watch 삼성전자"

    parts = args.strip().split()
    stock_name = parts[0]
    stock_code = parts[1] if len(parts) > 1 else None

    # 종목코드 미입력 시 자동 검색
    if not stock_code:
        from app.collectors import stock_search
        results = await stock_search.search_stocks(stock_name, limit=1)
        if not results:
            return f"⚠️ '{stock_name}' 종목을 찾을 수 없습니다.\n종목코드를 직접 입력해주세요.\n예) /watch {stock_name} 005930"
        stock_code = results[0]["stock_code"]
        stock_name = results[0]["stock_name"]

    if not stock_code.isdigit() or len(stock_code) != 6:
        return f"종목코드는 6자리 숫자입니다.\n예) /watch {stock_name} 005930"

    try:
        async with async_session() as session:
            await watchlist_service.add(session, stock_code, stock_name)
        return f"✅ 관심종목 추가: {stock_name} ({stock_code})"
    except Exception:
        return f"⚠️ 이미 등록된 종목이거나 추가에 실패했습니다."
```

---

## 수정 7: AI 요약 품질 개선 — 뉴스 본문 추가 (🟡 고도화)

### 문제
뉴스 제목만 Claude에 보내고 있어 AI 요약 품질이 낮음.

### 수정 파일

**파일: `backend/app/collectors/news_collector.py`**

`_fetch_naver_news` 함수에서 description(요약문) 추가 수집:

현재:
```python
for item in data.get("items", []):
    title = item["title"].replace("<b>", "").replace("</b>", "")
    items.append({
        "title": title,
        "link": item["originallink"],
        "source": "네이버",
        "published": item.get("pubDate", ""),
    })
```

수정:
```python
import re

for item in data.get("items", []):
    title = item["title"].replace("<b>", "").replace("</b>", "")
    desc = re.sub(r"<[^>]+>", "", item.get("description", ""))  # HTML 태그 제거
    items.append({
        "title": title,
        "description": desc[:200],  # 요약문 200자 제한
        "link": item["originallink"],
        "source": "네이버",
        "published": item.get("pubDate", ""),
    })
```

**파일: `backend/app/services/ai_summarizer.py`**
위치: `summarize_news` 함수

현재:
```python
titles = "\n".join(
    f"- {n['title']} ({n.get('source', '')})" for n in news_items[:20]
)
```

수정:
```python
lines = []
for n in news_items[:15]:
    line = f"- {n['title']} ({n.get('source', '')})"
    desc = n.get("description", "")
    if desc:
        line += f"\n  요약: {desc}"
    lines.append(line)
titles = "\n".join(lines)
```

---

## 수정 8: DART 공시 관심종목 매칭 개선 (🟡 고도화)

### 문제
DART API 응답에서 `stock_code`가 빈 문자열인 경우가 많아 관심종목 공시가 누락됨.

### 수정 파일

**파일: `backend/app/services/watchlist_service.py`**
위치: `check_watchlist` 함수 110행

현재:
```python
# 3. DART 공시
matched = [d for d in all_disclosures if d.get("stock_code") == w.stock_code]
```

수정:
```python
# 3. DART 공시 (stock_code 또는 corp_name 매칭)
matched = [
    d for d in all_disclosures
    if d.get("stock_code") == w.stock_code
    or (w.stock_name and w.stock_name in d.get("corp_name", ""))
]
```

**파일: `backend/app/services/daily_report_service.py`**
위치: `generate_daily_report` 함수 내 공시 매칭 부분

현재:
```python
matched_disc = [d for d in all_disclosures if d.get("stock_code") == w.stock_code]
```

수정:
```python
matched_disc = [
    d for d in all_disclosures
    if d.get("stock_code") == w.stock_code
    or (w.stock_name and w.stock_name in d.get("corp_name", ""))
]
```

---

## 수정 9: 브리프 중복 발송 방지 (🟡 고도화)

### 문제
서버 재시작 시 기존 브리프를 다시 텔레그램으로 발송함.

### 수정 파일

**파일: `backend/app/models/brief.py`**

필드 추가:
```python
class DailyBrief(Base):
    __tablename__ = "daily_briefs"

    # ... 기존 필드 유지
    sent_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime, nullable=True, default=None
    )
```

**파일: `backend/app/services/scheduler.py`**
위치: `_generate_and_send` 함수

현재:
```python
existing = await brief_service.get_brief_by_date(session, date.today())
if existing:
    logger.info("스케줄: 오늘 브리프 이미 존재, 발송만 진행")
    await telegram_service.send_brief(existing)
    return
```

수정:
```python
existing = await brief_service.get_brief_by_date(session, date.today())
if existing:
    if existing.sent_at:
        logger.info("스케줄: 오늘 브리프 이미 발송됨, 스킵")
        return
    logger.info("스케줄: 오늘 브리프 존재, 미발송 → 발송 진행")
    await telegram_service.send_brief(existing)
    existing.sent_at = datetime.now()
    await session.commit()
    return
```

**파일: `backend/app/services/brief_service.py`**
위치: `generate_daily_brief` 함수 끝부분

DB 저장 후 `sent_at`은 None으로 둠 (발송은 스케줄러에서 처리):
```python
# 5. DB 저장 (sent_at은 None — 스케줄러에서 발송 후 업데이트)
session.add(brief)
await session.commit()
```

---

## 수정 10: 에러 텔레그램 알림 통일 (🟡 고도화)

### 문제
점심 체크와 일일 리포트는 실패 시 텔레그램 알림 없이 로그만 남김.

### 수정 파일

**파일: `backend/app/services/scheduler.py`**

`_midday_watchlist_check` except 블록:

현재:
```python
except Exception:
    logger.exception("스케줄: 점심 체크 실패")
```

수정:
```python
except Exception:
    logger.exception("스케줄: 점심 체크 실패")
    await telegram_service.send_text("⚠️ 점심 관심종목 체크 중 오류가 발생했습니다.")
```

`_daily_report` except 블록:

현재:
```python
except Exception:
    logger.exception("스케줄: 일일 리포트 실패")
```

수정:
```python
except Exception:
    logger.exception("스케줄: 일일 리포트 실패")
    await telegram_service.send_text("⚠️ 일일 리포트 생성 중 오류가 발생했습니다.")
```

---

## 구현 순서

| 순위 | 항목 | 난이도 | 영향 |
|------|------|--------|------|
| 1 | 수정 1: 뉴스 오매칭 | 낮음 | 3개 파일 수정 |
| 2 | 수정 2: 주말 스케줄러 | 낮음 | 1개 파일 수정 |
| 3 | 수정 5: HTML 이스케이프 | 낮음 | 2개 파일 수정 |
| 4 | 수정 10: 에러 알림 통일 | 낮음 | 1개 파일 수정 |
| 5 | 수정 3: 브리프 병렬화 | 낮음 | 1개 파일 수정 |
| 6 | 수정 4: 시세 병렬화 | 중간 | 1개 파일 리팩토링 |
| 7 | 수정 6: /watch 자동 검색 | 중간 | 1개 파일 수정 |
| 8 | 수정 8: DART 매칭 개선 | 낮음 | 2개 파일 수정 |
| 9 | 수정 7: AI 요약 품질 | 중간 | 2개 파일 수정 |
| 10 | 수정 9: 중복 발송 방지 | 중간 | 3개 파일 수정 + DB 마이그레이션 |

---

## 주의사항

- 수정 9(중복 발송 방지)는 DB 스키마 변경이 포함되므로 `sent_at` 컬럼 추가 후 DB 재생성 또는 마이그레이션 필요
- 수정 7(AI 요약)은 Claude API 토큰 사용량이 증가할 수 있음. `ai_max_tokens`을 1000→1500으로 조정 권장
- 수정 1과 수정 8에서 `daily_report_service.py`도 같이 수정해야 함 (동일 로직이 2곳에 있음)
- 코드 변경 전 반드시 현재 코드를 확인하고 Ko~님에게 보고 후 승인받을 것
