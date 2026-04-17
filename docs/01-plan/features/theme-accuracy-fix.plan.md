---
template: plan
version: 1.2
feature: theme-accuracy-fix
date: 2026-04-16
author: kochangkwon
project: InvestBrief
status: Draft
---

# theme-accuracy-fix Planning Document

> **Summary**: 테마 스캐너(THEME_RADAR)의 종목명 오탐 문제를 Claude API 검증 레이어로 해결하고, 기존 48건 감지 이력을 재검증하여 오탐을 제거한다.
>
> **Project**: InvestBrief
> **Version**: 0.1 (Phase 4 보강)
> **Author**: kochangkwon
> **Date**: 2026-04-16
> **Status**: Draft

---

## 1. Overview

### 1.1 Purpose

현재 `theme_radar_service._scan_single_theme`는 키워드로 검색한 뉴스 제목에서 정규식으로 한글 단어를 추출 → `stock_search`로 검증하는 방식이다. 뉴스 제목에 우연히 등장한 **무관 종목명**도 그대로 수혜주로 감지되어 실사용 불가 수준의 오탐이 누적되고 있다.

**목표:** Claude API 기반 문맥 검증 레이어를 도입하여 "해당 뉴스에서 이 종목이 실제로 이 테마의 수혜주인가?"를 판정, 오탐 90% 이상 차단.

### 1.2 Background

2026-04-16 기준 DB 상태:
- `theme` 6개 등록, `theme_detection` 48건 누적
- **확인된 오탐 예시:**
  - 방산 수출 확대 → 셀트리온 (제약)
  - HBM 반도체 후공정 → 삼천당제약 (제약), 로보티즈 (로봇), 성호전자 (전기부품)
  - 포장재·캔병 공급 대란 → 효성중공업 (전력기기), 삼양식품 (식품)

**원인:**
1. 정규식이 뉴스 제목의 모든 한글 단어를 후보로 추출
2. 추출된 종목명이 테마 키워드와 문맥적 연관이 있는지 판단하는 로직 없음
3. 네이버 뉴스 `description`(200자) 필드를 활용하지 않음 — 컨텍스트 부족

**비즈니스 영향:** 매주 월요일 08:00 자동 스캔 시 오탐이 계속 쌓이고 텔레그램 알림도 무관 종목을 포함. Ko~님의 실제 의사결정에 사용 불가.

### 1.3 Related Documents

- 지시서: `instructions/INVESTBRIEF_THEME_RADAR.md` (원본 설계)
- 지시서: `instructions/INVESTBRIEF_THEME_DISCOVERY.md` (참고 — 동일 패턴)
- 마스터 적용 지시서: `instructions/MASTER_APPLY_ORDER.md`
- 프로젝트 가이드: `CLAUDE.md` (Python 3.9 호환성, async 규약)

---

## 2. Scope

### 2.1 In Scope

- [ ] `theme_radar_service.py`에 Claude API 검증 함수 `_verify_theme_match()` 추가
- [ ] `_scan_single_theme`의 감지 흐름에 검증 레이어 삽입 (저장/알림 직전)
- [ ] Claude API 호출 실패 시 **기본 거부**(reject) 정책으로 오탐 방지
- [ ] 뉴스 `description` 필드를 검증 프롬프트 컨텍스트에 포함
- [ ] 기존 48건 재검증 일회성 스크립트 (`scripts/verify_theme_detections.py` 신규)
- [ ] 재검증 결과 리포트를 콘솔 + 파일로 출력 (Ko~님 확인용)
- [ ] Ko~님 승인 후 오탐 레코드 삭제

### 2.2 Out of Scope

- `reason` 컬럼 추가 (Q3 B — 스키마 유지)
- `theme_discovery_service` 오탐 개선 (별도 이슈, 본 범위 외)
- 규칙 기반 필터 (키워드 인접성 등) — Claude 단독 검증으로 충분
- 프론트엔드 UI 변경 (백엔드 전용 수정)
- `/theme-add`, `/theme-list` 등 CRUD 로직 (영향 없음)

---

## 3. Requirements

### 3.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-01 | `_verify_theme_match(theme_name, keyword, stock_name, title, description)` 비동기 함수가 bool 반환 | High | Pending |
| FR-02 | 검증 프롬프트는 테마명, 매칭 키워드, 뉴스 제목+설명, 종목명을 모두 포함 | High | Pending |
| FR-03 | Claude 응답 파싱: `YES`/`NO` 판정 + 1줄 근거 (근거는 로깅만, DB 미저장) | High | Pending |
| FR-04 | Claude API 예외/타임아웃 시 `False` 반환 (오탐 방지) | High | Pending |
| FR-05 | `_scan_single_theme`에서 DB 저장 직전 검증 → YES만 저장 + 알림 | High | Pending |
| FR-06 | `scripts/verify_theme_detections.py` 일회성 스크립트 — 기존 48건 재검증 | High | Pending |
| FR-07 | 재검증 스크립트는 오탐 리스트를 `docs/03-analysis/theme-cleanup-report.md`로 저장 | Medium | Pending |
| FR-08 | 스크립트는 `--dry-run` 플래그로 미삭제 실행 지원, 삭제는 `--apply` 필요 | High | Pending |

