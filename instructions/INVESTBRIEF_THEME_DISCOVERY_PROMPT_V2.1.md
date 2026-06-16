# InvestBrief 테마 발굴 프롬프트 v2.1 — 단독 지시서

> **작업명**: 주간 테마 발굴 프롬프트의 출력 깊이 강화 (검증 완료 버전)
> **작성일**: 2026-05-13 (v2.1: 검증 후 5개 보강)
> **적용 대상**: InvestBrief `backend/app/services/theme_discovery_service.py`
> **작업 분량**: **1일 (실제 코드 수정 2~3시간 + 검증)**
> **사전 의존성**: 없음 (v3.1 P1-4 이벤트 캘린더 있으면 통합, 없어도 작동)
> **StockAI 영향**: **없음**
>
> ---
>
> ## v2.1 보강 (v2 대비)
>
> 검증 결과 발견된 5개 우려를 모두 보강:
>
> 1. **이벤트 캘린더 옵션 통합** — P1-4 적용 시 자동 활용, 없어도 작동 (카탈리스트 정확도 ↑)
> 2. **max_tokens 3000 → 3500** — 5개 테마 12항목 안전 출력
> 3. **테마 수 3~4개로 제한** — 깊이 우선, 양 줄임
> 4. **TAM/CAGR/한국 노출도를 "선택" 표시** — "데이터 부족" 도배 방지, 항목 자체 생략 가능하게
> 5. **dry-run 대안 스크립트** — 빈 DB / 운영 DB 양쪽 모두 검증 가능
>
> ## 솔직한 기대치
>
> | | v1 (현재) | v2 (1차) | **v2.1 (검증)** |
> |------|:---:|:---:|:---:|
> | 테마당 분석 항목 | 4개 | 12개 | **9~12개 (선택 가능)** |
> | "데이터 부족" 도배 위험 | — | 높음 | **낮음 (선택형)** |
> | 카탈리스트 정확도 | — | 낮음 | **중간 (이벤트 캘린더 통합)** |
> | 텔레그램 분할 발송 | 거의 없음 | 항상 | **1회 분할 (안전)** |
> | 점수 (예상) | 70 | 75 (현실) | **78~80** |

---

## 1. 목적

### 현재 상태 (v3.1까지)

주간 테마 발굴(`/theme-discover` 또는 월요일 자동 실행) 출력이 5개 항목으로 단순:

```
### 1. AI 반도체
- 부상 근거: 2~3줄
- 핵심 키워드: 5개
- 수혜 종목: 5개
- 모멘텀 강도: 🔥🔥🔥
```

→ **"무엇이 부상 중인지"는 알지만, "그 테마가 진짜인지, 얼마나 갈지, 어떻게 깨질지"는 모름.**

### 변경 후

12개 항목으로 확장 → **테마 분석가 리포트 수준**:

```
### 1. AI 반도체
- 부상 근거: 2~3줄
- 핵심 키워드: 5개
- 핵심 드라이버: 정책/기술/수요 중 무엇이 추진력인지
- 시장 규모/성장률: TAM과 CAGR (가능 범위 내)
- 밸류체인 위치: 상류/중류/하류 구분
- 한국 노출도: 한국 기업의 시장 점유율 또는 매출 비중
- 라이프 스테이지: 초기/가속/성숙/쇠퇴
- 과거 유사 사례: 비슷한 흐름이 있었던 과거 테마
- 수혜 종목: 5개
- 깨질 시나리오: 이 테마가 끝날 수 있는 리스크
- 다음 카탈리스트: 7-30일 내 일정 (가능한 경우)
- 모멘텀 강도: 🔥🔥🔥
```

### 기대 효과

- 테마 발굴 점수: **70 → 80점** (v3.1 기준)
- 사용자가 키움/네이버 금융을 추가로 띄울 필요 감소
- 의사결정 직전까지 필요한 정보 한 번에 제공

### 비용 영향

| 항목 | v1 (현재) | v2 (1차) | **v2.1** |
|------|:---:|:---:|:---:|
| max_tokens | 2000 | 3000 | **3500** |
| 프롬프트 입력 길이 | ~5000 토큰 | ~5500 토큰 | **~5800 토큰** (이벤트 포함) |
| 호출당 비용 (Sonnet 4) | ~$0.05 | ~$0.08 | **~$0.09** |
| 주간 1회 실행 | 주 $0.05 | 주 $0.08 | **주 $0.09** |

