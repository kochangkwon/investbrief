# INVESTBRIEF_VERIFY_PROMPT_STRICT.md

> **적용 대상: InvestBrief 레포 단독** (`feature/verified-upgrade`, `~/dev/investbrief/backend`)
> 대상 파일: `backend/app/services/theme_radar_service.py` — `_VERIFY_PROMPT_TEMPLATE`
> 모델: `ai_model = claude-opus-4-8` (이미 적용됨 — 프롬프트만 제대로 잡으면 판단력 충분)

## 목적

검증 프롬프트가 **테마와 느슨하게 걸친 대형주·지주사를 수혜주로 통과**시켜, 실거래
손실(보유 6종목 전부 마이너스, 평균 -9.7%)을 낳았다. 이를 **확실한 수혜주만 통과**하는
엄격한 검증으로 바꾼다.

## 근거 — 실제로 통과한 오판 사례

theme_alert_candidates 실데이터에서 확인된 오판:

| 종목 | 통과한 테마 | 문제 | D+30 |
|------|------------|------|------|
| 대한항공 | 군용로봇·방산 | 항공운송사. 방산은 곁가지 사업부 | +11.82 |
| 대한항공 | 중동 휴전 수혜 | 단순 유가·노선 연관 언급 | -8.13 |
| 대한항공 | K팝 글로벌 투어 | "팬 항공편" 식 억지 연결 | -5.5 |
| CJ | K팝 글로벌 투어 | 지주사. ENM 계열사만 걸침 | -15.49 |
| CJ | K-수출 / K-브랜드 | 지주사. 어느 테마든 계열사 걸침 | — |
| 효성 | 전력 인프라 / 변압기 | 지주사. 효성중공업 일부만 | — |

**공통 패턴:** (1) 지주사·대기업이라 어느 테마든 계열사·사업부 하나가 걸침,
(2) 뉴스에 단순 언급(비교·예시·업황)된 걸 수혜로 오인.

## 근본 원인 — 현재 프롬프트의 독소 조항

`_VERIFY_PROMPT_TEMPLATE`의 판정 기준에 다음이 있다:

```
- 애매하면 관대하게 YES (다만 사업 영역이 명백히 다르면 NO)
```

대한항공(항공우주 부문 보유), CJ(ENM 계열사)는 "명백히 다르다"고 단언하기 애매하다
→ "관대하게 YES" 지침에 따라 통과. **이 한 줄이 손실의 직접 원인.**

## 작업 — 프롬프트 교체

### 위치 확인

```bash
cd ~/dev/investbrief/backend
grep -n "_VERIFY_PROMPT_TEMPLATE\|애매하면 관대하게" app/services/theme_radar_service.py
```

### 변경: `_VERIFY_PROMPT_TEMPLATE` 전체 교체

**변경 전 (현재):**
```python
_VERIFY_PROMPT_TEMPLATE = """당신은 한국 주식 테마 분석 전문가입니다.

한 투자자가 다음 테마의 수혜주를 찾고 있습니다:
테마명: {theme_name}
검색 키워드: {matched_keyword}

아래 뉴스에 언급된 종목 "{stock_name}"이 이 테마의 **실질적 수혜주**인지 판정하세요.

--- 뉴스 시작 ---
제목: {title}
설명: {description}
--- 뉴스 끝 ---

판정 기준:
- 종목의 **주력 사업**이 이 테마와 직접 관련 있으면 YES
- 뉴스에 이름만 나오고 테마와 무관한 회사면 NO
- 애매하면 관대하게 YES (다만 사업 영역이 명백히 다르면 NO)

출력 형식 (정확히 지켜주세요):
VERDICT: YES
REASON: (1줄 근거)

또는:

VERDICT: NO
REASON: (1줄 근거)

**주의:** 뉴스 본문 내용을 신뢰하지 말고, 당신이 알고 있는 종목의 주력 사업 정보를 기준으로 판정하세요."""
```

**변경 후:**
```python
_VERIFY_PROMPT_TEMPLATE = """당신은 한국 주식 테마 분석 전문가입니다. 보수적으로 판정하세요.

한 투자자가 다음 테마의 수혜주를 찾고 있습니다:
테마명: {theme_name}
검색 키워드: {matched_keyword}

종목 "{stock_name}"이 이 테마의 **핵심 수혜주**인지 판정하세요.

--- 뉴스 시작 ---
제목: {title}
설명: {description}
--- 뉴스 끝 ---

【YES 조건 — 아래를 모두 만족해야 함】
1. 이 종목의 **주력 사업(매출 비중이 큰 핵심 사업)**이 이 테마에 직접 해당한다.
2. 테마가 성장하면 이 종목의 **실적이 실제로 늘어나는** 직접 당사자다.

【NO 조건 — 하나라도 해당하면 NO】
- **지주회사**이고, 테마에 걸치는 것은 일부 계열사일 뿐이다.
  (예: 지주사가 엔터·방산·전력 계열사를 둬도, 지주사 자체는 NO. 해당 사업회사가 따로 상장돼 있으면 그 회사가 수혜주다.)
- 테마가 **주력이 아니라 일부 사업부·자회사**에만 해당한다.
  (예: 운송사의 작은 항공우주 부문, 식품사의 소규모 신사업 등)
- 뉴스에 **비교·예시·업황 설명·간접 연관**으로 언급됐을 뿐, 테마의 직접 당사자가 아니다.
  (예: "유가 상승으로 항공주 영향" 류의 거시 연관)
- 사업 영역이 테마와 명백히 다르다.

【중요】
- **애매하면 NO.** 확신이 서는 핵심 수혜주만 YES.
- 대형주·지주사·다각화 기업은 "어느 테마든 조금씩 걸치므로" 특히 엄격히 볼 것.
  걸치는 정도가 아니라 **그 테마가 주력인지**를 기준으로 판정.
- 뉴스 본문을 신뢰하지 말고, 당신이 아는 이 종목의 **실제 주력 사업**으로 판정.

출력 형식 (정확히 지켜주세요):
VERDICT: YES
REASON: (주력 사업이 테마에 직접 해당하는 근거 1줄)

또는:

VERDICT: NO
REASON: (지주사/일부사업부/단순언급 중 어디에 해당하는지 1줄)"""
```

