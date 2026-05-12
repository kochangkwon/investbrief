# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.


## Project Overview

**InvestBrief** — 매일 아침 투자자에게 AI가 모아 요약한 투자 모닝브리프를 제공하는 시스템.
네이버금융 + DART + 경제뉴스 + 해외시장을 하나로 통합.

StockAI와 완전 독립 프로젝트 (API 키만 공유, import 없음, DB 별도).

## Tech Stack

- Backend: Python 3.9+ + FastAPI + SQLAlchemy 2.0 (async) + APScheduler
- Frontend: Next.js 16 App Router + TypeScript strict + Tailwind CSS 4
- DB: SQLite (investbrief.db) via aiosqlite
- AI: Claude API (claude-sonnet-4-20250514) — 뉴스 요약 + 업종별 분류
- Bot: Telegram Bot API (polling 방식)

## Python Compatibility

- Runtime: Python 3.9 — `str | None` 등 3.10+ union 문법 사용 금지
- Pydantic BaseModel 필드: `Optional[str]` 사용 (`from typing import Optional`)
- 일반 함수 시그니처: `from __future__ import annotations` 추가 후 `str | None` 가능

## Commands

```bash
# Backend 실행 (port 8001)
cd backend && python3 -m uvicorn app.main:app --reload --port 8001

# Frontend 실행 (port 3001)
cd frontend && npm run dev

# 의존성 설치
cd backend && pip install -r requirements.txt
cd frontend && npm install
```

## Ports

- Backend: 8001
- Frontend: 3001 (API는 next.config.ts rewrites로 `/api/*` → `localhost:8001/api/*` 프록시)

## Environment Variables (.env in backend/)

필수: `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
선택: `DART_API_KEY`, `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`
설정: `BRIEF_SEND_HOUR` (기본 7), `BRIEF_SEND_MINUTE` (기본 30), `AI_MODEL`, `AI_MAX_TOKENS`

`.env`에 다른 프로젝트 키가 혼재하므로 Settings에 `extra="ignore"` 설정됨.

## Architecture — 브리프 생성 파이프라인

`brief_service.generate_daily_brief()`가 오케스트레이터:

1. **수집** — 4개 collector 병렬 호출 (`_safe_collect`로 개별 실패 허용)
   - `stock_collector`: 코스피/코스닥 (네이버 금융 API, httpx async)
   - `market_collector`: 해외 시장 (yfinance)
   - `news_collector`: 경제 뉴스 (네이버 검색 API + feedparser)
   - `dart_collector`: DART 공시 API
2. **AI 요약** — `ai_summarizer`가 Claude API로 뉴스 요약
3. **관심종목** — `watchlist_service`가 등록 종목별 가격/뉴스/공시 취합
4. **저장** — `DailyBrief` 모델로 SQLite에 JSON 필드로 저장
5. **발송** — `telegram_service`로 텔레그램 전송

## Schedules (APScheduler)

- 07:30 — 모닝브리프 생성 + 텔레그램 발송 (`brief_send_hour`/`brief_send_minute`로 설정 가능)
- 12:00 — 관심종목 변동 알림 (±2% 이상, 뉴스/공시 있을 때)
- 16:30 — 관심종목 일일 리포트 (월~금)
- 18:00 — 90일 이전 데이터 정리

## Code Rules

- Python 타입 힌트 필수, async/await 사용
- 모든 외부 API 호출은 try/except로 감싸기
- 로깅: `logger.info/warning/error` 사용 (print 금지)
- `_safe_collect` 패턴: 개별 수집 실패가 전체 브리프 생성을 중단하지 않음

## Directory Rules

- `collectors/`: 외부 데이터 수집만 (비즈니스 로직 없음)
- `services/`: 비즈니스 로직 (collector 조합, AI 호출, 텔레그램 봇)
- `models/`: SQLAlchemy 모델
- `api/`: FastAPI 라우터 (얇게 — service 호출만)

## Telegram Bot Commands

/today, /watch, /unwatch, /list, /news, /dart, /help


