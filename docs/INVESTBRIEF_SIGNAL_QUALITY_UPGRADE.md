# INVESTBRIEF_SIGNAL_QUALITY_UPGRADE

> 지시서 F — 테마 레이더 검증 엄격화 · 뉴스 신선도 필터 · 재료 중요도 판정
> 대상: Claude Code / InvestBrief backend (Oracle Cloud ARM VM)
> 작성 기준일: 2026-07-02
> 우선순위: **P2** — StockAI와 독립 배포 가능. 단, StockAI 지시서 E(갭 가드)와 함께 적용될 때 승률 개선 효과가 완성됨 (E가 "가격이 이미 반영됨"을 막고, F가 "재료가 이미 낡음"을 막는다 — 같은 문제의 양끝).
> 선행: 없음 (InvestBrief 단독).

---

## 1. 개요 (Overview)

StockAI로 매일 후보를 공급하는 것은 08:10 `theme_radar_service`인데, 코드 확인 결과 검증 체계가 **이원화**되어 있다:

- `theme_discovery_service`(주간 자동발굴): "애매하면 보수적으로 NO" + 지주사 오매핑 차단 — 엄격 ✅
- `theme_radar_service`(매일, **StockAI 실공급 라인**): "애매하면 관대하게 YES" — 관대 ❌

즉 엄격 검증은 일주일에 한 번 도는 보조 라인에 있고, 실탄이 나가는 라인은 관대하다. 추가로 radar의 뉴스 수집(`_scan_single_theme` → `_fetch_naver_news`)은 **pubDate 필터가 없어** 며칠 지난 기사도 신규 감지로 잡히며, 검증 프롬프트는 "테마 관련성"만 묻고 "이 재료가 새로운가 / 실적에 유의미한가"는 묻지 않는다.

본 지시서는 radar 라인을 discovery 수준으로 엄격화하고, 신선도(24시간)·중요도(materiality) 축을 추가하며, 프롬프트 버전을 태깅해 변경 효과를 기존 30/60/90일 수익률 추적 인프라로 측정 가능하게 만든다. 목표는 **후보 수를 줄이더라도 StockAI에 도달하는 신호의 타율을 올리는 것.**

---

## 2. 배경 및 문제 정의 (Background & Problem Statement)

### 관측된 사실 (코드 기준: theme_radar_service.py, news_collector.py)
- radar 검증 프롬프트 판정 기준: "애매하면 관대하게 YES (다만 사업 영역이 명백히 다르면 NO)".
- discovery 프롬프트에는 "애매하면 보수적으로 NO" + 주요 그룹명 단독 등장 시 지주사 오매핑 차단 목록이 이미 존재 — **radar에 이식되지 않음**.
- `_scan_single_theme`은 `_fetch_naver_news(keyword)` (display=10, sort=date) 결과를 **pubDate 검사 없이** 전부 사용. 네이버 sort=date라도 키워드가 한산하면 수일 전 기사가 상위에 옴.
- 종목 추출은 뉴스 **제목** 정규식 매칭 → 제목에 등장하는 유명 종목(이미 오른 대장주) 편향.
- 프리필터(RSI<70, MA20 +30%, 5일 +30%, 시총 500억)가 "이미 폭등"은 걸러주지만, "재료는 낡았는데 아직 안 오른(안 오를) 종목"은 통과함.
- 검증 통과 후 14일 재검증 금지 윈도우(DETECTION_WINDOW_DAYS)는 **중복 알림 방지**용이지 신선도 판정이 아님.

### 파생 영향 (StockAI 3~6월 성과와의 연결)
- StockAI 승률 38.9%. 지시서 D(페이오프)·E(갭 가드) 이후에도 손익분기 승률 44.4%를 넘으려면 신호 원천의 정밀도 개선이 필요.
- 관대한 YES → 후보 과다 → StockAI 배치의 즉시제외/D등급 비율 상승 → Claude API 비용과 분석 시간 낭비 (프리필터 도입 목적이 무색해짐).

---

## 3. 근본 원인 분석 (Root Cause Analysis)

- **원인 ①**: radar와 discovery의 프롬프트가 별도 상수로 관리되어, discovery에만 적용된 개선(보수적 NO, 지주사 차단)이 radar에 전파되지 않음 — 프롬프트 이원화의 전형적 drift.
- **원인 ②**: 뉴스 신선도는 "수집 시점" 문제인데 검증은 "내용" 문제로만 설계됨 — pubDate가 수집기에서 파싱됨에도(`_parse_pub_date` 존재) radar 경로에서 사용되지 않음.
- **원인 ③**: 검증 프롬프트의 질문이 1축(관련성)뿐 — "관련은 있으나 낡았거나 사소한 재료"가 전부 YES로 통과.

---

## 4. 목표 및 비목표 (Goals / Non-Goals)