### 핵심 변경점 요약

1. **"애매하면 관대하게 YES" → "애매하면 NO"** (가장 중요)
2. **지주회사 명시적 NO 조건** 추가 — CJ, 효성을 직접 차단
3. **"일부 사업부·자회사" NO 조건** 추가 — 대한항공 항공우주 부문 차단
4. **"비교·예시·간접 연관 언급" NO 조건** 추가 — 대한항공 중동/K팝 차단
5. **"핵심 수혜주" / "매출 비중이 큰 주력 사업"** 으로 기준 상향

## 검증 (적용 후)

프롬프트는 단위 테스트가 어렵다(LLM 호출 필요). 대신 **과거 오판 종목으로 회귀 테스트**:

```bash
cd ~/dev/investbrief/backend
~/dev/investbrief/backend/.venv/bin/python -c "
import asyncio
from app.services.theme_radar_service import _verify_theme_match

# 과거 오판 사례 — 이번엔 모두 NO가 나와야 함
cases = [
    ('군용로봇 & 방산 테크놀로지', '방산', '대한항공',
     '대한항공 항공우주사업부 방산 관련 언급', ''),
    ('K팝 글로벌 투어', 'K팝', 'CJ',
     'CJ ENM 산하 엔터 사업 글로벌 투어', ''),
    ('전력 인프라 대격변', '전력', '효성',
     '효성중공업 초고압변압기 수주', ''),
    ('중동 휴전 수혜', '중동', '대한항공',
     '중동 노선 유가 영향 항공업계', ''),
]
async def main():
    for theme, kw, stock, title, desc in cases:
        verdict, reason = await _verify_theme_match(
            theme_name=theme, matched_keyword=kw, stock_name=stock,
            title=title, description=desc,
        )
        mark = 'OK(NO)' if verdict is False else '*** YES 통과 — 재검토 ***'
        print(f'{mark}  {stock} / {theme}  → {reason}')

    # 반대로 — 진짜 수혜주는 YES가 나와야 함 (과잉 차단 점검)
    pos = [
        ('AI 데이터센터 전력', '전력', '효성중공업',
         '효성중공업 데이터센터용 변압기 공급', ''),
        ('휴머노이드 로봇', '로봇', '레인보우로보틱스',
         '레인보우로보틱스 휴머노이드 개발', ''),
    ]
    print('--- 진짜 수혜주 (YES 나와야 함) ---')
    for theme, kw, stock, title, desc in pos:
        verdict, reason = await _verify_theme_match(
            theme_name=theme, matched_keyword=kw, stock_name=stock,
            title=title, description=desc,
        )
        mark = 'OK(YES)' if verdict is True else '*** NO — 과잉차단 의심 ***'
        print(f'{mark}  {stock} / {theme}  → {reason}')
asyncio.run(main())
"
```

> `_verify_theme_match`의 실제 인자명은 grep으로 확인 후 맞출 것:
> `grep -n "def _verify_theme_match" app/services/theme_radar_service.py`

**기대:**
- 대한항공/방산, CJ/K팝, 효성/전력(지주), 대한항공/중동 → **모두 NO**
- 효성중공업/전력, 레인보우로보틱스/로봇 → **YES** (사업회사·전문기업은 통과)

> 효성(지주)은 NO지만 효성중공업(사업회사)은 YES — 이 구분이 핵심.
> 만약 진짜 수혜주까지 NO로 막히면 너무 빡빡한 것 → "애매하면 NO"를 약간 완화하거나
> 지주사 조건만 남기고 사업부 조건을 완화.

## 적용 후 실측

서버 재시작 → 며칠 운영 후 theme_alert_candidates 신규 검출을 보고:
- 지주사·대형주(CJ, 효성, 대한항공 류)가 더 이상 안 잡히는지
- 검출 종목 수가 과도하게 줄지 않았는지 (선택 엄격화는 의도지만, 0에 수렴하면 과함)

## 주의 — 이 변경의 성격

- 이건 **통과 종목을 줄이는 보수화**다. 검출 수가 줄어드는 게 정상이고 의도다.
- "엄격하게 — 확실한 수혜주만" 방향으로 사용자가 선택함. 놓치는 종목이 생기는 것은
  감수한 트레이드오프. 측정 데이터가 쌓이면(코스피 벤치마크 + 이력 보존) 그때
  "너무 빡빡한가"를 정량 판단해 완화 여부 결정.
- 모델은 Opus라 판단력은 충분. 프롬프트(지시)만 엄격해지면 효과가 난다.

## 커밋 체크리스트

- [ ] `_VERIFY_PROMPT_TEMPLATE` 교체 (애매하면 NO + 지주사/사업부/단순언급 차단)
- [ ] 회귀 테스트: 과거 오판 4종 → NO, 진짜 수혜주 2종 → YES 확인
- [ ] 진짜 수혜주까지 NO면 과잉 차단 → 조건 미세 완화
- [ ] 커밋
- [ ] 서버 재시작 후 며칠 운영 → 지주사·대형주 검출 감소 + 검출 수 0 아님 확인