→ v1 대비 **주당 +$0.04**. 무시 가능한 수준.

---

## 2. 변경 파일 (단일)

### `backend/app/services/theme_discovery_service.py`

- **수정 함수 1개**: `_build_theme_discovery_prompt()` (전체 교체, **시그니처에 `events_text` 추가**)
- **수정 호출부**: `discover_themes()` 의 3곳 (이벤트 캘린더 조회 + 프롬프트 빌드 + max_tokens)
- **수정 1줄**: `discover_themes()` 의 `max_tokens=2000` → `max_tokens=3500`

다른 파일은 건드리지 않음. 출력 형식의 핵심 패턴(`### 1. [테마명]`, `**핵심 키워드**:`)은 **그대로 유지** — 따라서 DB 자동 등록 로직(`_auto_register_themes`)도 변경 불필요.

---

## 3. 새 프롬프트 (전체 코드)

### v2.1 핵심 변경 사항

| 보강 | 어디에 적용 |
|------|------|
| ① 이벤트 캘린더 통합 | 함수 시그니처 + 프롬프트 입력 섹션 |
| ② max_tokens 3500 | `discover_themes()` 호출부 |
| ③ 테마 3~4개로 제한 | 프롬프트 첫 문장 + "중요 규칙" |
| ④ 선택 항목 명시 | 분석 항목 일부에 "(선택)" 표시 + 규칙 |
| ⑤ dry-run 대안 | 5장 검증 절차 (코드 변경 X) |

### `_build_theme_discovery_prompt()` 전체 교체

⚠️ **함수 시그니처에 `events_text` 매개변수 추가** (이벤트 캘린더 통합용, optional):

```python
def _build_theme_discovery_prompt(
    days: int,
    news_titles: list[str],
    disclosure_titles: list[str],
    ai_summaries: list[str],
    events_text: str = "",  # v2.1: 이벤트 캘린더 (선택)
) -> str:
    """테마 발굴용 Claude 프롬프트 (v2.1 — 9~12개 항목 분석가 리포트).

    events_text가 제공되면 카탈리스트 항목에 활용.
    없으면 카탈리스트 항목은 뉴스/공시에서만 추출 시도.
    """
    news_section = "\n".join(news_titles[:300])
    disclosure_section = "\n".join(disclosure_titles[:100])
    summary_section = "\n\n".join(ai_summaries[:30])

    # v2.1: 이벤트 캘린더 섹션 (있을 때만 표시)
    events_block = ""
    if events_text and events_text.strip():
        events_block = f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📅 향후 30일 예정 이벤트 (P1-4 캘린더):
{events_text}

"""

    return f"""당신은 한국 주식 시장 테마 분석 전문가입니다.

다음은 최근 {days}일간 한국 증시 관련 데이터입니다.

이 데이터에서 **부상 중인 투자 테마를 3~4개** 발굴하고,
**깊이 우선** 원칙으로 분석가 리포트 수준의 분석을 제공하세요.
(테마 수보다 분석 깊이가 더 중요)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📰 뉴스 제목 (최근 {days}일):
{news_section}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 DART 공시 제목:
{disclosure_section}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🤖 일일 AI 요약:
{summary_section}

{events_block}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

다음 형식으로 답변하세요:

## 📈 부상 중인 테마 (3~4개)

### 1. [테마명]

**필수 항목** (모든 테마에 작성):
- **부상 근거**: 왜 이 테마가 주목받는지 (2~3줄)
- **핵심 키워드**: 해당 테마를 관통하는 키워드 3~5개 (쉼표 구분)
- **핵심 드라이버**: 정책 / 기술 / 수요 중 무엇이 추진력인지 (1줄)
- **밸류체인 위치**: 상류(소재/장비) / 중류(제조) / 하류(서비스/유통) 중 한국 기업이 강한 위치
- **라이프 스테이지**: 초기 부상 / 가속 성장 / 성숙 / 조정 중 하나 + 1줄 근거
- **수혜 종목**: 뉴스/공시에 명시적으로 등장한 종목 (종목명만, 최대 5개)
- **깨질 시나리오**: 이 테마가 끝날 수 있는 리스크 요인 (1~2줄)
- **모멘텀 강도**: 🔥🔥🔥 (강함) / 🔥🔥 (중간) / 🔥 (약함)

**선택 항목** (입력 데이터에서 추출 가능한 경우만 작성, 불확실하면 생략):
- **시장 규모 (TAM)**: 추정 시장 규모 + 연 성장률(CAGR)
- **한국 노출도**: 글로벌 시장 대비 한국 기업 점유율 또는 매출 비중
- **과거 유사 사례**: 비슷한 흐름이 있었던 과거 테마 (예: "2017 메모리 슈퍼사이클")
- **다음 카탈리스트**: 7~30일 내 예정 일정 (어닝/정책/컨퍼런스 등)

## ⚠️ 주의 섹터 (1~2개)

각 항목 형식:
- **섹터명**: 하방 압력 이유 (1줄) + 깨질/지속 시나리오 (1줄)

## 💡 한 줄 인사이트

이 {days}일간 시장을 관통하는 핵심 스토리를 한 줄로.

## 🔄 테마 간 관계 (선택사항)

상호 보강 또는 반비례 관계인 테마 쌍이 있으면 1~2쌍만:
- "테마 A ↔ 테마 B: 관계 설명 (1줄)"

---

**중요 규칙:**

1. **양보다 깊이**: 테마는 3~4개로 충분. 5개는 깊이가 떨어지므로 지양.
2. **선택 항목은 진짜 있을 때만**: 추측하지 말고, 입력 데이터에서 명확한 근거가 있을 때만 작성. 불확실하면 **항목 자체를 생략**. "데이터 부족" 같은 표기 불필요.
3. **다음 카탈리스트**: 위 "📅 향후 30일 예정 이벤트" 섹션이 제공되면 그 일정을 우선 활용. 없으면 뉴스/공시에서 추출. 둘 다 없으면 항목 생략.
4. **수혜 종목**: 뉴스에 **실제로 등장한** 종목만. 한 종목은 한 테마에만 배정 권장 (가장 강한 매칭).
5. **이미 누구나 아는 테마**(예: "반도체 수혜")는 제외. **새롭게 부상 중인** 것 중심.
6. **라이프 스테이지**: 입력 데이터의 언급 빈도, 가격 동향, 정책 단계 등 종합 판단. 일관성을 위해 보수적으로(과대 단계 평가 회피).
7. 서론/결론 없이 위 형식대로 바로 작성."""
```

