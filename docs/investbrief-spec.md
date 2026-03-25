# InvestBrief — AI 투자 모닝브리프 시스템

> **목적**: 매일 아침 투자자가 체크하는 정보를 AI가 모아서 요약
> **사용자**: 본인용 먼저, 반응 보고 확장
> **핵심 가치**: 네이버금융 + DART + 경제뉴스 + 해외시장을 하나로

---

## 1. 프로젝트 구조

```
investbrief/
├── backend/
│   ├── app/
│   │   ├── main.py                   # FastAPI 앱 + lifespan
│   │   ├── config.py                 # 환경 설정
│   │   ├── database.py               # SQLite (investbrief.db)
│   │   │
│   │   ├── collectors/               # 데이터 수집
│   │   │   ├── market_collector.py    # 해외지수/환율/유가/금 (yfinance)
│   │   │   ├── news_collector.py      # 경제뉴스 RSS + 네이버 뉴스
│   │   │   ├── dart_collector.py      # DART 주요 공시
│   │   │   └── stock_collector.py     # 국내 시장 요약 (FDR/네이버)
│   │   │
│   │   ├── services/
│   │   │   ├── brief_service.py       # 브리프 생성 오케스트레이터
│   │   │   ├── ai_summarizer.py       # Claude API 뉴스 요약
│   │   │   ├── watchlist_service.py   # 관심종목 관리
│   │   │   ├── telegram_service.py    # 텔레그램 봇 (발송 + 명령어)
│   │   │   └── scheduler.py           # APScheduler (07:00 브리프 등)
│   │   │
│   │   ├── models/
│   │   │   ├── brief.py               # DailyBrief 모델
│   │   │   ├── watchlist.py           # Watchlist 모델
│   │   │   └── news.py                # NewsItem 모델
│   │   │
│   │   └── api/
│   │       ├── brief.py               # GET /api/brief/today
│   │       ├── watchlist.py           # CRUD /api/watchlist
│   │       └── health.py              # GET /api/health
│   │
│   ├── requirements.txt
│   └── .env
│
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── page.tsx               # 오늘의 브리프 (메인)
│   │   │   ├── archive/page.tsx       # 과거 브리프
│   │   │   ├── watchlist/page.tsx      # 관심종목 관리
│   │   │   └── layout.tsx
│   │   └── components/
│   │       ├── BriefCard.tsx           # 브리프 섹션 카드
│   │       ├── MarketOverview.tsx      # 글로벌/국내 시장 요약
│   │       ├── NewsSection.tsx         # 뉴스 요약 리스트
│   │       ├── DisclosureList.tsx      # 공시 타임라인
│   │       └── WatchlistCheck.tsx      # 관심종목 체크
│   ├── package.json
│   └── next.config.ts
│
└── CLAUDE.md                          # Claude Code 개발 규칙
```

---

## 2. 기술 스택

```
Backend:  Python 3.11 + FastAPI + SQLAlchemy 2.0 + APScheduler
Frontend: Next.js 15 (App Router) + TypeScript + Tailwind CSS 4 + Shadcn UI
AI:       Claude API (claude-sonnet-4-20250514) — 뉴스 요약
Bot:      Telegram Bot API
DB:       SQLite (investbrief.db)
Data:     yfinance, feedparser (RSS), DART OpenAPI, 네이버 검색 API
```

---

## 3. 데이터 소스 상세

### 3-1. 해외 시장 (market_collector.py)

```python
# yfinance 라이브러리 사용 (무료, API 키 불필요)
TICKERS = {
    "sp500": "^GSPC",        # S&P 500
    "nasdaq": "^IXIC",       # 나스닥
    "dow": "^DJI",           # 다우존스
    "nikkei": "^N225",       # 니케이 225
    "shanghai": "000001.SS", # 상해종합
    "vix": "^VIX",           # 공포지수
    "usdkrw": "KRW=X",      # 원달러 환율
    "wti": "CL=F",           # WTI 유가
    "gold": "GC=F",          # 금 선물
    "us10y": "^TNX",         # 미국 10년물 금리
}

# 수집 항목: 종가, 전일비, 등락률
```

### 3-2. 경제 뉴스 (news_collector.py)

```python
# RSS 피드 (무료)
RSS_FEEDS = {
    "한경": "https://www.hankyung.com/feed/economy",
    "매경": "https://www.mk.co.kr/rss/30000001/",
    "서울경제": "https://www.sedaily.com/RSS/Economy",
    "연합뉴스": "https://www.yna.co.kr/rss/economy.xml",
}

# 네이버 뉴스 검색 API (기존 StockAI 키 재사용)
# 검색어: "증시", "코스피", "금리", "환율"
```

### 3-3. DART 공시 (dart_collector.py)

