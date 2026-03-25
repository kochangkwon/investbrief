# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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
- Frontend: 3001 (API는 next.config.ts rewrites로 8001 프록시)

## Schedules (APScheduler)

- 07:00 — 모닝브리프 생성 + 텔레그램 발송
- 12:00 — 관심종목 변동 알림 (±2% 이상, 뉴스/공시 있을 때)
- 18:00 — 90일 이전 데이터 정리

## Code Rules

- Python 타입 힌트 필수, async/await 사용
- 모든 외부 API 호출은 try/except로 감싸기
- 로깅: `logger.info/warning/error` 사용 (print 금지)
- 환경 변수: pydantic-settings의 `BaseSettings` 사용 (`extra="ignore"` — .env에 다른 프로젝트 키 혼재)
- brief_service의 `_safe_collect` 패턴: 개별 수집 실패가 전체 브리프 생성을 중단하지 않음

## Directory Rules

- `collectors/`: 외부 데이터 수집만 (비즈니스 로직 없음)
- `services/`: 비즈니스 로직 (collector 조합, AI 호출, 텔레그램 봇)
- `models/`: SQLAlchemy 모델
- `api/`: FastAPI 라우터 (얇게 — service 호출만)

## Telegram Bot Commands

/today, /watch, /unwatch, /list, /news, /dart, /help
