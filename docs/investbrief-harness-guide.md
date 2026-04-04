# InvestBrief 하네스 활용 지시서

> Claude Code에서 InvestBrief 프로젝트를 하네스 기반으로 개발하기 위한 실전 가이드

---

## 1. 설치 & 셋업

### 1-1. 하네스 파일 배치

```bash
# InvestBrief 프로젝트 루트에 .claude/ 디렉토리 배치
investbrief/
├── .claude/
│   ├── skills/
│   │   └── orchestrator.md        # 오케스트레이터 (전체 조율)
│   └── agents/
│       ├── data-collector.md      # 데이터 수집
│       ├── ai-analyst.md          # AI 요약/분류
│       ├── backend-core.md        # 브리프 조립/스케줄러/DB/API
│       ├── telegram-agent.md      # 텔레그램 봇/발송
│       ├── frontend-agent.md      # Next.js 웹 대시보드
│       └── code-reviewer.md       # 코드 품질 검증
├── backend/
├── frontend/
├── CLAUDE.md
└── docs/
```

### 1-2. Harness 플러그인 설치 (선택)

revfactory/harness 플러그인을 설치했다면, 이미 만들어둔 `.claude/` 파일과 함께 동작합니다.
플러그인 없이도 `.claude/agents/`와 `.claude/skills/`는 Claude Code가 인식합니다.

```bash
# 설치 확인
claude plugins list

# 또는 Claude Code에서 직접
/agents   # 등록된 에이전트 목록 확인
```

---

## 2. 아키텍처 이해

### 2-1. 에이전트 구성도

```
┌─────────────────────────────────────────────────┐
│                 오케스트레이터                      │
│              (orchestrator.md)                    │
├────────┬────────┬────────┬────────┬──────────────┤
│        │        │        │        │              │
│  data  │   ai   │backend │telegram│  frontend    │
│collector│analyst │ -core  │-agent  │  -agent      │
│        │        │        │        │              │
│collectors/│ai_sum│brief_  │telegram│ src/app/     │
│ *.py   │marizer│service │_service│ src/comp/    │
│        │ .py   │ .py    │ .py    │              │
└────────┴────────┴────────┴────────┴──────────────┘
                      │
              ┌───────┴───────┐
              │ code-reviewer │  ← 모든 작업 후 검증
              └───────────────┘
```

### 2-2. 데이터 흐름

```
[팬아웃: 병렬 수집]
  market_collector ──┐
  stock_collector  ──┤
  news_collector   ──┼──→ [팬인: 합류]
  dart_collector   ──┤         │
  watchlist_service──┘         ▼
                        [파이프라인: 순차]
                        ai_summarizer
                              │
                              ▼
                        brief_service (조립)
                              │
                     ┌────────┼────────┐
                     ▼        ▼        ▼
                   DB저장  텔레그램   웹API
```

---

## 3. 실전 사용법: 프롬프트 예시

### 3-1. 특정 에이전트에게 작업 지시

Claude Code에서 자연어로 요청하면, 오케스트레이터가 적절한 에이전트에게 배정합니다.

#### 데이터 수집 관련

```
market_collector에 비트코인(BTC-USD) 추가해줘.
기존 TICKERS 딕셔너리에 추가하고 LABELS도 같이.
```

```
news_collector RSS 피드에 조선비즈 추가해줘.
URL: https://biz.chosun.com/rss/economy/
```

```
dart_collector 공시 중요도 분류에 "스팩합병" 키워드를 🟡(주의)로 추가해줘.
```

#### AI 요약 관련

```
ai_summarizer 프롬프트를 개선해줘.
현재 업종별 동향에 "방산" 업종을 추가하고,
각 이슈에 "투자 시사점"을 한 줄 더 붙여줘.
```

#### 백엔드 코어 관련

```
brief_service에서 데이터 수집을 asyncio.gather로 병렬 실행하도록 바꿔줘.
현재는 순차 실행이라 느림.
```

```
scheduler에 주말 제외 로직 추가해줘.
모닝브리프는 평일에만 생성.
```

```
새 API 엔드포인트 추가해줘:
GET /api/brief/weekly — 이번 주 브리프 요약 (월~금 핵심 이슈 통합)
```

#### 텔레그램 관련

```
텔레그램 봇에 /report 명령어 추가해줘.
실행하면 관심종목 일일 리포트를 즉시 발송.
```

```
텔레그램 브리프 포맷에 "시장 한줄 코멘트" 섹션 추가해줘.
AI 요약 맨 앞에 한 줄 총평 넣기.
```

#### 프론트엔드 관련

```
메인 페이지에 "시장 히트맵" 컴포넌트 추가해줘.
글로벌 시장 데이터를 색상으로 시각화.
상승=초록, 하락=빨강, 크기=변동폭.
```

```
관심종목 페이지에 드래그 정렬 기능 추가해줘.
```

### 3-2. 복합 작업 지시

여러 에이전트가 협력해야 하는 경우:

```
"시장 공포 지수" 기능을 추가해줘.

1. market_collector: VIX + 원달러 환율 변동 + 미국채 금리 데이터 활용
2. ai_summarizer: 수집된 데이터 기반 공포/탐욕 점수 (0~100) 산출
3. brief_service: DailyBrief 모델에 fear_greed_score 필드 추가
4. telegram_service: 브리프에 "🌡️ 시장 온도: 35 (공포)" 표시
5. frontend: MarketOverview 컴포넌트에 게이지 차트 추가
```

