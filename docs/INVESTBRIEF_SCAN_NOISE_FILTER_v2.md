# INVESTBRIEF_SCAN_NOISE_FILTER.md (v2 — 앵커 기준)

> **적용 대상: InvestBrief 레포 단독** (`feature/verified-upgrade`, `~/dev/investbrief/backend`)
> 선행 상태(이미 반영됨, 확인됨):
> - radar 추출이 `combined_text = f"{title} {description[:200]}"` 로 본문 포함
> - radar가 `from app.services.stock_name_rules import GROUP_PREFIX_NAMES` 사용
> - 추출 루프에 `if candidate in GROUP_PREFIX_NAMES: continue` 존재

> ⚠️ 본 지시서는 **라인 번호가 아니라 코드 앵커(고정점)로 위치를 지정**한다.
> 각 변경의 "찾을 코드"를 먼저 grep으로 확인한 뒤 그 자리에 적용할 것.

## 목적

본문 추출 적용 후, 뉴스 본문에서 나온 **일반 단어·숫자·금액·조사·HTML잔재 토큰**이
네이버 AC를 무차별 호출하는 문제를 해결한다. 실측 로그의 노이즈 예:

```
증시, 최근, 코스피, 수혜주로, 주가가, 삼성전자에, 시가총액은, 초집중, 부상하면서,
만2000원으로, 조6600억원으로, 조9300억에서, quot, 데이터센터에, 억달러를, 덧붙였다
```

종목당 네이버 호출 1회씩 낭비 → 스캔 지연 + 네이버 차단 위험 + 우연한 오탐.
**정확일치 필터가 뒤에 있어 최종 결과는 안전하나, "호출 전에" 쳐내지 못해 느리다.**

## 작업 (3 Phase, 독립 커밋)

---

### Phase 1: STOPWORDS를 공통 모듈에 두고 radar에 적용

**상황:** `GROUP_PREFIX_NAMES`는 `stock_name_rules.py`로 이미 옮겨졌으나, `STOPWORDS`는
아직 `theme_discovery_service.py`에만 있다. radar는 STOPWORDS를 안 쓴다.

**1-1. `stock_name_rules.py`에 STOPWORDS 추가**

먼저 현재 내용 확인:
```bash
grep -n "STOPWORDS\|GROUP_PREFIX_NAMES" app/services/stock_name_rules.py
```
`GROUP_PREFIX_NAMES`만 있고 `STOPWORDS`가 없으면, **그 파일에 STOPWORDS 블록을 추가**한다.
내용은 `theme_discovery_service.py`의 기존 STOPWORDS를 그대로 가져오되, 본문 추출로
빈출하는 항목을 보강:

```python
STOPWORDS = {
    "한국", "미국", "중국", "일본", "유럽", "코스피", "코스닥",
    "증시", "시장", "투자", "기업", "정부", "대통령", "장관", "위원회",
    "분석", "전망", "예상", "발표", "공시", "뉴스", "기사", "매출", "실적",
    "영업이익", "순이익", "주가", "주식", "종목", "거래", "상승", "하락",
    "오늘", "내일", "어제", "금주", "이번", "지난", "최근",
    # ── 본문 추출 빈출 노이즈 보강 ──
    "수혜주", "관련주", "대장주", "테마주", "급등", "급락", "강세", "약세",
    "호황", "불황", "규제", "차세대", "역시", "장악", "초집중", "주도",
    "확대", "성장", "둔화", "회복", "부진", "개선", "전반", "당분간",
}
```

**1-2. discovery는 공통 모듈을 쓰도록 정리 (중복 제거)**

`theme_discovery_service.py`에서 자체 `STOPWORDS = {...}` 정의를 찾아:
```bash
grep -n "^STOPWORDS = {" app/services/theme_discovery_service.py
```
존재하면 그 블록을 삭제하고, import 줄에 STOPWORDS를 합친다. 현재 import가
`from app.services.stock_name_rules import GROUP_PREFIX_NAMES`이면
`from app.services.stock_name_rules import GROUP_PREFIX_NAMES, STOPWORDS`로 변경.
(discovery 동작 불변 — 같은 내용을 공통 모듈에서 가져올 뿐)

