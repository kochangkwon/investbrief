---
name: investbrief-orchestrator
description: "InvestBrief 프로젝트의 에이전트를 조율하는 오케스트레이터. 사용자 요청을 분석하여 적절한 에이전트(data-collector, ai-analyst, backend-core, telegram-agent, frontend-agent, code-reviewer)에게 작업을 배정한다. 데이터 수집, AI 요약, 백엔드, 텔레그램, 프론트엔드, 코드 리뷰 등 InvestBrief 관련 모든 개발 작업 시 이 스킬을 사용할 것."
---

# InvestBrief Orchestrator

InvestBrief 프로젝트의 에이전트를 조율하여 사용자 요청을 처리하는 통합 스킬.

## 실행 모드: 서브 에이전트

## 에이전트 구성

| 에이전트 | subagent_type | 역할 | 담당 영역 |
|---------|--------------|------|----------|
| data-collector | data-collector | 외부 데이터 수집 | collectors/*.py |
| ai-analyst | ai-analyst | AI 요약/분류 | ai_summarizer.py |
| backend-core | backend-core | 브리프 파이프라인/스케줄/DB/API | services/, models/, api/ |
| telegram-agent | telegram-agent | 텔레그램 봇/발송 | telegram_service.py, telegram_bot.py |
| frontend-agent | frontend-agent | Next.js 웹 대시보드 | frontend/src/ |
| code-reviewer | code-reviewer | 코드 품질 검증 | 전체 (읽기 전용) |

## 라우팅 규칙

사용자 요청을 분석하여 적절한 에이전트에 배정한다.

| 키워드/패턴 | 에이전트 |
|------------|---------|
| collector, 수집, 크롤링, RSS, API 데이터, 네이버, DART, yfinance | data-collector |
| 프롬프트, AI 요약, 업종 분류, 요약 품질, Claude API | ai-analyst |
| brief_service, 스케줄, DB 모델, API 엔드포인트, 관심종목 로직 | backend-core |
| 텔레그램, 봇 명령어, 메시지 포맷, 발송 | telegram-agent |
| 페이지, 컴포넌트, UI, 대시보드, 프론트엔드, Next.js | frontend-agent |
| 코드 리뷰, 품질 체크, 검증 | code-reviewer |

**모호한 요청**: 2개 이상 에이전트가 관련될 때 → 복합 작업 워크플로우 진행

## 워크플로우

### 단일 에이전트 작업

대부분의 요청은 단일 에이전트로 처리한다:

1. 사용자 요청 분석 → 라우팅 규칙으로 에이전트 결정
2. 해당 에이전트 호출:
   ```
   Agent(
     name: "{agent-name}",
     subagent_type: "{agent-name}",
     model: "opus",
     prompt: "{CLAUDE.md 컨텍스트 + 구체적 작업 지시}"
   )
   ```
3. 결과 반환

### 복합 작업 워크플로우 (새 기능 추가 등)

여러 에이전트가 협력해야 하는 경우:

#### Phase 1: 분석
1. 사용자 요청을 에이전트별 작업으로 분해
2. 의존 관계 파악 (어떤 에이전트가 먼저 작업해야 하는지)

#### Phase 2: 순차/병렬 실행

데이터 흐름에 따라 실행:

```
[팬아웃: 독립 작업 병렬]
  data-collector ──┐
  ai-analyst     ──┼── 병렬 실행 (run_in_background: true)
                   │
[파이프라인: 의존 작업 순차]
  backend-core ──→ telegram-agent ──→ frontend-agent
```

**실행 순서 원칙:**
1. collector 변경이 있으면 data-collector 먼저
2. 서비스 로직 변경 → backend-core
3. 출력 변경 → telegram-agent + frontend-agent (병렬 가능)
4. 마지막에 code-reviewer로 검증

#### Phase 3: 검증
```
Agent(
  name: "code-reviewer",
  subagent_type: "code-reviewer",
  model: "opus",
  prompt: "다음 파일들의 변경 사항을 검증하라: {변경된 파일 목록}"
)
```

#### Phase 4: 결과 보고
사용자에게 변경 요약 보고

## 데이터 흐름

```
[수집 계층]
  stock_collector ──┐
  market_collector──┤
  news_collector  ──┼──→ [서비스 계층]
  dart_collector  ──┤     brief_service (조립)
  watchlist_svc   ──┘     ai_summarizer (요약)
                                │
                       ┌────────┼────────┐
                       ▼        ▼        ▼
                     DB저장  텔레그램   웹API
```

## 에러 핸들링

| 상황 | 전략 |
|------|------|
| 에이전트 1개 실패 | 1회 재시도. 재실패 시 해당 결과 없이 진행, 사용자에게 실패 명시 |
| 복합 작업 중 중간 실패 | 이전 단계 결과 보존, 실패한 단계부터 재시도 가능 |
| 에이전트 범위 침범 | 해당 에이전트의 담당 파일 외 수정 시 경고, 올바른 에이전트에 재배정 |

## 테스트 시나리오

### 정상 흐름: 단일 에이전트
1. 사용자: "news_collector RSS 피드에 조선비즈 추가해줘"
2. 라우팅: data-collector
3. data-collector가 news_collector.py 수정
4. 결과: RSS 피드 추가 완료

### 정상 흐름: 복합 작업
1. 사용자: "시장 공포 지수 기능 추가해줘"
2. 분해: data-collector(VIX 수집) → ai-analyst(점수 산출) → backend-core(모델+API) → telegram-agent(발송) → frontend-agent(UI)
3. 순차 실행 후 code-reviewer 검증
4. 결과: 전체 기능 구현 + 리뷰 보고

### 에러 흐름
1. 사용자: "비트코인 시세 추가해줘"
2. data-collector 호출 → 실패 (API 키 없음)
3. 1회 재시도 → 재실패
4. 사용자에게 "market_collector에 BTC-USD 추가했지만 API 접근 실패. 환경변수 확인 필요" 보고