```python
# DART OpenAPI (기존 StockAI 키 재사용)
# 당일 주요 공시 수집
# 필터: 관심종목 + 시총 상위 종목
#
# 중요 공시 분류:
#   🔴 위험: 유상증자, CB발행, 감자, 상장폐지
#   🟡 주의: 최대주주변경, 소송, 영업정지
#   🟢 호재: 자사주매입, 배당결정, 수주공시
#   ⚪ 정보: 실적발표, IR, 정기공시
```

### 3-4. 국내 시장 (stock_collector.py)

```python
# FinanceDataReader (무료)
# 코스피/코스닥 종가, 등락률
# 외국인/기관 순매수 상위 (네이버 금융 크롤링)
# 거래대금 상위 종목
```

---

## 4. 핵심 기능 상세

### 4-1. 모닝 브리프 생성 (brief_service.py)

매일 07:00 실행되는 메인 로직:

```python
class BriefService:
    async def generate_daily_brief(self) -> DailyBrief:
        """매일 아침 브리프 생성 파이프라인"""

        # 1. 데이터 수집 (병렬 실행)
        global_market = await market_collector.get_global_summary()
        domestic_market = await stock_collector.get_domestic_summary()
        news_items = await news_collector.get_today_news(limit=20)
        dart_items = await dart_collector.get_today_disclosures()
        watchlist_data = await watchlist_service.check_watchlist()

        # 2. AI 요약 (Claude API)
        ai_summary = await ai_summarizer.summarize_news(news_items)

        # 3. 브리프 조립
        brief = DailyBrief(
            date=date.today(),
            global_market=global_market,
            domestic_market=domestic_market,
            news_summary=ai_summary,       # AI가 20개 뉴스 → 3~5줄 요약
            disclosures=dart_items,
            watchlist=watchlist_data,
            created_at=datetime.now(),
        )

        # 4. DB 저장
        await self._save_brief(brief)

        # 5. 텔레그램 발송
        await telegram_service.send_brief(brief)

        return brief
```

### 4-2. AI 뉴스 요약 (ai_summarizer.py)

```python
class AISummarizer:
    async def summarize_news(self, news_items: list[dict]) -> str:
        """뉴스 20건을 Claude API로 3~5줄 핵심 요약"""

        titles = "\n".join([
            f"- {n['title']} ({n['source']})"
            for n in news_items[:20]
        ])

        prompt = f"""아래는 오늘의 경제/증시 뉴스 제목입니다.
투자자가 아침에 빠르게 파악할 수 있도록
가장 중요한 3~5개 이슈를 한국어로 요약해주세요.

각 이슈는 한 줄로, 투자에 미치는 영향을 간단히 덧붙여주세요.
불필요한 서론 없이 바로 본론만 작성하세요.

뉴스 제목:
{titles}"""

        response = await self._call_claude(prompt)
        return response
```

### 4-3. 텔레그램 봇 (telegram_service.py)

```python
# 발송 기능
async def send_brief(self, brief: DailyBrief):
    """브리프를 텔레그램 메시지로 포맷팅해서 발송"""
    msg = self._format_brief(brief)
    await self._send_message(msg)

# 명령어 처리 (webhook 또는 polling)
COMMANDS = {
    "/today":     "오늘 브리프 다시 보기",
    "/watch":     "관심종목 추가 (/watch 삼영무역 또는 /watch 002810)",
    "/unwatch":   "관심종목 제거",
    "/list":      "관심종목 목록",
    "/news":      "특정 종목 뉴스 (/news 삼성전자)",
    "/dart":      "특정 종목 공시 (/dart 005930)",
}
```

### 4-4. 관심종목 관리 (watchlist_service.py)

```python
class WatchlistService:
    async def add(self, stock_code: str, stock_name: str):
        """관심종목 추가"""

    async def remove(self, stock_code: str):
        """관심종목 제거"""

    async def list_all(self) -> list[Watchlist]:
        """전체 관심종목 조회"""

    async def check_watchlist(self) -> list[dict]:
        """관심종목별 오늘의 변동사항 체크"""
        # 각 종목에 대해:
        # - 뉴스 유무 (있으면 제목 1~2개)
        # - DART 공시 유무
        # - 외국인/기관 수급 변화
        # - 전일 종가 대비 등락
```

---

## 5. DB 모델