### 목표
1. radar 검증을 discovery와 동일한 엄격 기준으로 통일 (단일 프롬프트 빌더로 통합 — 재발 방지).
2. 신선도 필터: 발행 24시간(설정 가능) 초과 뉴스는 감지 원천에서 제외.
3. 중요도 판정: 프롬프트에 MATERIALITY 축 추가, LOW는 탈락.
4. `prompt_version` 태깅으로 변경 전/후 알림 성과(기존 30/60/90일 추적)를 분리 측정.

### 비목표
- 뉴스 본문 크롤링 확대(제목+description → 전문) — 비용 대비 효과 검증 후 별도.
- 종목 추출을 제목 정규식에서 본문 NER로 교체 — 동일하게 후속.
- 테마 키워드 자체의 품질 개선(테마 등록 후행성) — 운영 이슈로 별도 논의.

---

## 5. 변경 사항 상세 — 검증 프롬프트 통합·엄격화

### 5.1 단일 프롬프트 빌더 (신규 `app/services/verify_prompts.py`)

radar/discovery가 각자 보유한 프롬프트 상수를 제거하고 공용 빌더로 통합:

```python
def build_theme_verify_prompt(theme_name, matched_keyword, stock_name,
                              title, description, pub_date_str) -> str:
```

프롬프트 요구 응답 형식 (기존 VERDICT/REASON에 1축 추가):

```
VERDICT: YES|NO
MATERIALITY: HIGH|MEDIUM|LOW
REASON: (1줄 근거)
```

판정 기준 (프롬프트에 명시):
- 종목의 **주력 사업**이 테마와 직접 관련 + 뉴스가 그 관련성의 **새 재료**면 YES.
- **애매하면 보수적으로 NO** (radar도 discovery 기준으로 통일).
- 지주사/그룹명 오매핑 차단: discovery의 주요 그룹명 차단 목록을 빌더로 이동, 양쪽 공용.
- 단순 언급(리스트성 기사, 시황 나열)·사업부 일부만 관련·경쟁사 뉴스에 이름만 등장 → NO.
- MATERIALITY: 본업 매출/이익에 유의미한 영향이 추정되면 HIGH/MEDIUM, 기대감·간접 수혜·규모 불명이면 LOW.
- 기존 "뉴스 본문을 신뢰하지 말고 알고 있는 주력 사업 기준 판정" 지침 유지.

### 5.2 파서 확장 (`ai_verifier.py`)

- `_MATERIALITY_RE` 추가. 반환을 `(verdict, materiality, reason)`으로 확장하되 **기존 호출부 호환** 유지 (materiality 미파싱 시 None → 호출측 보수 처리).
- radar 정책: `verdict is not True` → 탈락 (기존 fail-closed 유지), `materiality == "LOW"` → 탈락, `materiality is None` (파싱 실패) → **통과** (신규 축의 파싱 불안정이 전체를 막지 않도록 — 2주 관찰 후 fail-closed 전환 검토).

### 5.3 max_tokens 조정

응답 1줄 늘었으므로 DEFAULT_MAX_TOKENS 150 → 200.

---

## 6. 변경 사항 상세 — 신선도 필터

### 6.1 `_scan_single_theme` 수집 단계

```python
FRESHNESS_HOURS = settings.theme_news_freshness_hours  # 기본 24

for item in news_items:
    pub = _parse_pub_datetime(item.get("published"))   # 기존 _parse_pub_date의 datetime 버전
    if pub is None:
        keep + 로그 (fail-open — 파싱 실패로 정상 뉴스 유실 방지)
    elif now_kst - pub > timedelta(hours=FRESHNESS_HOURS):
        drop + debug 로그 "stale news skipped"
```

- 24시간 기준 근거: 08:10 스캔이 잡아야 할 것은 "전일 장 마감 후 ~ 당일 아침" 재료. 그 이전 재료는 전일 장에서 이미 소화됨. 주말 경과분을 고려해 **월요일 스캔만 72시간**으로 확장 (금·토·일 재료 수용).
- 프롬프트에도 발행일을 전달(`pub_date_str`)해 Claude가 재탕 판단에 참고하게 함.

### 6.2 통계 로깅

스캔 완료 로그에 `fresh=N / stale_dropped=N` 추가 — 필터가 실제로 무엇을 버리는지 관측 가능하게.

---

## 7. 변경 사항 상세 — 효과 측정 (prompt_version 태깅)

- `ThemeDetection`·`ThemeScanResult`(또는 후보 저장 지점)에 `prompt_version VARCHAR(8)` 추가, 본 지시서 적용 시 `"v2"` 기록 (기존 데이터는 NULL = v1).
- 기존 18:05/18:15/18:25 크론(30/60/90일 알림 수익률 추적)과 월간 리포트가 이 필드로 v1/v2 그룹 비교를 낼 수 있도록 analytics 집계에 group-by 축 추가.
- 판정 기준(리포트에 자동 표기): v2 알림 30건 누적 시점에 v1 대비 30일 평균 수익률·양(+)비율 비교. **후보 수 감소는 실패가 아님** — 타율(양의 비율)이 지표.