### 3.2 Non-Functional Requirements

| Category | Criteria | Measurement Method |
|----------|----------|-------------------|
| 정확도 | 기존 오탐 48건 중 90% 이상 NO 판정 | 수동 스팟 체크 + Claude 판정 결과 비교 |
| 성능 | 검증 1건당 평균 2초 이내 (Claude API 응답) | 로그 타이머 |
| 비용 | 월 추가 Claude API 비용 < $1 (기존 $2~3에 추가) | API usage 로그 (`response.usage.output_tokens`) |
| 안정성 | Claude API 실패율 5% 이하 시에도 오탐 증가 없음 | fallback=False 동작 확인 |
| Python 호환 | Python 3.9 호환 유지 (`from __future__ import annotations` 활용) | 실행 확인 |
| 로깅 | 검증 결과(YES/NO + 이유) 모두 `logger.info` 기록 | 로그 grep 확인 |

---

## 4. Success Criteria

### 4.1 Definition of Done

- [ ] `_verify_theme_match()` 구현 및 단위 동작 확인
- [ ] `_scan_single_theme` 검증 호출 삽입 완료
- [ ] 기존 48건 재검증 리포트 생성 (`theme-cleanup-report.md`)
- [ ] Ko~님 리포트 검토 후 오탐 레코드 삭제 승인
- [ ] 백엔드 재시작 후 `/theme-scan` 수동 실행 → 새 감지는 검증 통과분만 저장됨을 확인
- [ ] `/pdca analyze theme-accuracy-fix` Gap Rate ≥ 90%

### 4.2 Quality Criteria

- [ ] Python 3.9 문법 위반 없음 (union `str | None` 금지 규칙 준수)
- [ ] 기존 `_safe_collect` 패턴 유지 (외부 API 실패가 전체 스캔을 중단하지 않음)
- [ ] 로깅 기준 준수 (`print` 금지, `logger.*` 사용)
- [ ] 텔레그램 알림 메시지 포맷은 기존 유지 (검증 로직만 삽입)
- [ ] DB 스키마 변경 없음 (`theme_detection` 테이블 원형 유지)

---

## 5. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Claude API가 legitimate 수혜주를 NO 판정 (false rejection) | Medium | Medium | 프롬프트에 "애매하면 YES" 원칙 명시 + 주 1회 로그 검토 |
| Claude API 응답 포맷 파싱 실패 | Medium | Low | 정규식으로 YES/NO 추출, 실패 시 False 반환(오탐 방지 우선) |
| Rate Limit 도달 — 30+ 후보 동시 검증 시 | Medium | Low | 후보 목록을 순차 처리, 실패 시 다음 스캔에 재시도 (중복 감지 로직으로 자연스러운 재시도) |
| 비용 초과 — 스캔당 후보가 100+ 인 경우 | Low | Low | 정규식 추출 단계에서 중복 제거 + `STOPWORDS` 추가 확장 |
| 기존 48건 삭제 중 정상 감지도 함께 제거 | High | Low | `--dry-run` 기본값 + Ko~님 승인 후 `--apply` + 실행 전 DB 백업 |
| DB 백업 없이 삭제 실행 | High | Low | 스크립트 시작 시점에 `cp investbrief.db investbrief.db.bak-YYYYMMDD` 자동 실행 |
| Claude 모델 변경 시 프롬프트 재튜닝 필요 | Low | Medium | `settings.ai_model` 참조 — 모델 교체 시 프롬프트 영향 재평가 메모 |

---

## 6. Architecture Considerations

### 6.1 Project Level Selection

| Level | Characteristics | Recommended For | Selected |
|-------|-----------------|-----------------|:--------:|
| **Starter** | Simple structure | Static sites | ☐ |
| **Dynamic** | Feature-based modules, services layer | Web apps with backend, SaaS MVPs | ☑ |
| **Enterprise** | Strict layer separation, DI, microservices | High-traffic systems | ☐ |

InvestBrief는 FastAPI + services 레이어 분리형 Dynamic 프로젝트. 본 작업은 기존 `services/theme_radar_service.py`에 함수 추가만 하므로 레이어 변경 없음.