```python
# models/brief.py
class DailyBrief(Base):
    __tablename__ = "daily_briefs"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    global_market: Mapped[dict] = mapped_column(JSON)     # 해외시장 데이터
    domestic_market: Mapped[dict] = mapped_column(JSON)   # 국내시장 데이터
    news_summary: Mapped[str] = mapped_column(Text)       # AI 요약
    news_raw: Mapped[list] = mapped_column(JSON)          # 원본 뉴스 목록
    disclosures: Mapped[list] = mapped_column(JSON)       # DART 공시
    watchlist_check: Mapped[list] = mapped_column(JSON)   # 관심종목 체크
    created_at: Mapped[datetime] = mapped_column(DateTime)

# models/watchlist.py
class Watchlist(Base):
    __tablename__ = "watchlist"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(6), unique=True)
    stock_name: Mapped[str] = mapped_column(String(100))
    memo: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
```

---

## 6. API 엔드포인트

```
GET  /api/health                    # 서버 상태
GET  /api/brief/today               # 오늘 브리프
GET  /api/brief/{date}              # 특정일 브리프 (YYYY-MM-DD)
GET  /api/brief/list?days=7         # 최근 N일 브리프 목록
GET  /api/watchlist                 # 관심종목 목록
POST /api/watchlist                 # 관심종목 추가 {stock_code, stock_name}
DELETE /api/watchlist/{stock_code}  # 관심종목 삭제
GET  /api/news/{stock_code}         # 종목별 뉴스
GET  /api/dart/{stock_code}         # 종목별 공시
POST /api/brief/generate            # 수동 브리프 생성 (테스트용)
```

---

## 7. 프론트엔드 페이지

### 7-1. 메인 — 오늘의 브리프 (/)

```
┌─────────────────────────────────────────┐
│ ☀️ 오늘의 투자 브리프 (2026-03-25 화)     │
├─────────────────────────────────────────┤
│ 🌍 글로벌 시장                            │
│ ┌──────┬──────┬──────┬──────┬──────┐    │
│ │S&P500│나스닥│다우  │니케이│상해  │    │
│ │+0.8% │+1.2% │+0.3% │-0.3%│+0.5% │    │
│ └──────┴──────┴──────┴──────┴──────┘    │
│ 원/달러 1,436원 | WTI $68.5 | 금 $2,180 │
├─────────────────────────────────────────┤
│ 📊 국내 시장 (어제)                       │
│ 코스피 2,890 (+1.1%) | 코스닥 920 (+0.5%)│
│ 외국인 +2,300억 | 기관 -800억             │
├─────────────────────────────────────────┤
│ 📰 AI 뉴스 요약                          │
│ 1. 삼성전자 HBM4 양산 — 반도체 수혜      │
│ 2. 밸류업 2차 방안 — 저PBR주 관심         │
│ 3. 연준 "금리 인하 서두르지 않겠다"       │
│                          [뉴스 전체 보기] │
├─────────────────────────────────────────┤
│ 📋 주요 공시                              │
│ 🟢 한화오션 — 수주 3.2조원                │
│ 🔴 LG에너지 — 유상증자 결정               │
│ 🟢 삼영무역 — 배당 1,183원                │
│                          [공시 전체 보기] │
├─────────────────────────────────────────┤
│ 🔍 관심종목 체크                          │
│ 삼영무역: 뉴스 없음 | 외국인 +5만주       │
│ 유수홀딩스: 실적발표 D-3                  │
│                     [관심종목 관리 →]      │
└─────────────────────────────────────────┘
```

### 7-2. 과거 브리프 (/archive)

```
달력 형태로 날짜 선택 → 해당일 브리프 조회
최근 30일 브리프 리스트
```

### 7-3. 관심종목 관리 (/watchlist)

```
종목 검색 + 추가
현재 관심종목 목록 (드래그 정렬)
종목별 최근 뉴스/공시 미리보기
```

---

## 8. 스케줄 (APScheduler)

```python
# 매일 실행
07:00  generate_daily_brief()     # 모닝브리프 생성 + 텔레그램 발송
12:00  check_midday_news()        # 점심 뉴스 체크 (관심종목 변동 있을 때만 알림)
18:00  cleanup_old_data()         # 90일 이전 데이터 삭제

# 장중 (선택 — Phase 2)
09:30~15:00 매 30분  check_breaking_news()  # 관심종목 속보 감지 시 즉시 알림
```

---

## 9. 환경 설정 (.env)

```env
# 기존 StockAI와 동일한 키 재사용
DART_API_KEY=xxxxx
NAVER_CLIENT_ID=xxxxx
NAVER_CLIENT_SECRET=xxxxx
ANTHROPIC_API_KEY=xxxxx

# 텔레그램 (StockAI와 같은 봇 또는 별도 봇)
TELEGRAM_BOT_TOKEN=xxxxx
TELEGRAM_CHAT_ID=xxxxx

# InvestBrief 전용
INVESTBRIEF_DB_URL=sqlite+aiosqlite:///./investbrief.db
BRIEF_SEND_HOUR=7          # 브리프 발송 시간 (기본 07:00)
AI_MODEL=claude-sonnet-4-20250514
AI_MAX_TOKENS=1000
```

