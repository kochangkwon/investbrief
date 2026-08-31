"""그룹명 줄임 표기 오태깅 차단 (2026-09-01 효성 실사고 회귀 테스트).

헤드라인 "美 전력망 '현지생산' 승부…HD현대·효성 한발 앞서"의 주체는
효성중공업(298040)이지만, 계열사명이 "효성"으로 줄여 표기되어
_group_prefix_is_noise(계열사 토큰 동반 시 차단)가 뚫렸고 Claude 검증도
YES 오판 → 지주사 ㈜효성(004800)이 전력 인프라 테마 B등급 자동매매 ON까지
등록됐다. 그룹명 단독 토큰에도 회사 문맥 증거(접미 결합 or 주어+쉼표)를
요구한다. 근거: docs/INVESTBRIEF_GROUP_NAME_ABBREVIATION_GUARD.md
"""
from app.services.stock_name_rules import (
    GROUP_PREFIX_NAMES,
    ambiguous_name_lacks_company_context,
)


def test_real_incident_headline_blocked():
    """실사고 헤드라인 — 차단."""
    text = "美 전력망 '현지생산' 승부…HD현대·효성 한발 앞서"
    assert ambiguous_name_lacks_company_context("효성", text) is True


def test_measured_group_token_noise_blocked():
    """theme_detection 실측 NO 사례들 — 추출 단계 차단 (검증 호출 절약)."""
    cases = [
        ("효성", "삼성·LG·효성 창업주 발자취 잇는 'K-거상 투어' 올해 뜬다"),
        ("LG",  "삼성·LG·효성 창업주 발자취 잇는 'K-거상 투어' 올해 뜬다"),
        ("효성", "코스피, 1.5% 오른 6912 마감...트럼프 \"전력비상사태\" 선포에 효성重 등 강세"),
        ("SK",  "최태원 SK 회장, 日 반도체 합작공장 설립 추진"),
        ("SK",  "JDC 송석언 \"AIDC, 제주에도…카카오·SK·KT 논의\""),
        ("한화", "[THE CEO] 김동관 한화 수석부회장"),
    ]
    for name, text in cases:
        assert ambiguous_name_lacks_company_context(name, text) is True, (name, text)


def test_company_context_passes():
    """회사로서의 언급은 통과 — 실측 정상 기사 미탐 방지."""
    cases = [
        ("신세계", "면세점까지 흑자 전환…신세계, 3분기 실적 더 좋아진다"),  # 실측 정상 YES
        ("한화",  "한화, LNG 글로벌 사업법인 설립·밸류체인 구축"),          # ㈜한화 자체 사업
        ("두산",  "'전자제품 뼈대' CCL 지켜낸 두산, 반도체 3대 파트너"),
        ("효성",  "효성, 2분기 영업이익 개선…화학 부문 회복"),              # 지주사 주어+쉼표
        ("효성",  "효성그룹 지배구조 개편 검토"),                            # 그룹 접미
    ]
    for name, text in cases:
        assert ambiguous_name_lacks_company_context(name, text) is False, (name, text)


def test_all_group_names_covered_by_guard():
    """가드가 실제로 그룹명 전체에 걸리는지 — 사고 종목 등록 확인."""
    assert "효성" in GROUP_PREFIX_NAMES   # 실사고 종목 — 해제 금지
    # 대표 케이스: 어느 그룹명이든 문맥 증거 없으면 차단, 주어+쉼표면 통과
    for name in sorted(GROUP_PREFIX_NAMES):
        assert ambiguous_name_lacks_company_context(name, f"…{name} 계열 성장 전망") is True
        assert ambiguous_name_lacks_company_context(name, f"{name}, 2분기 실적 발표") is False


def test_radar_loop_condition():
    """theme_radar_service 추출 루프 조건이 그룹명을 포함하는지 (소스 검사).

    heavy import 없이 조건 자체를 검사 — 리팩토링으로 조건이 지워지면 실패.
    """
    import os
    src_path = os.path.join(
        os.path.dirname(__file__), "..", "app", "services", "theme_radar_service.py"
    )
    with open(src_path, encoding="utf-8") as f:
        src = f.read()
    assert "or candidate in GROUP_PREFIX_NAMES)" in src, (
        "추출 루프의 그룹명 회사 문맥 가드가 제거됨 — "
        "docs/INVESTBRIEF_GROUP_NAME_ABBREVIATION_GUARD.md 참조"
    )