### 6.2 Key Architectural Decisions

| Decision | Options | Selected | Rationale |
|----------|---------|----------|-----------|
| 검증 방식 | Claude API / 규칙 / 하이브리드 | **Claude API** | 문맥 판단은 정규식/규칙으로 불가, Claude가 가장 정확 |
| 실패 시 정책 | 승인(True) / 거부(False) / 보류 | **거부(False)** | 오탐 방지가 최우선 — API 장애 시 알림 일시 중단이 오탐보다 나음 |
| 검증 시점 | 수집 직후 / DB 저장 직전 / 알림 직전 | **DB 저장 직전** | 중복 검증 방지 + 불필요한 Claude 호출 최소화 (이미 `existing_codes` 필터 통과한 신규 후보만) |
| 컨텍스트 소스 | title 단독 / title+description / title+description+URL 페치 | **title+description** | 네이버 뉴스 description 200자로 충분, URL 페치는 비용·지연 증가 |
| reason 저장 | 컬럼 추가 / 로그만 / 미저장 | **로그만** | Q3 B 결정 — 스키마 단순성 유지 |
| 기존 48건 처리 | 유지 / 삭제 / 재검증 | **재검증 후 Ko~님 승인 삭제** | Q2 A 결정 — 데이터 보호 + 제어권 확보 |

### 6.3 Clean Architecture Approach

```
Selected Level: Dynamic

기존 구조 유지:
backend/app/
  ├── collectors/          # 외부 데이터 수집 (news, stock_search)
  ├── services/            # 비즈니스 로직
  │   ├── theme_radar_service.py   ← 본 작업 대상
  │   └── telegram_service.py
  ├── models/              # SQLAlchemy
  │   └── theme.py         ← 스키마 변경 없음
  └── config.py            # ANTHROPIC_API_KEY 등

신규:
backend/scripts/
  └── verify_theme_detections.py   ← 일회성 재검증 스크립트
```

---

## 7. Convention Prerequisites

### 7.1 Existing Project Conventions

- [x] `CLAUDE.md` 에 Python 호환성 / async / 로깅 / `_safe_collect` 패턴 명시됨
- [ ] `docs/01-plan/conventions.md` 없음 (개별 프로젝트 규약은 CLAUDE.md 따름)
- [x] ESLint / Prettier / TypeScript — Frontend 전용, 본 작업 무관
- [x] Python async/await 규약 CLAUDE.md 준수

### 7.2 Conventions to Define/Verify

| Category | Current State | To Define | Priority |
|----------|---------------|-----------|:--------:|
| **Naming** | `_private_func` 규약 존재 | 본 작업 `_verify_theme_match` 동일 패턴 | Low |
| **Folder structure** | `services/`, `scripts/` 존재 (scripts는 신규) | `backend/scripts/` 디렉토리 신규 생성 | Medium |
| **Import order** | stdlib → 3rd party → app. 순 | 기존 관례 준수 | Low |
| **Environment variables** | `ANTHROPIC_API_KEY` 사용 중 | 신규 없음 | — |
| **Error handling** | `try/except` + `logger.exception` | 기존 패턴 준수 | High |

### 7.3 Environment Variables Needed

| Variable | Purpose | Scope | To Be Created |
|----------|---------|-------|:-------------:|
| `ANTHROPIC_API_KEY` | Claude API 호출 (이미 사용 중) | Server | ☐ (기존) |
| `AI_MODEL` | 검증용 모델 (기존값 `claude-sonnet-4-20250514` 재사용) | Server | ☐ (기존) |

**신규 환경변수 없음.** 기존 `settings.anthropic_api_key`, `settings.ai_model` 재사용.

### 7.4 Pipeline Integration

본 작업은 9단계 파이프라인의 **Phase 8 (Review/Gap Analysis)** 성격. 단일 feature 개선이므로 파이프라인 전체 실행은 불필요, PDCA 단일 사이클로 진행.

---

## 8. Next Steps

1. [ ] `/pdca design theme-accuracy-fix` — 상세 설계 문서 작성
   - 프롬프트 템플릿 확정
   - 검증 함수 시그니처 확정
   - 스크립트 워크플로우 확정
2. [ ] `/pdca do theme-accuracy-fix` — 구현 착수
3. [ ] `/pdca analyze theme-accuracy-fix` — Gap 검증
4. [ ] Ko~님 재검증 리포트 승인 → 오탐 삭제
5. [ ] `/pdca report theme-accuracy-fix` — 완료 보고서

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-04-16 | Initial draft — Q1 A / Q2 A / Q3 B 확정 반영 | kochangkwon |