### 변경점 요약

| 기존 (v1) | v2 (1차) | **v2.1 (검증)** |
|------|------|------|
| 4개 분석 항목 | 12개 (모두 필수) | **8개 필수 + 4개 선택** |
| 3~5개 테마 | 3~5개 | **3~4개 (깊이 우선)** |
| 추측 금지만 명시 | "데이터 부족" 강제 표기 | **선택 항목은 생략 가능** |
| 이벤트 캘린더 미통합 | 미통합 | **events_text 옵션 (자동 활용)** |
| max_tokens 2000 | 3000 | **3500** |

### 호환성 보장 (기존 v1)

- `### N. [테마명]` 형식 그대로 → `_extract_themes_from_analysis()` 정상 작동
- `**핵심 키워드**:` 라인 그대로 → 자동 등록 정상 작동
- 함수 시그니처에 추가된 `events_text=""` 는 기본값 있어서 **기존 호출자도 그대로 사용 가능**

---

## 4. 파싱 호환성 보강

`_extract_themes_from_analysis()` 의 기존 패턴은 그대로 작동. 단, **테마 메타데이터를 함께 추출**해서 DB에 저장하면 추후 활용 가치 ↑.

### 옵션 A: 최소 변경 (기존 그대로)

- 파싱 함수 미수정
- 신규 항목들은 AI 응답 텍스트에만 존재, DB 저장 X
- 텔레그램 알림에는 전체 응답이 그대로 나가므로 사용자는 정보 다 봄
- **권장**: 1일 작업으로 끝내려면 이 옵션

### 옵션 B: 메타데이터 추출 (추가 1-2시간)

- 라이프 스테이지, 모멘텀 강도 등을 추출해 Theme 모델에 저장
- Theme 테이블 컬럼 추가 필요 (`lifecycle_stage`, `momentum_strength`, ...)
- DB 마이그레이션 필요

**본 지시서는 옵션 A 권장** (단순함 + 안정성 우선). 옵션 B는 운영 후 필요성 확인 후 별도 작업.

---

## 5. 적용 절차

### 5-1. 백업