---

## 8. DB 스키마 / 마이그레이션

- `theme_detections`(및 스캔 결과 테이블)에 `prompt_version` 추가. InvestBrief의 마이그레이션 관행(Alembic 유무)을 확인 후 그 방식대로 — 없으면 스키마 변경 스크립트 + README 기록.
- Neon/SQLite 이중 환경이면(migrate_sqlite_to_neon.py 존재) **운영 DB가 어느 쪽인지 확인 후** 해당 DB에 적용.

---

## 9. 연동 영향 확인 (StockAI Pull API)

- `/api/internal/theme-scan/results` 응답 스키마는 **변경하지 않는다** (StockAI `investbrief_client.py`의 pydantic 모델과 호환 유지). prompt_version·materiality는 InvestBrief 내부 필드 — 응답에 추가하려면 optional 필드로만 (StockAI 모델이 unknown 필드를 무시하는지 확인).
- 후보 수 감소로 "스캔 결과 0건" 날이 늘 수 있음 — StockAI daily_batch는 0건을 정상 처리(로그 후 종료)하므로 무해. 다만 텔레그램 스캔 요약에 "검증 탈락 사유 분포"를 추가해 0건이 "필터 정상 작동"인지 "수집 장애"인지 구분 가능하게.

---

## 10. 테스트 계획

1. 프롬프트 빌더 단위: radar/discovery 양쪽에서 동일 빌더 사용 확인 (기존 상수 삭제 grep 검증).
2. 파서: VERDICT+MATERIALITY 정상 / MATERIALITY 누락(구형 응답) → None / 파싱 실패 케이스.
3. 신선도: 12시간 전 기사 keep / 30시간 전 drop / pubDate 파싱 실패 keep / 월요일 72시간 분기.
4. 정책 조합: YES+HIGH 통과, YES+LOW 탈락, YES+None 통과, NO+HIGH 탈락.
5. 통합(스테이징 또는 수동 스캔 1회): 실제 스캔에서 stale_dropped·materiality 탈락 로그 관측, ThemeDetection에 prompt_version='v2' 기록 확인.
6. StockAI 연동 회귀: 스캔 후 StockAI에서 `get_theme_scan_results` 호출이 기존과 동일하게 파싱됨.

---

## 11. 배포 및 롤백

- Oracle VM 배포 절차는 기존 관행(docker/systemd) 준수. 배포 후 다음 영업일 08:10 스캔 로그로 실측.
- 롤백: config 2개 — `theme_verify_strict: bool`(false면 구 프롬프트 경로), `theme_news_freshness_hours: int`(0이면 필터 무효) — 로 즉시 완화 가능하게 구현. 코드 롤백 불필요.
- 첫 주 관찰 지표: 일평균 검증 통과 종목 수 (기존 대비 30~60% 감소가 예상 범위, **90% 이상 급감하면 과차단** — freshness 완화부터 검토).

---

## 12. 완료 기준 (Definition of Done)

- [ ] radar와 discovery가 단일 프롬프트 빌더 사용 (프롬프트 상수 중복 0)
- [ ] radar 판정이 "애매하면 NO" + 지주사 차단 + MATERIALITY LOW 탈락으로 동작 (로그 실증)
- [ ] 24시간(월 72시간) 초과 뉴스가 감지 원천에서 제외되고 stale_dropped 카운트가 로그에 남음
- [ ] ThemeDetection에 prompt_version='v2' 태깅
- [ ] 30/60/90일 추적 리포트가 v1/v2 분리 집계 제공
- [ ] StockAI daily_batch가 변경 후에도 무수정으로 정상 동작 (0건 포함)
- [ ] 운영 2주 후: 통과 후보 수·탈락 사유 분포·(표본 축적 시) v2 타율을 요약한 관찰 노트 1건 작성

---

## 구현 노트 (2026-07-02, F-패치 정정)

- **radar/discovery 프롬프트 통합은 미적용이 타당** — discovery의 프롬프트는 "종목이 특정 이슈로 시장 주목을 받는가"를 판별하는 **테마 후보 발굴용**이고, radar는 "이 종목이 이 테마의 실질 수혜주인가"를 판정하는 **종목 검증용**으로 용도가 다르다. radar 프롬프트만 `verify_prompts.build_theme_verify_prompt` 빌더로 이관했고 discovery는 자기 프롬프트를 유지한다. 후속 세션은 이 둘을 억지로 통합하지 말 것.
- **F-패치(prompt_version 분리 집계)**: 수익률 집계 대상은 `ThemeAlertCandidate`이므로 `prompt_version`을 해당 테이블에 추가(지시서 F-패치 §6의 "스키마 변경 없음"은 정정 — ThemeDetection이 아닌 ThemeAlertCandidate에 컬럼 필요). 월간 리포트에 v1/v2 비교 블록 + v2 성숙 30건 미만 유보 표기.
