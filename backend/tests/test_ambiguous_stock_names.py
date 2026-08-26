"""일반명사 동철 종목명 오추출 차단 (2026-08-26 실사고 회귀 테스트).

"대상"(對象)이 제약 기사의 "…를 대상으로"에서 종목으로 추출되어 K-바이오
기술수출 테마 수혜주로 등록, Claude 검증(YES 오판)까지 통과해 실매수 주문
직전까지 갔다(001680, 개장 전 수동 취소). theme_detection 실측 4건 중 3건은
검증이 걸렀으나 1건이 샜다 — 추출 단계에서 회사 문맥 증거를 요구한다.
"""
from app.services.stock_name_rules import (
    AMBIGUOUS_COMMON_NOUN_NAMES,
    ambiguous_name_lacks_company_context,
)


def test_real_incident_articles_blocked():
    """theme_detection에 기록된 실제 오추출 기사 3건 — 전부 차단."""
    cases = [
        "전임상·초기 1상서도 빅딜 잇따라…기전 확실하면 기술수출 시계 빨라진다. "
        "글로벌 제약사가 국내 바이오텍을 대상으로 기술 도입 협상을 확대하고 있다.",
        "금감원, 제약·바이오 공시개편 후속 설명회…IPO 주관사·상장사 대상",
        "SK텔링크, 英 인마샛과 해상 위성통신 협력 확대…선사 대상 공급",
    ]
    for text in cases:
        assert ambiguous_name_lacks_company_context("대상", text) is True


def test_company_context_passes():
    """회사로서의 언급은 통과 — 미탐 방지."""
    cases = [
        "대상, 2분기 영업이익 사상 최대…라이신 회복",   # 주어+쉼표
        "대상그룹, 소재 사업 재편 검토",                  # 그룹 접미
        "대상(주) 3분기 실적 발표",                       # 법인 표기
        '"대상, 새 성장동력 찾는다"…소재사업 강화',       # 인용부호 안 주어
    ]
    for text in cases:
        assert ambiguous_name_lacks_company_context("대상", text) is False


def test_dongwon_both_ways():
    assert ambiguous_name_lacks_company_context("동원", "예비군 동원 훈련 시행") is True
    assert ambiguous_name_lacks_company_context("동원", "동원, 참치 가격 인상 검토") is False


def test_ambiguous_set_requires_test_coverage():
    """가드 대상 이름 목록 — 무분별 확장 방지.

    하드코딩 동등성 대신 **커버리지 강제**로 의도를 지킨다: 등록된 모든
    이름은 아래 _BLOCK_CASES(일반명사 차단)와 _PASS_CASES(회사 통과)에
    각각 케이스가 있어야 한다. 근거 없이 이름만 추가하면 여기서 실패한다.
    """
    blocked_names = {n for n, _ in _BLOCK_CASES}
    passed_names = {n for n, _ in _PASS_CASES}
    missing_block = AMBIGUOUS_COMMON_NOUN_NAMES - blocked_names
    missing_pass = AMBIGUOUS_COMMON_NOUN_NAMES - passed_names
    assert not missing_block, f"차단 케이스 없는 등록 이름: {missing_block}"
    assert not missing_pass, f"통과 케이스 없는 등록 이름: {missing_pass}"
    # 케이스만 있고 등록 안 된 이름도 방지 (오타 등)
    assert blocked_names <= AMBIGUOUS_COMMON_NOUN_NAMES
    assert "대상" in AMBIGUOUS_COMMON_NOUN_NAMES   # 실사고 종목 — 해제 금지


# ── 2026-08-26 사고 후 확장분 회귀 (실측 오추출 문맥) ──────────────────
# 등록 이름 전체를 커버한다 — test_ambiguous_set_requires_test_coverage 가 강제.

_BLOCK_CASES = [
    ("대상", "글로벌 제약사가 국내 바이오텍을 대상으로 기술 도입 협상을 확대"),
    ("동원", "총력 동원 체제로 전환…공급망 재편 대응"),
    ("전방", "반도체 지수, 10% 추가 하락 경고…전방 산업 수요 둔화 우려 확산"),
    ("나노", "2나노 넘어 1.6나노로…TSMC, AI칩 미세공정 속도전"),
    ("신원", "〈GTA6〉 유출 사태 법정 공방···테이크투, 해커 신원 공개 청구"),
    ("미래산업", "정부, 미래산업 육성에 5조 투입…반도체·바이오 집중"),
    ("한창", "말차 붐에 웃는다…K푸드 수출이 한창 늘고 있다"),
]

_PASS_CASES = [
    ("대상", "대상그룹 바이오사업부 아미노산 증설 투자"),
    ("동원", "동원, 참치 가격 인상 검토"),
    ("전방", "전방, 2분기 영업이익 흑자 전환…면방 업황 회복"),
    ("나노", "나노, 탈질촉매 신규 수주 240억"),
    ("신원", "신원, 패션 부문 매출 증가로 실적 개선"),
    # 공시 목록의 실제 회사 언급 — 쉼표 규칙으로 통과해야 한다
    ("미래산업", "[주요공시] 퀄리타스반도체, 스트라드비젼, 우리기술, 미래산업, 롯데케미칼"),
    ("한창", "한창㈜ 신규 사업 진출 검토"),
]


def test_expanded_names_blocked_in_real_contexts():
    """일반명사 문맥 — 전부 차단."""
    for name, text in _BLOCK_CASES:
        assert ambiguous_name_lacks_company_context(name, text), f"{name} 차단 실패: {text}"


def test_expanded_names_pass_as_real_company():
    """진짜 회사 뉴스 — 통과 (과잉 차단 방지)."""
    for name, text in _PASS_CASES:
        assert not ambiguous_name_lacks_company_context(name, text), f"{name} 과잉 차단: {text}"


def test_verify_prompt_has_common_noun_guard():
    """검증 프롬프트 조건 0(종목 지칭 여부) — 추출 차단과 이중 방어."""
    from app.services.verify_prompts import build_theme_verify_prompt
    prompt = build_theme_verify_prompt(
        theme_name="K-바이오 글로벌 기술수출·임상 모멘텀",
        matched_keyword="기술수출",
        stock_name="대상",
        title="전임상·초기 1상서도 빅딜 잇따라…기전 확실하면 기술수출 시계 빨라진다",
    )
    assert "조건 0" in prompt and "일반명사" in prompt


if __name__ == "__main__":
    for fn_name in sorted(k for k in dir() if k.startswith("test_")):
        globals()[fn_name]()
        print(f"  ✓ {fn_name}")
    print("✅ 일반명사 동철 종목명 회귀 테스트 전부 통과")