```bash
cd ~/dev/investbrief  # 본인 경로
git status
git checkout -b feature/theme-prompt-v2-1
cp backend/app/services/theme_discovery_service.py \
   backend/app/services/theme_discovery_service.py.backup
```

### 5-2. 코드 수정 (총 3곳)

**(a) `_build_theme_discovery_prompt()` 전체 교체** — 위 3장의 함수 전체로.

**(b) `discover_themes()` 의 호출부 수정** (3개 변경):

```python
# theme_discovery_service.py 약 275-285줄 부근

# 1. 이벤트 캘린더 조회 (v3.1 P1-4 적용된 경우만 작동, 없으면 빈 문자열)
events_text = ""
try:
    from app.services import event_calendar_service
    events = await event_calendar_service.get_upcoming_events(days=30)
    if events:
        events_lines = []
        for e in events[:15]:  # 최대 15건
            events_lines.append(
                f"[{e.get('date', '?')}] {e.get('title', '?')} "
                f"({e.get('category', '?')})"
            )
        events_text = "\n".join(events_lines)
except ImportError:
    # P1-4 미적용 환경 — 정상, events_text=""로 진행
    pass
except Exception:
    logger.exception("이벤트 캘린더 조회 실패 (선택사항, 무시)")

# 2. 프롬프트 빌드 (events_text 추가)
prompt = _build_theme_discovery_prompt(
    days, news_titles, disclosure_titles, ai_summaries,
    events_text=events_text,  # v2.1 신규
)

# 3. max_tokens 2000 → 3500
try:
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model=settings.ai_model,
        max_tokens=3500,  # v2.1: 8개 필수 + 4개 선택 = 최대 12 항목, 3~4 테마
        messages=[{"role": "user", "content": prompt}],
    )
```

**(c) 로깅 1줄 추가** (선택, 디버깅용):

```python
# discover_themes() 끝부분에 추가
logger.info(
    "테마 발굴 v2.1: 입력 %d 뉴스 + %d 공시 + %d 요약 + %d 이벤트 → 출력 %d 토큰",
    len(news_titles), len(disclosure_titles), len(ai_summaries),
    len(events_text.split("\n")) if events_text else 0,
    response.usage.output_tokens,
)
```

### 5-3. dry-run 검증 (v2.1: 2가지 시나리오)

**시나리오 A: 운영 DB 있음 (최근 30일 브리프 누적)**

```bash
cd backend
python3 << 'EOF'
import asyncio
from app.services.theme_discovery_service import discover_themes

async def test():
    result = await discover_themes(days=30)
    if "error" in result:
        print("ERROR:", result["error"])
        print("→ 시나리오 B (가짜 입력) 사용 권장")
        return
    print("=== 발굴 결과 (앞 3000자) ===")
    print(result["analysis"][:3000])
    print()
    print(f"아카이브: {result['archive_count']}건")
    print(f"뉴스: {result['news_count']}건")
    print(f"공시: {result['disclosure_count']}건")

asyncio.run(test())
EOF
```

**시나리오 B: 운영 DB 없음 / 빈 DB / 로컬 dev 환경** ← v2.1 신규 대안

`discover_themes`을 우회하고 **프롬프트 빌더만 직접 테스트**:

