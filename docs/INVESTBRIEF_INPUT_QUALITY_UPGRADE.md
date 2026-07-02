# INVESTBRIEF_INPUT_QUALITY_UPGRADE.md

> **적용 대상: InvestBrief 레포 단독**
> 선행 조건: `INVESTBRIEF_INTEGRITY_FIXES.md` 적용 완료 (TZ 헬퍼·GROUP_PREFIX 공통 모듈 사용)

## 목적

테마 스캔의 **종목 추출 정확도(재현율)**를 높인다. 현재 `_scan_single_theme`은
뉴스 **제목만** 보고 종목명 토큰을 뽑아 네이버 AC로 역추적하는데, 이 경로는
(a) 본문에만 등장하는 수혜주를 놓치고 (b) 토큰→코드 역추적이 부정확하다.

이미 수집 중이나 안 쓰던 두 데이터를 추출 소스로 추가한다:

1. **뉴스 본문(description)** — `_fetch_naver_news`가 이미 200자까지 가져온다.
   추가 API 호출 0. 제목에 없고 본문에만 나오는 종목을 회수.
2. **DART 공시** — `dart_collector`가 `stock_code`를 **직접** 준다(역추적 불필요,
   정확도 ~100%). 수주·계약체결 등 🟢 호재 공시의 종목을 1차 신호로 추가.

> 이 작업은 측정 결과와 무관하게 "더 정확한 입력을 쓰는" 개선이라 트레이드오프가 없다.
> (검증 프롬프트 보수화처럼 통과 종목을 *줄이는* 변경은 측정 데이터 축적 후 별도 진행.)

## 적용 순서 (각 Phase 독립 커밋)

| Phase | 항목 | 효과 |
|-------|------|------|
| 1 | 뉴스 본문(description)에서도 종목 추출 | 본문 전용 수혜주 회수 |
| 2 | DART 🟢 공시를 종목 추출 소스로 추가 | 정확한 1차 신호 (코드 직접 제공) |

**Phase 순서대로 적용 → 검증 → 커밋.** Phase 1만 먼저 해도 독립적으로 효과 있음.

## 전체 규칙

- CLAUDE.md Simplicity First / Surgical Changes 준수. 명시된 파일만 수정.
- DB 스키마 변경 없음.
- **기존 안전장치는 그대로 통과시킨다** — 추출한 종목도 Claude 검증 + prefilter +
  GROUP_PREFIX 차단(INTEGRITY_FIXES Phase 3)을 동일하게 거친다. 추출 소스만 늘릴 뿐
  검증을 우회하지 않는다.
- 검증 명령의 `backend` 경로는 실제 InvestBrief 레포 경로로 조정.

---

## Phase 1: 뉴스 본문(description)에서도 종목 추출

### 1-1. 현황

`theme_radar_service._scan_single_theme` (약 222행):

```python
    for news in all_news:
        title = news.get("title", "")
        candidates = set(STOCK_NAME_PATTERN.findall(title))   # title만
        ...
```

`news`에는 `description`(본문 200자)이 이미 들어 있으나 추출에 안 쓰인다.

### 1-2. 변경 — title + description 합쳐서 추출

```python
    for news in all_news:
        title = news.get("title", "")
        description = news.get("description", "")
        # 제목 + 본문 합쳐서 종목 후보 추출 (본문 전용 수혜주 회수)
        search_text = f"{title} {description}"
        candidates = set(STOCK_NAME_PATTERN.findall(search_text))
        for candidate in candidates:
            if len(candidate) < 2:
                continue
            if candidate in GROUP_PREFIX_NAMES:   # INTEGRITY_FIXES Phase 3에서 추가됨
                continue
            ...
            stock_code = m["stock_code"]
            if stock_code not in detected_stocks:
                detected_stocks[stock_code] = {
                    "stock_code": stock_code,
                    "stock_name": candidate,
                    "headline": title,            # headline은 title 유지 (알림 가독성)
                    "description": description,
                    "matched_keyword": news["matched_keyword"],
                    "url": news.get("link", ""),
                }
```

