# StockAI + InvestBrief 통합 파이프라인 — 마스터 적용 지시서

## 목적

이번 세션에서 작성한 8개 지시서를 **올바른 순서**로 적용하여
**"테마 발굴 → 심층 분석 → 매수 알림 → 자동 매매"** 파이프라인을 완성합니다.

---

## 📋 8개 지시서 전체 목록

| # | 파일명 | 대상 | 의존성 |
|---|--------|------|--------|
| 1 | `STOCKAI_AGENT_TEAM_SETUP.md` | StockAI | 없음 (최우선) |
| 2 | `STOCKAI_REPORT_FORMAT_FIX.md` | StockAI | #1 필요 |
| 3 | `STOCKAI_BATCH_ANALYZE.md` | StockAI | #1, #2 필요 |
| 4 | `STOCKAI_REMOVE_HOLDING_LIMIT.md` | StockAI | 없음 (독립) |
| 5 | `STOCKAI_STOCK_MEMO_TOOLTIP.md` | StockAI | 없음 (독립) |
| 6 | `INVESTBRIEF_IMPROVEMENTS.md` | InvestBrief | 없음 (독립) |
| 7 | `INVESTBRIEF_THEME_RADAR.md` | InvestBrief | 없음 (독립) |
| 8 | `INVESTBRIEF_THEME_DISCOVERY.md` | InvestBrief | 없음 (독립 — #7과 통합 권장) |

---

## 🎯 적용 순서 (권장)

### Phase 1: StockAI 에이전트 팀 활성화 (최우선)

**목표:** `/analyze` 커맨드로 종목 심층 분석 가능하게 만들기

```
1-1. STOCKAI_AGENT_TEAM_SETUP.md 적용
     ↓
1-2. STOCKAI_REPORT_FORMAT_FIX.md 적용
     ↓
1-3. 검증: /analyze 삼성전자 실행 → 리포트 뷰어에서 확인
```

**완료 후 가능:**
- 개별 종목 심층 분석 (`/analyze <종목명>`)
- 에이전트 팀 3명 병렬 분석 (매크로/펀더멘탈/기술적)
- 리포트 뷰어 `/report`에서 시각적 대시보드

**소요 시간:** 30분~1시간

---

### Phase 2: StockAI 추가 기능 (선택)

**2-1. STOCKAI_BATCH_ANALYZE.md (배치 분석)**

**완료 후 가능:**
- `/batch-analyze 032620,071200,...` 여러 종목 일괄 분석
- 하네스 1단계 필터 → D등급 자동 탈락
- 매크로 1회 + 종목별 순차 분석으로 시간 40% 절약

**2-2. STOCKAI_REMOVE_HOLDING_LIMIT.md (3종목 제한 해제)**

**완료 후 가능:**
- 동시 보유 종목 수 무제한 (예수금이 허용하는 한)
- 현재 차단되고 있는 4번째 이후 종목도 매수 가능

**2-3. STOCKAI_STOCK_MEMO_TOOLTIP.md (메모 + 툴팁)**

**완료 후 가능:**
- 종목 분석 페이지에서 textarea로 메모 저장
- 대시보드 관심종목에 마우스 오버 시 📝 툴팁으로 메모 확인

**소요 시간:** 각 30분~1시간

---

### Phase 3: InvestBrief 버그 수정

**3-1. INVESTBRIEF_IMPROVEMENTS.md 적용**

버그 3건 + 고도화 7건 (총 10건):
- 🔴 뉴스 오매칭 (삼영무역 → 보원케미칼 표시 문제)
- 🔴 주말 스케줄러 미처리
- 🔴 HTML 특수문자 이스케이프
- 🟡 브리프 병렬화 (asyncio.gather)
- 🟡 시세 병렬화
- 🟡 `/watch` 자동 검색
- 🟡 AI 요약 품질 향상
- 🟡 DART 매칭 개선
- 🟡 중복 발송 방지
- 🟡 에러 알림 통일

**완료 후 가능:**
- 정확한 관심종목 뉴스 매칭
- 주말에도 스케줄러 정상 동작
- 전반적 품질 향상

**소요 시간:** 2~3시간

---

### Phase 4: 테마 시스템 (파이프라인 완성 ★★★)

**⚠️ 중요: #7과 #8은 통합 사용 권장. 둘 다 적용해야 파이프라인 완성.**

**4-1. INVESTBRIEF_THEME_RADAR.md (키워드 스캐너)**

**완료 후 가능:**
- `/theme-add "테마명" 키워드1,키워드2,...` 테마 등록
- `/theme-scan` 수동 즉시 스캔
- `/theme-list` 등록된 테마 목록
- `/theme-remove "테마명"` 테마 삭제
- **매주 월요일 08:00 자동 스캔** → 신규 수혜주 감지 시 텔레그램 알림

**4-2. INVESTBRIEF_THEME_DISCOVERY.md (아카이브 발굴)**

**완료 후 가능:**
- `/theme-discover [일수]` AI가 부상 테마 자동 발굴
- `/theme-trending` 언급 빈도 TOP 10
- **매주 일요일 09:00 자동 발굴** → 주간 테마 리포트 텔레그램 수신
- 180일치 아카이브 활용 (기존 90일에서 확장)

**소요 시간:** 각 1~2시간

---

## 🚀 완성 후 워크플로우

```
[매주 일요일 09:00] InvestBrief 자동
  ├── Claude API가 30일 아카이브 분석
  └── 🎯 주간 테마 발굴 리포트 텔레그램 수신
      ├── 부상 중인 테마 3~5개
      ├── 모멘텀 강도 🔥🔥🔥
      └── 언급 빈도 TOP 10

[일요일 오전] Ko~님 10분 투입
  └── /theme-add "새로 발견한 테마" 키워드1,키워드2,...

[매주 월요일 08:00] InvestBrief 자동
  ├── 등록된 테마 키워드로 네이버 뉴스 검색
  └── 🎯 신규 수혜주 감지 시 텔레그램 알림

[월요일 오전] Ko~님 Claude Code에서 15분
  └── /batch-analyze 감지된 종목들
      ├── 하네스 1단계 필터 (D등급 자동 제외)
      └── 에이전트 팀 심층 분석 → 리포트 생성

[월요일 오전] Ko~님 웹 UI에서 3분
  └── 매수 알림센터에 규칙 등록
      ├── 익절 ATR×2
      ├── 손절 ATR×3
      └── TIME_STOP 10거래일

[매일 09:00~14:30] StockAI 자동
  ├── 매크로 모드 판정 (TREND/CAUTIOUS/VALUE)
  ├── 조건 충족 감지
  └── 🚨 텔레그램 매수 확인 요청

[매수 시그널 발생] Ko~님 5초
  └── ✅ 매수 승인 버튼 클릭

[자동 실행] StockAI + 키움 API
  ├── 매수 주문 체결
  ├── 익절/손절 자동 감시
  └── 일일 리포트 (InvestBrief)
```

**Ko~님 투입 시간: 주당 약 30분**

---

## ✅ Phase별 체크리스트

### Phase 1 완료 확인

- [ ] `STOCKAI_AGENT_TEAM_SETUP.md` 적용
- [ ] `.claude/settings.json` 생성됨
- [ ] `.claude/commands/` 폴더에 analyze/screen/team-analyze/harness 4개 존재
- [ ] `.claude/agents/` 폴더에 3명 에이전트 정의 존재
- [ ] `_workspace/`, `reports/` 디렉토리 생성됨
- [ ] CLAUDE.md에 에이전트 팀 섹션 추가됨
- [ ] `STOCKAI_REPORT_FORMAT_FIX.md` 적용
- [ ] `report-template.md`가 10개 섹션 구조로 교체됨
- [ ] `stock-team/SKILL.md` Phase 4 형식 강제 규칙 추가됨
- [ ] **검증: `/analyze 삼성전자` 실행 성공**
- [ ] **검증: 리포트 뷰어 `/report`에서 정상 렌더링**

### Phase 2 완료 확인

- [ ] `/batch-analyze 005930,000660,035720` 실행 → 3종목 일괄 분석 성공
- [ ] 하네스 1단계 결과가 사용자에게 보고됨
- [ ] `reports/batch_비교요약_YYYYMMDD.md` 생성됨
- [ ] 3종목 이상 보유 상태에서 새 매수 시그널 → 정상 알림 수신
- [ ] 종목 분석 탭에 textarea 메모 입력 UI 표시됨
- [ ] 관심종목 현황에서 메모 있는 종목에 📝 아이콘 표시
- [ ] 📝 아이콘 마우스 오버 → 툴팁에 메모 내용 표시

### Phase 3 완료 확인

- [ ] 관심종목 뉴스에서 오매칭 사라짐 (삼영무역 뉴스에 보원케미칼 안 나옴)
- [ ] 주말에도 스케줄러 정상 동작
- [ ] HTML 특수문자 (`<`, `>`, `&`) 포함된 뉴스 정상 표시
- [ ] 중복 발송 방지 작동

### Phase 4 완료 확인

- [ ] `/theme-add "테스트" 반도체,HBM` → 테마 저장 성공
- [ ] `/theme-list` → 등록된 테마 목록 정상 출력
- [ ] `/theme-scan` → 즉시 스캔 + 🎯 텔레그램 알림 수신
- [ ] `/theme-discover 30` → Claude API 분석 결과 수신
- [ ] `/theme-trending` → TOP 10 종목 출력
- [ ] `/theme-remove "테스트"` → 테마 삭제 성공
- [ ] DB에 `theme`, `theme_detection` 테이블 생성 확인
- [ ] **일요일 09:00 자동 발굴 리포트 수신** (실행 주기 확인 필요)
- [ ] **월요일 08:00 자동 스캔 알림 수신** (실행 주기 확인 필요)

---

## 🔄 의존성 관계도

```
StockAI 파이프라인:
  [#1 AGENT_TEAM_SETUP]  ──┐
         │                 │
         ↓                 ↓
  [#2 REPORT_FORMAT_FIX]  [#3 BATCH_ANALYZE]
         │
         ↓
  /analyze 사용 가능

  [#4 REMOVE_HOLDING_LIMIT]  ← 독립 적용 가능
  [#5 STOCK_MEMO_TOOLTIP]    ← 독립 적용 가능


InvestBrief 파이프라인:
  [#6 IMPROVEMENTS]  ← 독립 적용 가능 (버그 수정)

  [#7 THEME_RADAR]  ──┐
                      │ (통합 사용 권장)
  [#8 THEME_DISCOVERY]─┘
  │
  ↓
  테마 자동 발굴 + 수혜주 감지 파이프라인 완성
```

---

## 📊 우선순위 매트릭스

| 우선순위 | 지시서 | 이유 |
|---------|--------|------|
| 🔴 **필수 (Tier 1)** | #1, #2 | 에이전트 팀 없으면 다른 기능도 못 씀 |
| 🔴 **필수 (Tier 1)** | #7 | 테마 스캐너 없으면 자동화 불가 |
| 🟡 **강추 (Tier 2)** | #3 | 배치 분석으로 효율 극대화 |
| 🟡 **강추 (Tier 2)** | #8 | 테마 자동 발굴로 사각지대 해소 |
| 🟢 **권장 (Tier 3)** | #6 | InvestBrief 품질 향상 |
| 🟢 **권장 (Tier 3)** | #4 | 3종목 제한 해제 |
| 🔵 **선택 (Tier 4)** | #5 | 편의 기능 |

---

## 🚨 적용 시 주의사항

### 공통

- 각 지시서 적용 **전후에 git 커밋** 필수
- StockAI와 InvestBrief는 **별도 프로젝트**이므로 각자 적용
- macOS 환경: `python3`, `pip3` 사용
- 코드 변경 전 Claude Code/Cowork에게 지시서 전달 후 **승인 요청**

### Phase 1 특별 주의

- StockAI v3 실전 운용 중이라면 **백업 필수**
- `_workspace/`, `reports/` 디렉토리 `.gitignore` 추가
- 에이전트 팀 분석 시 Claude API 호출 비용 발생 (월 약 $5~10 예상)

### Phase 4 특별 주의

- DB 마이그레이션 필요 (`ALTER TABLE`)
- 180일 cleanup 정책 변경 (기존 90일) → DB 크기 약 9MB 증가
- 네이버 뉴스 API 호출 증가 → rate limit 모니터링

---

## 💰 비용 예측

| 항목 | 월 예상 비용 |
|------|-----------|
| StockAI 에이전트 팀 (Claude API) | $5~10 |
| InvestBrief 일일 브리프 (Claude API) | $2~3 |
| InvestBrief 테마 발굴 (Claude API) | $0.30~0.50 |
| 네이버 뉴스 API | 무료 (일일 할당량 내) |
| **합계** | **$8~14 (약 10,000~20,000원)** |

---

## 📅 추천 적용 일정

### 1주차 주말
- [ ] Phase 1 적용 (#1, #2)
- [ ] `/analyze` 테스트

### 2주차 주말
- [ ] Phase 4 적용 (#7, #8)
- [ ] 첫 `/theme-discover` 실행 → 리포트 확인
- [ ] 1~2개 테마 등록

### 3주차 평일
- [ ] 월요일 자동 스캔 알림 수신 확인
- [ ] 감지된 종목 `/analyze`로 분석
- [ ] 매수 알림센터 첫 등록

### 4주차 이후
- [ ] Phase 2, 3 선택 적용 (#3, #4, #5, #6)
- [ ] 파이프라인 안정화 + 실전 운용

---

## 🔮 완성 후 기대 효과

**Before (현재)**
- 종목 발굴: Ko~님이 직접 뉴스 검색
- 심층 분석: 수동으로 웹 검색 + 분석
- 매수 결정: 감에 의존
- 소요 시간: 종목당 2~3시간

**After (완성 후)**
- 종목 발굴: AI가 자동 발굴 (일 09:00)
- 심층 분석: `/batch-analyze` 15분
- 매수 결정: ★★★★☆ 등급 기반 판단
- 소요 시간: 주당 30분

**ROI:** 주당 10시간 → 30분 (**95% 시간 절감**) + 종목 발굴 정확도 향상

---

## ⚠️ 마지막 경고

- 모든 지시서는 **설계도**입니다. 실제 코드 변경 전 반드시 Ko~님이 검토 + 승인
- 각 Phase 적용 후 **1주일간 모니터링** 권장
- 문제 발생 시 **이전 커밋으로 롤백** 가능하도록 git 관리 필수
- 전체 8개 지시서 적용은 **1~2개월 분량**입니다. 한번에 다 하지 마세요.

---

**이 마스터 지시서를 기준으로 단계별로 진행하시면, 완성된 AI 투자 파이프라인이 완성됩니다.**