```bash
cd backend
python3 << 'EOF'
import asyncio
import anthropic
from app.config import settings
from app.services.theme_discovery_service import _build_theme_discovery_prompt

async def test():
    # 가짜 입력 데이터 (실제 InvestBrief 출력 형태와 동일)
    fake_news = [
        "[2026-05-12] 한미반도체, 1Q 영업이익 3배 증가… HBM 수혜",
        "[2026-05-12] 엔비디아 H200 양산 본격화에 SK하이닉스 수주 잇따라",
        "[2026-05-11] 정부, AI 반도체 R&D 1조원 추가 투입 발표",
        "[2026-05-10] 한화에어로스페이스, 폴란드 K-9 자주포 추가 수주",
        "[2026-05-10] LIG넥스원, 사우디 천궁-II 1.2조원 계약 체결",
        "[2026-05-09] 셀트리온, ADC 신약 SBE303 Phase 1 결과 발표 임박",
        "[2026-05-09] 알테오젠 SC제형 기술수출, 머크와 추가 계약 가능성",
    ]
    fake_disclosures = [
        "[2026-05-12] 한미반도체: 단일판매·공급계약체결 (TC본더 1,200억원)",
        "[2026-05-11] 한화에어로스페이스: 단일판매·공급계약체결 (K-9 4,500억원)",
        "[2026-05-10] LIG넥스원: 단일판매·공급계약체결 (천궁-II 12,000억원)",
        "[2026-05-09] 셀트리온: 임상시험계획 변경승인 (SBE303)",
    ]
    fake_summaries = [
        "[2026-05-12] 반도체 섹터 강세, AI 반도체 후공정 종목 부각. 한미반도체 +8% 급등.",
        "[2026-05-11] 방산 수출 모멘텀 지속. 한화에어로, LIG넥스원 신고가.",
        "[2026-05-10] 바이오 ADC 테마 부상. 셀트리온, 알테오젠 강세.",
    ]
    fake_events = """[2026-05-22] 한미반도체 1Q 실적 발표 (earnings)
[2026-05-28] 엔비디아 GTC 컨퍼런스 (corporate)
[2026-06-15] 셀트리온 SBE303 Phase 1 결과 발표 (regulatory)
[2026-06-18] FOMC 회의 결과 발표 (macro)"""

    # 프롬프트 빌드
    prompt = _build_theme_discovery_prompt(
        days=30,
        news_titles=fake_news,
        disclosure_titles=fake_disclosures,
        ai_summaries=fake_summaries,
        events_text=fake_events,  # v2.1 신규
    )

    print("=== 프롬프트 길이 ===")
    print(f"{len(prompt):,} 문자, ~{len(prompt)//4} 토큰")
    print()

    # 실제 API 호출 (선택)
    if input("실제 Claude API 호출? (y/N): ").strip().lower() == "y":
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model=settings.ai_model,
            max_tokens=3500,
            messages=[{"role": "user", "content": prompt}],
        )
        print("=== 응답 ===")
        print(response.content[0].text)
        print()
        print(f"입력 토큰: {response.usage.input_tokens}")
        print(f"출력 토큰: {response.usage.output_tokens}")
    else:
        print("(API 호출 스킵)")

asyncio.run(test())
EOF
```

**확인 포인트** (양 시나리오 공통):
- [ ] 3~4개 테마 추출 (5개 이상이면 프롬프트 미준수)
- [ ] 필수 8개 항목은 모두 작성됨
- [ ] 선택 4개 항목은 일부만 작성되어도 OK ("데이터 부족" 표기 없음)
- [ ] 다음 카탈리스트 항목이 events_text의 내용을 활용함
- [ ] 기존 `### 1. [테마명]` 형식 유지
- [ ] `**핵심 키워드**:` 라인 유지

### 5-4. 파싱 검증

```bash
python3 << 'EOF'
import asyncio
from app.services.theme_discovery_service import (
    discover_themes, _extract_themes_from_analysis,
)

async def test():
    result = await discover_themes(days=30)
    if "error" in result:
        print("ERROR:", result["error"])
        return
    themes = _extract_themes_from_analysis(result["analysis"])
    print(f"추출 테마: {len(themes)}개")
    for t in themes:
        print(f"  - {t['name']} (키워드 {len(t['keywords'])}개)")
    if len(themes) < 3:
        print("⚠️ 테마 추출 부족 - 프롬프트나 파싱 점검 필요")

asyncio.run(test())
EOF
```

**확인 포인트**:
- [ ] **3~4개** 테마가 추출됨 (v2.1 목표 범위)
- [ ] 각 테마에 키워드 3~5개

### 5-5. 텔레그램 실전 테스트

```bash
# 텔레그램에서 직접 명령 실행
/theme-discover
```

**확인 포인트**:
- [ ] 메시지가 정상 발송됨 (1~2회 분할 발송은 정상)
- [ ] 12개 항목 중 8개 필수 + 일부 선택 = 가독성 OK
- [ ] 4개 정도의 테마가 깊이 있게 분석됨
- [ ] 이벤트 캘린더 적용 시: 카탈리스트 항목에 실제 일정 등장

### 5-6. (v3.1 P1-4 적용 안 된 경우) 출력 차이 확인

P1-4 이벤트 캘린더 없이 적용 시:
- `events_text=""` 로 전달되어 `events_block`은 빈 문자열
- 프롬프트에 "📅 향후 30일 예정 이벤트" 섹션 자체 등장 안 함
- "다음 카탈리스트" 항목은 뉴스/공시에서만 추출 → 거의 생략
- → **정상 동작, 다만 카탈리스트 정확도 ↓**

