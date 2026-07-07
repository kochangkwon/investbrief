"""레이더 교차 테마 가드 회귀 테스트 (순수 함수 — API/DB 불필요).

실행:
    cd backend && python3 -m tests.test_cross_theme_guard
    # 또는 pytest 설치 시: pytest tests/test_cross_theme_guard.py
"""
from app.services.theme_radar_service import _find_multi_theme_titles


def test_kt_samsung_securities_report_excluded():
    """회귀 픽스처 — 삼성증권의 광범위 리포트 제목(KT 등 다수 대장주 언급)이
    전력·반도체·로봇 테마 키워드에 동시 매칭 → 전 테마에서 검증 제외되어야 한다."""
    report_title = "삼성증권 리포트: KT·전력·반도체·로봇 대장주 목표주가 일제 상향"
    theme_titles = {
        "전력 인프라 대격변": {report_title, "효성중공업 초고압 변압기 수주"},
        "AI 반도체 슈퍼사이클 진화": {report_title, "SK하이닉스 HBM 증설 확정"},
        "물리적 AI(피지컬 AI) 로봇 혁명": {report_title, "레인보우로보틱스 신제품 공개"},
    }

    banned = _find_multi_theme_titles(theme_titles)

    # 복수 테마 매칭 리포트 제목 → 제외 대상
    assert report_title in banned, "복수 테마 매칭 리포트가 가드에 걸리지 않음"
    # 단일 테마 전용 제목은 제외되지 않아야 함 (정상 감지 보존)
    assert "효성중공업 초고압 변압기 수주" not in banned
    assert "SK하이닉스 HBM 증설 확정" not in banned
    assert "레인보우로보틱스 신제품 공개" not in banned


def test_single_theme_titles_not_banned():
    """단일 테마에만 나타난 제목은 가드에 걸리지 않는다."""
    theme_titles = {
        "A": {"뉴스1", "뉴스2"},
        "B": {"뉴스3"},
    }
    assert _find_multi_theme_titles(theme_titles) == set()


def test_empty_and_none_titles_ignored():
    """빈 제목은 여러 테마에 있어도 무시(제외 대상 아님)."""
    theme_titles = {
        "A": {"", "뉴스1"},
        "B": {"", "뉴스2"},
    }
    assert _find_multi_theme_titles(theme_titles) == set()


def test_same_title_repeated_within_one_theme_not_banned():
    """set 입력이므로 한 테마 내 중복은 1회로 집계 → 단일 테마면 제외 아님."""
    theme_titles = {
        "A": {"동일제목"},  # 여러 키워드로 걸려도 set이라 1회
    }
    assert _find_multi_theme_titles(theme_titles) == set()


if __name__ == "__main__":
    test_kt_samsung_securities_report_excluded()
    test_single_theme_titles_not_banned()
    test_empty_and_none_titles_ignored()
    test_same_title_repeated_within_one_theme_not_banned()
    print("✅ 교차 테마 가드 회귀 테스트 4건 모두 통과")