---

## 10. StockAI 연동 (Phase 2 — 나중에)

```
Phase 1 (지금): 완전 독립. API 키만 공유.
Phase 2 (안정화 후):
  - InvestBrief 관심종목 → StockAI 파이프라인 분석 연결
  - InvestBrief 대시보드에 "상세 분석" 버튼 → StockAI API 호출
  - 텔레그램 봇 통합 (하나의 봇으로 브리프 + 매매알림)
```

---

## 11. 개발 순서 (4주)

### 1주차: 데이터 수집 파이프라인

```
Day 1-2: 프로젝트 셋업
  - FastAPI 보일러플레이트 (main.py, config.py, database.py)
  - SQLite + 모델 정의
  - requirements.txt

Day 3-4: collectors 구현
  - market_collector.py (yfinance — 해외지수/환율/유가)
  - news_collector.py (RSS 파싱 + 네이버 뉴스 API)
  - dart_collector.py (당일 공시 수집)
  - stock_collector.py (코스피/코스닥 요약)

Day 5: AI 요약 + 브리프 조립
  - ai_summarizer.py (Claude API 뉴스 요약)
  - brief_service.py (수집 → 요약 → 조립)
  - 터미널에서 수동 실행하여 결과 확인

1주차 완료 기준: python -c "..." 로 브리프 JSON 출력 확인
```

### 2주차: 텔레그램 봇

```
Day 1-2: 텔레그램 발송
  - telegram_service.py (브리프 포맷팅 + 발송)
  - 07:00 스케줄 등록

Day 3-4: 텔레그램 명령어
  - /today, /watch, /unwatch, /list, /news
  - watchlist_service.py (관심종목 CRUD)

Day 5: 관심종목 체크
  - 관심종목별 뉴스/공시/수급 변동 수집
  - 브리프에 관심종목 섹션 추가

2주차 완료 기준: 매일 아침 7시 텔레그램에 브리프 도착
```

### 3주차: 웹 대시보드

```
Day 1-2: Next.js 셋업 + 메인 페이지
  - 오늘의 브리프 표시 (API 연동)
  - 글로벌 시장 카드, 뉴스 섹션

Day 3-4: 나머지 페이지
  - /archive (과거 브리프)
  - /watchlist (관심종목 관리)
  - 반응형 디자인

Day 5: API 연동 마무리
  - 종목 검색 + 관심종목 추가
  - 공시 상세 보기

3주차 완료 기준: http://localhost:3000 에서 브리프 확인 가능
```

### 4주차: 고도화

```
- 공시 중요도 자동 분류 (🔴🟡🟢⚪)
- 뉴스 업종별 분류 (반도체/자동차/금융...)
- 점심 뉴스 체크 (12:00 관심종목 변동 알림)
- 에러 처리, 로깅 정리
- 블로그 글 1편 작성: "AI 투자 모닝브리프 시스템 만들기"
```

---

## 12. Claude Code 개발 규칙 (CLAUDE.md)

```markdown
# InvestBrief 개발 규칙

## 기술 스택
- Backend: Python 3.11 + FastAPI + SQLAlchemy 2.0 (async)
- Frontend: Next.js 15 App Router + TypeScript strict
- DB: SQLite (investbrief.db) — SQLAlchemy aiosqlite
- AI: Claude API (claude-sonnet-4-20250514)
- 텔레그램: python-telegram-bot 또는 직접 HTTP 호출

## 코드 규칙
- Python: 타입 힌트 필수, async/await 사용
- 모든 외부 API 호출은 try/except로 감싸기
- 로깅: logger.info/warning/error 사용 (print 금지)
- 환경 변수: pydantic-settings의 BaseSettings 사용

## 디렉토리 규칙
- collectors/: 외부 데이터 수집만 (비즈니스 로직 없음)
- services/: 비즈니스 로직 (collector 조합, AI 호출)
- models/: SQLAlchemy 모델
- api/: FastAPI 라우터 (얇게 — service 호출만)

## StockAI와의 관계
- 코드 복사 가능하지만 import 하지 않음 (독립 프로젝트)
- API 키는 같은 .env에서 공유
- DB는 별도 (investbrief.db)
```

---

## 13. 비용

| 항목 | 비용 | 비고 |
|------|------|------|
| yfinance | 무료 | 해외지수/환율 |
| RSS | 무료 | 경제뉴스 |
| DART API | 무료 | 일 10,000건 |
| 네이버 검색 API | 무료 | 일 25,000건 |
| Claude API | 하루 ~100원 | 뉴스 20건 요약 1회 = ~1,000 토큰 |
| 텔레그램 | 무료 | Bot API |
| **합계** | **월 ~3,000원** | Claude API 비용만 |