P1-4 적용 후 자동으로 events_text 채워짐 → 정확도 ↑

---

## 6. 출력 예시 (예상)

### Before (v1, 현재)

```
### 1. AI 반도체 후공정
- **부상 근거**: 한미반도체 HBM 후공정 장비 수주 잇따르고, 
  엔비디아 발주 확대로 시장 관심 집중.
- **핵심 키워드**: HBM, 후공정, 패키징, TC본더, AI 반도체
- **수혜 종목**: 한미반도체, 하나마이크론, 케이씨텍, 동진쎄미켐, 와이씨켐
- **모멘텀 강도**: 🔥🔥🔥
```

### After (v2.1)

**필수 8개 + 선택 4개 모두 있는 이상적 경우** (이벤트 캘린더 통합 시):

```
### 1. AI 반도체 후공정

[필수 항목]
- **부상 근거**: 한미반도체 1Q 영업이익 3배 증가, HBM 후공정 장비 수주 
  잇따르고, 엔비디아 H200 양산 본격화로 시장 관심 집중.
- **핵심 키워드**: HBM, 후공정, 패키징, TC본더, AI 반도체
- **핵심 드라이버**: 수요 (엔비디아 H100/H200 양산 가속)
- **밸류체인 위치**: 중류 (후공정 장비/패키징) — 한국 강세
- **라이프 스테이지**: 가속 성장 — 1Q 어닝 호조 + 정부 R&D 1조원 추가
- **수혜 종목**: 한미반도체, 하나마이크론, 케이씨텍, 동진쎄미켐, 와이씨켐
- **깨질 시나리오**: AI 학습 수요 둔화, 중국 HBM 진입, 메모리 공급 과잉
- **모멘텀 강도**: 🔥🔥🔥

[선택 항목 — 데이터 있는 것만]
- **한국 노출도**: HBM 글로벌 점유율 SK하이닉스 53%, 삼성 38%
- **과거 유사 사례**: 2017-18 메모리 슈퍼사이클
- **다음 카탈리스트**: 5/22 한미반도체 1Q 실적, 5/28 엔비디아 GTC
```

**선택 항목 일부 생략 (정직한 경우)**:

```
### 2. 방산 수출

[필수 항목]
- **부상 근거**: 한화에어로 K-9 폴란드 추가 수주, LIG넥스원 사우디 천궁-II
  1.2조 계약 체결. 한국 방산 수출 사상 최대 페이스.
- **핵심 키워드**: K-방산, K-9 자주포, 천궁-II, FA-50, 방산 수출
- **핵심 드라이버**: 정책 (지정학적 긴장 + 한국 정부 방산 수출 지원 강화)
- **밸류체인 위치**: 하류 (완성품) — 한국 강세
- **라이프 스테이지**: 가속 성장 (2022~ 진행 중)
- **수혜 종목**: 한화에어로스페이스, LIG넥스원, 현대로템, 한화시스템
- **깨질 시나리오**: 우크라이나 휴전, 미국 방산 우위 회복, 한국 정부 정책 변화
- **모멘텀 강도**: 🔥🔥🔥

[선택 항목]
- **다음 카탈리스트**: (수주 공시 추가 가능성, 구체 일정 미명시)
```

→ TAM, 한국 노출도, 과거 사례는 입력 데이터에 명확한 근거 없어서 **생략**. 
"데이터 부족"이라고 적지 않음 → 정보 가독성 ↑

### v2.1 vs v2 출력 차이

| 항목 | v2 | **v2.1** |
|------|------|------|
| TAM 항목 매번 출력? | 항상 ("데이터 부족" 포함) | **있을 때만** |
| 테마 수 | 3~5개 | **3~4개 (깊이 우선)** |
| 카탈리스트 정확도 | 낮음 (입력에 일정 없음) | **중간 (이벤트 캘린더 통합)** |
| 사용자 가독성 | "데이터 부족" 도배 | **명확한 정보만** |

---

## 7. 운영 후 학습 사이클

본 프롬프트 적용 후 다음 항목을 1~2개월 모니터링:

### 모니터링 지표

1. **"데이터 부족" 빈도**
   - TAM/CAGR/한국 노출도 항목에서 자주 나오는지
   - 자주 나오면 입력 데이터(뉴스 소스) 확장이 필요한 신호
