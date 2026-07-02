# INVESTBRIEF_NOISE_FILTER_PATCH.md

> **적용 대상: InvestBrief 레포 단독** (`feature/verified-upgrade`, `~/dev/investbrief/backend`)
> 선행: `INVESTBRIEF_SCAN_NOISE_FILTER_v2.md` 적용 완료 (`_is_noise_token` 함수 존재)
> venv: `~/dev/investbrief/backend/.venv/bin/python`

## 목적

노이즈 필터 단위 테스트에서 **`에`로 끝나는 조사 토큰이 통과하는** 미흡점을 보강한다.

확인된 실제 동작 (단위 테스트 결과):

| 토큰 | 현재 | 기대 |
|------|------|------|
| 삼성전자에 | **통과** ❌ | 제외 |
| 데이터센터에 | **통과** ❌ | 제외 |
| 조6600억원으로 | 제외 ✅ | 제외 |
| quot | 제외 ✅ | 제외 |
| SK하이닉스 | 통과 ✅ | 통과 |
| 한화에어로스페이스 | 통과 ✅ | 통과 |

원인: `_JOSA_SUFFIXES`에 두 글자 이상 조사(`으로`, `에서` 등)만 있고 **한 글자 조사
(`에`, `는`, `가` 등)가 없다.** `삼성전자에`, `데이터센터에`는 `에` 한 글자로 끝나
차단되지 않는다.

## 설계 — 한 글자 조사는 더 보수적으로

한 글자 조사(`에`, `는`)는 흔해서, 짧은 종목명까지 잘못 거를 위험이 크다. 그래서:

- **두 글자 이상 조사**: `len >= 3`에서 차단 (기존 유지)
- **한 글자 조사**: `len >= 4`에서만 차단 (신규 — 더 보수적)

`len >= 4` 근거: `삼성전자에`(5자), `데이터센터에`(6자)는 잡히고, `현대차`(3자) 같은
짧은 종목명은 보호된다. 한국 종목명 중 4자 이상이면서 한 글자 조사로 끝나는 경우는
드물고, 설령 있어도 **뒤의 정확일치 필터가 이중으로 막는다**(네이버에서 `삼성전자`로
매칭돼도 `삼성전자 != 삼성전자에`라 제외). 즉 이 차단은 "네이버 호출 절약"이 목적이며
최종 판정 안전성은 정확일치 필터가 보장한다.

## 작업

### 대상

`backend/app/services/theme_radar_service.py` — `_JOSA_SUFFIXES`와 `_is_noise_token`.

### 위치 확인 (먼저 grep)

```bash
cd ~/dev/investbrief/backend
grep -n "_JOSA_SUFFIXES\|_JOSA_SINGLE\|def _is_noise_token" app/services/theme_radar_service.py
```

### 1. `_JOSA_SUFFIXES` 정의 아래에 한 글자 조사 셋 추가

`_JOSA_SUFFIXES = (...)` 블록을 찾아, 그 **바로 아래**에 추가:

```python
# 한 글자 조사 — 오탐 위험 커서 len >= 4 에서만 차단 (짧은 종목명 보호)
_JOSA_SINGLE = ("에", "은", "는", "이", "가", "을", "를", "의", "와", "과", "도", "로")
```

### 2. `_is_noise_token`에 한 글자 조사 차단 추가

함수 안의 기존 두 글자 조사 차단:
```python
    if len(token) >= 3 and token.endswith(_JOSA_SUFFIXES):
        return True
```
**바로 아래**에 추가:
```python
    if len(token) >= 4 and token.endswith(_JOSA_SINGLE):   # 한 글자 조사 (4자+)
        return True
```

최종 함수 형태 (참고):
```python
def _is_noise_token(token: str) -> bool:
    if token.lower() in _HTML_JUNK:
        return True
    if any(ch.isdigit() for ch in token):
        return True
    if token.endswith(("원", "원으로", "억원", "달러", "달러를", "퍼센트")):
        return True
    if len(token) >= 3 and token.endswith(_JOSA_SUFFIXES):
        return True
    if len(token) >= 4 and token.endswith(_JOSA_SINGLE):   # ← 추가
        return True
    return False
```

## 검증

```bash
cd ~/dev/investbrief/backend
~/dev/investbrief/backend/.venv/bin/python -c "
from app.services.theme_radar_service import _is_noise_token
# (토큰, 기대결과) — 기대 제외=True
cases = [
    ('삼성전자에', True),    # ← 이번 보강으로 제외돼야 함 (5자, 에)
    ('데이터센터에', True),  # ← 6자, 에
    ('조6600억원으로', True),
    ('quot', True),
    ('억달러를', True),
    ('SK하이닉스', False),   # 통과
    ('한화에어로스페이스', False),
    ('삼성전자', False),     # 4자지만 조사로 안 끝남 → 통과
    ('HBM', False),
    ('LS일렉트릭', False),
    ('현대차', False),       # 3자 → len<4라 한글자조사 차단 미적용 → 통과(보호)
]
ok = True
for tok, expect_exclude in cases:
    got = _is_noise_token(tok)
    mark = 'OK' if got == expect_exclude else '*** FAIL ***'
    print(f'{mark}  {\"제외\" if got else \"통과\"}  {tok}')
    if got != expect_exclude: ok = False
print('\\n전체 통과' if ok else '\\n실패 케이스 있음 — 위 *** 확인')
"
```

**기대:** 모든 줄이 `OK`. 특히:
- `삼성전자에`, `데이터센터에` → 제외 (이번 보강 핵심)
- `삼성전자`(조사 없음), `현대차`(3자) → 통과 (종목명 보호 정상)

> ⚠️ 만약 `삼성전자`가 제외로 나오면 안 된다. `삼성전자`는 `자`로 끝나 조사가 아니므로
> 통과가 정상. 제외되면 `_JOSA_SINGLE`에 `자` 같은 게 잘못 들어간 것이니 확인.

## 적용 후 실측 (선택)

서버 재시작 후 `/theme-scan` → ib-log에서 `삼성전자에`, `데이터센터에` 같은 `에`로
끝나는 토큰의 네이버 AC 호출이 사라졌는지 확인. 검출 종목 수는 유지돼야 한다
(노이즈만 제거).

## 롤백 기준

적용 후 검출 종목 수가 눈에 띄게 줄면, 4자 이상 종목명이 한 글자 조사로 끝나
잘못 걸린 것일 수 있다. 그 경우:
1. 로그에서 어떤 종목이 `_is_noise_token`에 걸렸는지 확인
2. 실제 종목명이면 → `len >= 4`를 `len >= 5`로 올리거나, 해당 조사를 `_JOSA_SINGLE`에서 제거
3. 정 안 되면 한 글자 조사 차단(2번 추가분)만 제거 → 정확일치 필터가 어차피 막으므로 안전

## 커밋 체크리스트

- [ ] `_JOSA_SINGLE` 추가 + `_is_noise_token`에 `len>=4` 차단 추가
- [ ] 검증 스크립트 전체 `OK` (특히 삼성전자에·데이터센터에 제외, 삼성전자·현대차 통과)
- [ ] 커밋
- [ ] (선택) 서버 재시작 후 /theme-scan 실측 — 에-종료 토큰 호출 감소 + 검출 수 유지