> 만약 discovery가 STOPWORDS를 자체 정의 없이 이미 어딘가서 가져오고 있으면 1-2 생략.
> 핵심은 "STOPWORDS 정의가 한 곳(stock_name_rules)에만 있게" 만드는 것.

**1-3. radar에 STOPWORDS import + 차단 적용**

radar의 import 줄을 찾아:
```bash
grep -n "from app.services.stock_name_rules import" app/services/theme_radar_service.py
```
`GROUP_PREFIX_NAMES`만 import하고 있으면 STOPWORDS를 추가:
```python
from app.services.stock_name_rules import GROUP_PREFIX_NAMES, STOPWORDS
```

그리고 추출 루프의 **앵커** — `if candidate in GROUP_PREFIX_NAMES:` 줄을 찾아
(grep: `grep -n "candidate in GROUP_PREFIX_NAMES" app/services/theme_radar_service.py`),
그 줄 **바로 위**에 STOPWORDS 차단을 추가:

```python
            if candidate in STOPWORDS:            # ← 추가 (GROUP_PREFIX 차단 위에)
                continue
            if candidate in GROUP_PREFIX_NAMES:   # 기존
                continue
```

---

### Phase 2: 숫자·금액·조사·HTML잔재 토큰 차단

STOPWORDS로 못 거르는 구조적 노이즈(`조6600억원으로`, `quot`, `삼성전자에`)를
**네이버 호출 전에** 함수로 쳐낸다.

**2-1. 노이즈 판정 헬퍼 추가**

`theme_radar_service.py`에서 `STOCK_NAME_PATTERN = re.compile(...)` 줄을 찾아
(grep: `grep -n "STOCK_NAME_PATTERN = re.compile" app/services/theme_radar_service.py`),
그 **아래에** 다음을 추가 (`re`는 이미 import돼 있음):

```python
# 한글 조사 — 토큰 끝에 붙으면 종목명이 아닐 가능성 높음
_JOSA_SUFFIXES = (
    "으로", "에서", "에게", "에는", "에도", "이라", "라고", "하며", "하면서",
    "지만", "보다", "처럼", "까지", "부터", "이라는", "라는", "하는", "되는",
)

# HTML 엔티티 잔재
_HTML_JUNK = {"quot", "amp", "lt", "gt", "nbsp", "apos"}


def _is_noise_token(token: str) -> bool:
    """네이버 AC 호출 전 명백한 노이즈를 쳐낸다.

    True면 후보에서 제외(네이버 호출 안 함). 보수적 — 애매하면 False(통과).
    정확일치 필터가 뒤에 있으므로 약간 새도 최종 결과는 안전.
    목적은 "최종 판정"이 아니라 "불필요한 네이버 호출 절약".
    """
    if token.lower() in _HTML_JUNK:                       # HTML 잔재
        return True
    if any(ch.isdigit() for ch in token):                 # 숫자 포함 (금액/수치)
        return True
    if token.endswith(("원", "원으로", "억원", "달러", "달러를", "퍼센트")):  # 금액 단위
        return True
    if len(token) >= 3 and token.endswith(_JOSA_SUFFIXES): # 조사로 끝남 (3자 이상만)
        return True
    return False
```

> ⚠️ 조사 차단은 보수적으로: `len >= 3`일 때만 적용해 짧은 종목명을 보호한다.
> 정상 종목명("한화에어로스페이스" 등)은 조사로 안 끝나므로 안전. 혹시 조사로
> 끝나는 종목이 있어도 정확일치 필터가 별도로 거르니 이중 안전.

**2-2. 추출 루프에 적용**

Phase 1-3에서 만든 STOPWORDS/GROUP_PREFIX 차단 블록 **바로 아래**에 추가:

```python
            if candidate in STOPWORDS:
                continue
            if candidate in GROUP_PREFIX_NAMES:
                continue
            if _is_noise_token(candidate):        # ← 추가
                continue
            try:
                matches = await search_stocks(candidate, limit=1)
                ...
```

---

### Phase 3 (선택, 권장): 네이버 AC 결과 스캔 1회 캐시

같은 종목명이 여러 뉴스/테마에 반복 등장하면 여전히 중복 호출한다. 스캔 1회 수명의
메모리 캐시로 제거.

**3-1.** `theme_radar_service.py` 상단(모듈 레벨)에 추가:

```python
_ac_cache: dict[str, list] = {}   # 종목명 → search_stocks 결과 (스캔 1회 수명)


async def _cached_search_stocks(name: str):
    if name in _ac_cache:
        return _ac_cache[name]
    result = await search_stocks(name, limit=1)
    _ac_cache[name] = result
    return result
```

**3-2.** 추출 루프의 `await search_stocks(candidate, limit=1)`를
`await _cached_search_stocks(candidate)`로 교체.

**3-3.** `scan_all_themes` 함수 시작 부분에 `_ac_cache.clear()` 추가
(grep: `grep -n "async def scan_all_themes" app/services/theme_radar_service.py`).
매 스캔 초기화로 상장/상폐 반영.

---

## 검증

```bash
cd ~/dev/investbrief/backend

# Phase 2 — 노이즈 판정 (가상환경 python 사용)
<venv_python> -c "
from app.services.theme_radar_service import _is_noise_token
tests = ['증가하며','삼성전자에','조6600억원으로','만2000원으로','quot','데이터센터에',
         '억달러를','SK하이닉스','한화에어로스페이스','삼성전자','HBM','LS일렉트릭']
for t in tests:
    print(('제외' if _is_noise_token(t) else '통과'), t)
"
# 기대 제외: 삼성전자에, 조6600억원으로, 만2000원으로, quot, 데이터센터에, 억달러를
# 기대 통과: SK하이닉스, 한화에어로스페이스, 삼성전자, HBM, LS일렉트릭
# (증가하며는 조사 아님→통과하나, STOPWORDS/정확일치에서 별도 처리)

# Phase 1 — STOPWORDS 일원화
<venv_python> -c "
from app.services.stock_name_rules import STOPWORDS
from app.services.theme_radar_service import STOPWORDS as R
print('radar가 같은 STOPWORDS 참조:', STOPWORDS is R, '/ 개수:', len(STOPWORDS))
"

# 실측 — 수동 /theme-scan 후 ib-log의 네이버 AC 호출 수가 적용 전 대비 감소했는지
```

> `<venv_python>`은 실제 가상환경 파이썬 경로로 대체
> (예: `~/dev/investbrief/.venv/bin/python` — `python3` alias가 venv를 가로채는 경우 대비).

## 기대 효과 / 안전성

- 네이버 AC 호출 대폭 감소(로그상 노이즈가 호출의 절반 이상) → 스캔 단축, 차단 위험↓
- **검출되는 실제 종목 수는 거의 안 줄어든다** (노이즈만 제거).
  적용 후 검출이 크게 줄면 STOPWORDS/조사 차단이 과한 것 → 해당 항목 완화.
- 모든 변경은 "네이버 호출 전 사전 차단"일 뿐, 뒤의 Claude 검증·prefilter·정확일치
  필터는 그대로 → 최종 판정 안전성 불변.

## 커밋 체크리스트

- [ ] Phase 1: stock_name_rules에 STOPWORDS 추가 + radar 적용 + discovery 중복 제거 → 커밋
- [ ] Phase 2: `_is_noise_token` 추가 + 루프 적용 → 단위 테스트 통과 → 커밋
- [ ] Phase 3(선택): AC 캐시 → 커밋
- [ ] 수동 /theme-scan: ib-log 네이버 호출 수 전후 비교 + 검출 종목 수 유지 확인
