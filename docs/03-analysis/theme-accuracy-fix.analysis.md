---
template: analysis
version: 1.0
feature: theme-accuracy-fix
date: 2026-04-16
author: gap-detector (via bkit:pdca analyze)
status: Final
---

# theme-accuracy-fix Gap Analysis

> 설계 문서 `docs/02-design/features/theme-accuracy-fix.design.md` 와 실제 구현 간 정합성 검증

## Summary

- **Match Rate: 100% (post-fix)** — 초안 97.1% → `selectinload` 미사용 import 제거로 100% 달성
- Total Items: 17 (9 main categories + 8 FR checks)
- Matched: 17
- Partial: 0
- Missing: 0

---

## Matched Items (완전 일치)

1. **`_verify_theme_match()` 시그니처 (Design 4.1)**
   파라미터 `theme_name, matched_keyword, stock_name, title, description=""`, 반환 `tuple[bool, str]`, fail-closed 모든 분기 구현. 위치: `backend/app/services/theme_radar_service.py:61-118`.

2. **프롬프트 템플릿 (Design 11.3)**
   VERDICT/REASON 포맷, "애매하면 YES" 기준, "뉴스 본문 신뢰 금지" 주의사항 모두 포함. 위치: `theme_radar_service.py:31-58`. 정규식 `_VERDICT_RE`, `_REASON_RE` 일치 (`:28-29`).

3. **상수 (Design 11.4)**
   `_VERIFY_MAX_TOKENS = 150`, `_VERIFY_TIMEOUT_SEC = 15.0` 일치. Design은 `15`(int)로 표기, 구현은 `15.0`(float) — anthropic SDK `timeout` 파라미터에 적합한 실질 동등.

4. **`_scan_single_theme` 통합 (Design 4.2)**
   `detected_stocks`에 `description` 필드 추가(`:190`), `session.add(detection)` 직전 검증 게이트 삽입(`:209-222`), `logger.info` 결과 기록(`:216-220`), 검증 실패 시 `continue`(`:221-222`).

5. **에러 처리 매트릭스 (Design 6.1)**
   모든 항목 구현. 단일 레코드 검증 예외는 `_verify_record`에서 별도 포획되어 `VerificationRecord.error`에 저장, 삭제 대상 제외.

6. **재검증 스크립트 (Design 4.3, 11.2)**
   `--apply`, `--theme` CLI 인자 구현, DB 백업(`investbrief.db.bak-YYYYMMDD-HHMMSS`), 리포트 경로(`docs/03-analysis/theme-cleanup-report.md`), dry-run 기본, ERROR 판정 삭제 제외 동작 확인.

7. **Clean Architecture (Design 9.1~9.3)**
   `_verify_theme_match`가 `app/services/` Application 계층에 위치, `anthropic` SDK 직접 의존(Infrastructure 취급) OK. Import 순서 준수: stdlib → 3rd party → app.

8. **컨벤션 (Design 10.1~10.4)**
   `from __future__ import annotations` 사용, `_leading_underscore` 내부 함수 네이밍, `logger.info/warning/exception` 사용 (print 없음), snake_case 파일/함수명 모두 준수.

9. **`.gitignore`** `*.db.bak-*` 패턴 추가됨 (`.gitignore:3`).

10~17. **FR-01 ~ FR-08 (Plan 기능 요구사항)** 전부 구현 확인:
- FR-01: `_verify_theme_match` 판정 반환 (`tuple[bool, str]` — Design에서 구체화)
- FR-02: 프롬프트에 테마명/키워드/뉴스(title+description)/종목명 포함
- FR-03: YES/NO 파싱 + 근거 (근거는 로깅만)
- FR-04: 예외/타임아웃 시 False
- FR-05: `_scan_single_theme` 저장 직전 검증 → YES만 저장+알림
- FR-06: `backend/scripts/verify_theme_detections.py` 일회성 스크립트
- FR-07: 리포트 저장 경로 `docs/03-analysis/theme-cleanup-report.md` (실제 생성 확인)
- FR-08: `--dry-run` 기본, `--apply` 플래그로만 삭제 수행

---

## Partial Matches (부분 일치)

없음 (post-fix).

**수정 전 초안에서는 1건 존재:**
- `backend/scripts/verify_theme_detections.py:30` 의 `from sqlalchemy.orm import selectinload` 가 파일 내 미사용 dead import였음.
- 2026-04-16 수정으로 제거 완료.

---

## Missing / Divergence

없음. 명세 대비 누락된 기능이나 동작 불일치는 발견되지 않음.

---

## Match Rate 계산

- 완전일치 17개 × 1.0 = 17.0
- 부분일치 0개 × 0.5 = 0.0
- 미일치 0개 × 0.0 = 0.0
- 합계: 17.0 / 17 = **100%**

---

## 결론

**Match Rate 100% → 리포트 단계(`/pdca report theme-accuracy-fix`) 진입 가능.**

Design 문서와 구현이 완전히 일치. 프롬프트·상수·정규식·에러 처리·스크립트 CLI 모두 설계대로 구현. Plan FR-01~FR-08 전부 충족. Clean Architecture 및 Python 3.9 호환 컨벤션 위반 없음.

**실전 검증도 완료:**
- 4개 스팟 테스트 통과 (셀트리온→NO, 현대로템→YES, 리노공업→YES, 삼천당제약→NO)
- 48건 전수 dry-run → 20건 오탐 식별 → 19건 실제 삭제 → DB 28건으로 정리
- "포장재·캔병 공급 대란 수혜" 테마 키워드 재설계 완료 (7개 범용명사 → 7개 구체 소재명)

---

## 권장 조치

1. ✅ **(완료)** 미사용 import 제거 — Match Rate 100% 달성
2. **(선택)** 백엔드 재시작 후 `/theme-scan` 수동 실행 → 새 스캔에서 검증 동작 로그 확인
3. **(다음)** `/pdca report theme-accuracy-fix` — 완료 보고서 생성

---

## 참고 파일

- 설계: `docs/02-design/features/theme-accuracy-fix.design.md`
- 계획: `docs/01-plan/features/theme-accuracy-fix.plan.md`
- 구현:
  - `backend/app/services/theme_radar_service.py`
  - `backend/scripts/verify_theme_detections.py`
  - `backend/scripts/__init__.py`
  - `.gitignore`
- 데이터 정리 리포트: `docs/03-analysis/theme-cleanup-report.md`