```
"실적 시즌 캘린더" 기능 추가해줘.

1. dart_collector: 실적발표 예정 공시 수집
2. watchlist_service: 관심종목 중 실적발표 D-Day 계산
3. brief_service: 브리프에 "이번 주 실적 발표" 섹션 추가
4. telegram: "📅 삼성전자 실적발표 D-2" 알림
5. frontend: watchlist 페이지에 캘린더 뷰 추가
```

### 3-3. 버그 수정 지시

```
뉴스 수집에서 RSS 타임아웃이 자주 발생해.
news_collector의 httpx 타임아웃을 10초→15초로 늘리고,
실패한 RSS 소스를 로그에 남기되 다른 소스 수집은 계속하도록 해줘.
```

```
텔레그램 브리프 발송 시 4096자 초과 에러 발생.
메시지를 분할 발송하도록 수정해줘.
글로벌 시장 + 국내 시장은 1번 메시지,
뉴스 요약 + 공시는 2번 메시지,
관심종목은 3번 메시지로.
```

### 3-4. 코드 리뷰 요청

```
지금까지 변경한 파일들 전체 코드 리뷰해줘.
code-reviewer 체크리스트 기준으로.
```

---

## 4. 작업 시 주의사항

### 4-1. 반드시 지켜야 할 규칙

| 규칙 | 이유 |
|------|------|
| Python 3.9 호환 유지 | 서버 환경 제약 |
| `_safe_collect` 패턴 유지 | 한 수집 실패가 전체를 죽이면 안 됨 |
| 텔레그램 + 웹 양쪽 확인 | StockAI에서 한쪽만 고쳐서 버그 난 교훈 |
| 외부 API 호출은 try/except | 네트워크 불안정 대비 |
| print 금지 → logger 사용 | 운영 환경 로깅 |

### 4-2. 에이전트 범위 침범 방지

각 에이전트는 자기 담당 파일만 수정합니다:

```
❌ 잘못된 예: data-collector가 brief_service.py 수정
✅ 올바른 예: data-collector가 collector만 수정,
              필요한 인터페이스 변경은 오케스트레이터에 보고
```

### 4-3. 새 기능 추가 시 체크리스트

```
□ 어떤 에이전트 범위인지 확인
□ 다른 에이전트와 인터페이스 변경이 필요한지 확인
□ 새 환경변수 → config.py + .env 예시 업데이트
□ 새 의존성 → requirements.txt 또는 package.json 업데이트
□ DB 모델 변경 → 기존 데이터 호환성 확인
□ 텔레그램 경로 영향 확인
□ 웹 UI 경로 영향 확인
□ code-reviewer 체크리스트 통과
```

---

## 5. 트러블슈팅

### 5-1. 하네스가 안 먹힐 때

```bash
# .claude/ 디렉토리가 프로젝트 루트에 있는지 확인
ls -la .claude/agents/
ls -la .claude/skills/

# Claude Code를 프로젝트 루트에서 실행했는지 확인
pwd
# → /path/to/investbrief 이어야 함
```

### 5-2. 에이전트가 범위 밖 파일을 건드릴 때

```
오케스트레이터에게 명시적으로 범위를 지정:

"data-collector 범위만 수정해줘.
collectors/ 폴더 안의 파일만 건드리고,
services/ 는 건드리지 마."
```

### 5-3. 복잡한 작업에서 컨텍스트가 길어질 때

```
작업을 단계별로 나눠서 진행:

1단계: "collector만 먼저 구현해줘"
2단계: "이제 service 레이어 연결해줘"
3단계: "텔레그램 발송 추가해줘"
4단계: "프론트엔드 컴포넌트 만들어줘"
5단계: "전체 코드 리뷰해줘"
```

---

## 6. 향후 확장

### 6-1. 새 에이전트 추가 시

`.claude/agents/` 에 새 마크다운 파일을 추가하면 됩니다:

```markdown
# 새 에이전트 이름 (agent-id)

## 역할
...

## 담당 파일
...

## 의존 관계
...

## 검증 기준
...
```

### 6-2. StockAI 연동 에이전트 (Phase 2)

InvestBrief가 안정화되면:

```
.claude/agents/stockai-bridge.md

역할: InvestBrief ↔ StockAI 간 데이터 브릿지
- 관심종목 → StockAI 파이프라인 분석 연결
- "상세 분석" 버튼 → StockAI API 호출
- 텔레그램 봇 통합 (브리프 + 매매알림 하나의 봇)
```

---

## 부록: 프로젝트 현황 요약

| 항목 | 상태 |
|------|------|
| Backend 구조 | ✅ 완성 (collectors, services, models, api) |
| 데이터 수집 | ✅ 4개 collector 구현 완료 |
| AI 요약 | ✅ Claude API 연동 완료 |
| 브리프 생성 | ✅ 파이프라인 구현 완료 |
| 텔레그램 봇 | ✅ 발송 + 명령어 처리 구현 완료 |
| 스케줄러 | ✅ 07:00/12:00/16:30/18:00 등록 완료 |
| 프론트엔드 | ✅ 메인/아카이브/관심종목 페이지 구현 |
| 일일 리포트 | ✅ RSI/이격률/거래량 포함 구현 완료 |
| 하네스 | ✅ 6개 에이전트 + 오케스트레이터 구성 완료 |