2. **카탈리스트 정확도**
   - "5/22 한미 어닝" 같이 명시된 일정이 실제와 맞는지
   - 틀린 경우가 많으면 P1-4 어닝 캘린더 (v3.1)와 통합 필요
3. **라이프 스테이지 분류의 일관성**
   - 같은 테마가 매주 다른 스테이지로 분류되는지
   - 일관성 없으면 프롬프트 추가 보강 필요
4. **사용자 만족도** (정성적)
   - 출력 정보로 의사결정에 도움이 되는지 직접 평가

### 보강 후보 (운영 후 1~2개월 뒤)

- 라이프 스테이지를 DB에 별도 저장 (옵션 B 활성화)
- 모멘텀 강도를 P1-5 점수와 연계
- 깨질 시나리오 자동 모니터링 (해당 시나리오 발생 시 알림)

---

## 8. 적용 체크리스트

```bash
# 1단계: 백업
[ ] git branch 생성 (feature/theme-prompt-v2-1)
[ ] theme_discovery_service.py 백업

# 2단계: 코드 수정
[ ] _build_theme_discovery_prompt() 전체 교체 (events_text 매개변수 추가)
[ ] discover_themes() 내부 이벤트 캘린더 조회 코드 추가
[ ] discover_themes() 호출 시 events_text 전달
[ ] max_tokens 2000 → 3500
[ ] (선택) 로깅 1줄 추가

# 3단계: dry-run (시나리오 A 또는 B)
[ ] 시나리오 A: 운영 DB 있으면 discover_themes(days=30) 직접 호출
[ ] 시나리오 B: 빈 DB면 _build_theme_discovery_prompt() 직접 호출 (가짜 입력)
[ ] 3~4개 테마 추출 확인
[ ] 필수 8개 항목 모두 작성 확인
[ ] 선택 4개 항목은 진짜 있을 때만 작성 (생략 OK)
[ ] events_text 적용 시 카탈리스트 항목 채워지는지 확인

# 4단계: 파싱 검증
[ ] _extract_themes_from_analysis() 호출 결과
[ ] 3~4개 테마명 + 키워드 정상 추출

# 5단계: 텔레그램 실전
[ ] /theme-discover 명령 실행
[ ] 메시지 정상 발송 (1~2회 분할 OK)
[ ] 정보 가독성 확인 (필수 8 + 선택 일부)

# 6단계: commit
[ ] git add backend/app/services/theme_discovery_service.py
[ ] git commit -m "feat: 테마 발굴 프롬프트 v2.1 — 9~12 항목 + 이벤트 캘린더 통합"

# 7단계: 운영
[ ] 다음 월요일 자동 실행 결과 확인
[ ] 1주 뒤 출력 품질 평가
[ ] (v3.1 P1-4 미적용 환경) → P1-4 적용 후 카탈리스트 정확도 재평가
```

---

## 9. 롤백 가이드

문제 발생 시 즉시 롤백:

```bash
cd ~/dev/investbrief
# 백업 복원
cp backend/app/services/theme_discovery_service.py.backup \
   backend/app/services/theme_discovery_service.py

# 또는 git revert
git revert HEAD

# 서버 재시작
sudo systemctl restart investbrief-backend
```

롤백 후 출력은 v1 형식 (4개 항목)으로 즉시 복귀. DB/스케줄러 영향 없음.

---

## 10. 변경 이력

- **v2 (2026-05-13)**: 최초 작성. 12개 항목 분석가 리포트 수준 프롬프트.
- **v2.1 (2026-05-13)**: 검증 결과 발견된 5개 우려 보강.
  - ① **이벤트 캘린더 옵션 통합**: `events_text` 매개변수 추가, v3.1 P1-4 있으면 자동 활용
  - ② **max_tokens 3000 → 3500**: 5개 테마 12 항목 안전 출력
  - ③ **테마 3~4개로 제한**: 깊이 우선 (양 줄임)
  - ④ **TAM/CAGR/한국 노출도/과거 사례를 "선택"으로 변경**: "데이터 부족" 도배 방지
  - ⑤ **dry-run 시나리오 B 추가**: 빈 DB 환경 대응 (가짜 입력으로 프롬프트만 테스트)
  - 기대 점수: v2 75 → **v2.1 78~80**
  - 작업 분량: 실제 2~3시간 (검증 포함 1일)
  - 파싱 호환: 기존 `_extract_themes_from_analysis` 그대로 작동

---

**끝.**