**주의:**
- `headline`은 **title 그대로 유지** — 텔레그램 알림에 본문 200자가 헤드라인으로
  나가면 지저분하다. 추출에만 본문을 쓰고, 표시는 제목.
- `GROUP_PREFIX_NAMES` 차단은 INTEGRITY_FIXES Phase 3에서 이미 추가됐어야 한다.
  안 돼 있으면 그 지시서를 먼저 적용할 것.
- 본문에서 토큰이 늘면 네이버 AC 호출도 는다. INTEGRITY_FIXES에 AC 캐시가 없으므로
  (부록 P2 항목이었음), 본 Phase로 호출량이 체감 증가하면 그때 캐시를 검토.
  현재는 종목당 1회 `search_stocks(limit=1)` + 정확일치 필터라 오탐 위험은 낮다.

### 1-3. 검증

```bash
cd backend && python3 -c "
from app.services.theme_radar_service import STOCK_NAME_PATTERN
title = 'AI 데이터센터 전력 수요 급증'
desc = '관련주로 LS일렉트릭과 HD현대일렉트릭이 부각되고 있다'
print('제목만:', set(STOCK_NAME_PATTERN.findall(title)))
print('제목+본문:', set(STOCK_NAME_PATTERN.findall(f'{title} {desc}')))
"
# 기대: 제목만으로는 종목 0개, 제목+본문으로는 'LS일렉트릭','HD현대일렉트릭' 등장
```

수동 `/theme-scan` 1회 실행 후 로그에서 검출 종목 수가 이전 대비 늘었는지 확인.

---

## Phase 2: DART 🟢 공시를 종목 추출 소스로 추가

### 2-1. 핵심 — DART는 stock_code를 직접 준다

`dart_collector.get_today_disclosures`는 각 공시에 대해
`{corp_name, stock_code, title, importance}`를 반환한다. 뉴스처럼 토큰→코드 역추적이
필요 없다. `importance == "🟢"`(수주/계약체결/자사주 등 호재)인 공시의 `stock_code`를
바로 쓰면 된다.

### 2-2. 테마 매칭 방식

DART 공시는 키워드 기반 뉴스 검색과 결이 다르다. 공시 제목(`report_nm`)을 해당 테마의
키워드와 매칭해서, **테마 키워드가 공시 제목에 포함된** 호재 공시만 추출 소스로 쓴다.

`_scan_single_theme`에 DART 추출 블록을 **뉴스 추출 다음에** 추가:

```python
    # ── 뉴스 추출 (Phase 1까지 적용된 기존 로직) ──
    # detected_stocks가 채워진 상태에서 이어서:

    # ── DART 🟢 호재 공시 추출 (테마 키워드가 공시 제목에 포함된 것만) ──
    try:
        from app.collectors import dart_collector
        disclosures = await dart_collector.get_today_disclosures(target_date=scan_date)
    except Exception:
        logger.exception("[scan_single_theme] DART 수집 실패 — 뉴스만으로 진행: %s", theme.name)
        disclosures = []

    for disc in disclosures:
        if disc.get("importance") != "🟢":   # 호재 공시만
            continue
        stock_code = (disc.get("stock_code") or "").strip()
        if not stock_code or len(stock_code) != 6:
            continue   # 비상장/코드 없는 공시 제외

        disc_title = disc.get("title", "")
        # 이 테마의 키워드가 공시 제목에 포함되는지
        matched_kw = next((k for k in keywords if k and k in disc_title), None)
        if not matched_kw:
            continue

        if stock_code not in detected_stocks:
            detected_stocks[stock_code] = {
                "stock_code": stock_code,
                "stock_name": disc.get("corp_name", ""),
                "headline": f"[공시] {disc_title}",   # 출처 표시
                "description": "",
                "matched_keyword": matched_kw,
                "url": "",   # DART 공시 URL은 rcept_no로 구성 가능하나 선택
                "source_type": "dart",   # 추적용 (선택)
            }
```

