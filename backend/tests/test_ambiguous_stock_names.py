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


def test_ambiguous_set_contents():
    """가드 대상 이름 목록 — 무분별 확장 방지 (추가 시 근거와 케이스 필수)."""
    assert AMBIGUOUS_COMMON_NOUN_NAMES == {"대상", "동원"}