**주의:**
- `_scan_single_theme` 시그니처에 `scan_date`가 이미 있다(기존 인자). DART 조회에 그대로 전달.
- DART가 준 `stock_code`/`corp_name`은 정확하므로 **네이버 AC 역추적·정확일치 필터를
  거치지 않는다**(이미 정확). 단, 그 후 Claude 검증 + prefilter는 동일하게 통과한다.
- `corp_name`(예: "에이치디현대일렉트릭")과 뉴스 추출의 `stock_name`(예: "HD현대일렉트릭")이
  표기 다를 수 있으나, dedup 키는 `stock_code`라 충돌 없음(같은 코드면 뉴스가 선점, DART는 skip).
- 🟢 외(🔴 악재, ⚪ 일반)는 추출 안 함. 수주·계약 같은 호재만 수혜주 신호로 의미 있음.

### 2-3. DART 공시 URL 채우기 (선택)

`headline`에 출처만 표시하고 url을 비워뒀는데, 원하면 DART 공시 링크를 구성:

```python
                "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={disc.get('rcept_no','')}",
```

`get_today_disclosures` 반환에 `rcept_no`가 이미 있으나, 현재 dart_collector가
detected_stocks로 넘기는 dict엔 없으니 위에서 `disc.get("rcept_no")` 접근 가능
(disclosures 원본 dict에는 있음).

### 2-4. 검증

```bash
# DART 수집 자체가 되는지 (API 키 필요)
cd backend && python3 -c "
import asyncio
from app.collectors import dart_collector
async def main():
    d = await dart_collector.get_today_disclosures()
    greens = [x for x in d if x.get('importance')=='🟢']
    print(f'전체 공시 {len(d)}건, 🟢 호재 {len(greens)}건')
    for g in greens[:5]:
        print(f\"  {g['corp_name']}({g['stock_code']}): {g['title']}\")
asyncio.run(main())
"
# 기대: 🟢 공시에 stock_code가 채워져 나옴 (비상장은 빈 문자열)

# 수동 /theme-scan 후 로그에서 [공시] 출처 종목이 검출에 포함됐는지 확인
```

---

## 효과 측정 (중요 — 본 고도화의 검증 방법)

본 작업은 "재현율↑"이라 **검출 종목 수가 늘어난다.** 그 자체는 의도된 동작이나,
"늘어난 게 좋은 종목이냐"는 별도로 봐야 한다. 단, 그 측정은 **이력 데이터가 쌓인 뒤** 가능하다:

- StockAI `buy_alerts` 이력 보존(STOCKAI_BUY_ALERT_HISTORY_RETENTION 적용)으로 추천 이력이 쌓이고
- InvestBrief `theme_alert_candidates`의 D+30 성적 + (벤치마크 수정 후) 코스피 대비 초과수익으로
- "본문/DART 출처 종목"이 "제목 출처 종목"보다 성적이 나은지 사후 비교

→ 그래서 Phase 2의 `source_type: "dart"` 태그를 남겨두면 나중에 출처별 성적 비교가 가능하다.
   (theme_alert_candidates에 source_type 컬럼 추가는 측정 인프라 작업으로 별도 진행)

**지금은 입력을 정확하게 만드는 데 집중하고, 효과 검증은 데이터 축적 후로 미룬다.**

## 부록 (P2 — 범위 밖, 기록용)

- 네이버 AC 토큰→코드 캐시 (본문 추출로 호출 증가 시)
- theme_alert_candidates에 `source_type`(news_title / news_body / dart) 컬럼 추가 — 출처별 성적 측정용
- 검증 프롬프트 "신규 촉매" 축 (통과 종목 *감소* 변경 — 측정 데이터 축적 후)

## 커밋 체크리스트

- [ ] Phase 1: title+description 추출 + headline은 title 유지 → 검증 → 커밋
- [ ] Phase 2: DART 🟢 공시 stock_code 직접 추출 + 테마 키워드 매칭 → 검증 → 커밋
- [ ] 수동 /theme-scan 1회: 검출 종목 수 증가 + [공시] 출처 종목 포함 확인
- [ ] 기존 Claude 검증/prefilter/GROUP_PREFIX 차단이 추가분에도 동일 적용되는지 로그 확인
