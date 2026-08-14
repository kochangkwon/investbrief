"""레이더 교차 테마 가드 회귀 테스트 (순수 함수 — API/DB 불필요).

P3-1 재설계 반영: 광범위 마커 기사만 전 테마 차단, 마커 없는 복수 테마
매칭 제목은 대표 테마 1곳에 배정된다.

실행:
    cd backend && python3 -m tests.test_cross_theme_guard
    # 또는 pytest 설치 시: pytest tests/test_cross_theme_guard.py
"""
from app.services.theme_radar_service import (
    _assign_primary_theme,
    _build_title_kw_counts,
    _find_banned_broad_titles,
    _find_multi_theme_titles,
)


def test_broad_report_banned_everywhere():
    """회귀 픽스처 — 광범위 리포트(대장주·목표주가·리포트 마커 포함)가
    복수 테마에 매칭되면 전 테마에서 차단된다."""
    report_title = "삼성증권 리포트: KT·전력·반도체·로봇 대장주 목표주가 일제 상향"
    theme_titles = {
        1: {report_title, "효성중공업 초고압 변압기 수주"},
        2: {report_title, "SK하이닉스 HBM 증설 확정"},
        3: {report_title, "레인보우로보틱스 신제품 공개"},
    }
    banned = _find_banned_broad_titles(theme_titles)
    assert report_title in banned, "광범위 리포트가 가드에 걸리지 않음"
    assert "효성중공업 초고압 변압기 수주" not in banned
    assert "SK하이닉스 HBM 증설 확정" not in banned


def test_strong_material_assigned_not_banned():
    """P3-1 핵심 — 마커 없는 강한 재료(HBM 수주)는 복수 테마 매칭이어도
    차단되지 않고, 키워드 매칭 수가 많은 대표 테마에 배정된다."""
    strong = "SK하이닉스 HBM4 대규모 수주 계약 체결"
    theme_news_map = {
        1: [  # AI 반도체 — 키워드 2개 매칭
            {"title": strong, "matched_keyword": "HBM"},
            {"title": strong, "matched_keyword": "메모리 증설"},
        ],
        2: [  # 패키징 — 키워드 1개 매칭
            {"title": strong, "matched_keyword": "HBM 패키징"},
        ],
    }
    title_map = {tid: {n["title"] for n in news} for tid, news in theme_news_map.items()}
    banned = _find_banned_broad_titles(title_map)
    assert strong not in banned, "마커 없는 재료가 차단됨 (역선택 재발)"

    primary = _assign_primary_theme(_build_title_kw_counts(theme_news_map), banned)
    assert primary[strong] == 1, "키워드 매칭 수가 많은 테마에 배정돼야 함"


def test_assignment_tie_breaks_by_lower_theme_id():
    """동률이면 theme_id 낮은 쪽 (결정론적)."""
    t = "양쪽 테마 키워드에 1개씩 걸린 기사"
    counts = {t: {5: 1, 2: 1}}
    assert _assign_primary_theme(counts, set())[t] == 2


def test_single_theme_titles_not_banned_nor_assigned():
    """단일 테마 제목은 차단도 배정도 없다."""
    theme_titles = {1: {"뉴스1", "뉴스2"}, 2: {"뉴스3"}}
    assert _find_banned_broad_titles(theme_titles) == set()
    counts = {"뉴스1": {1: 1}}
    assert _assign_primary_theme(counts, set()) == {}


def test_empty_and_none_titles_ignored():
    """빈 제목은 여러 테마에 있어도 무시."""
    theme_titles = {1: {"", "뉴스1"}, 2: {"", "뉴스2"}}
    assert _find_multi_theme_titles(theme_titles) == set()


def test_banned_title_not_assigned():
    """차단된 제목은 대표 배정 대상에서도 제외."""
    t = "반도체 수혜주 총정리"
    counts = {t: {1: 2, 2: 1}}
    assert _assign_primary_theme(counts, {t}) == {}


if __name__ == "__main__":
    for fn_name in sorted(k for k in dir() if k.startswith("test_")):
        globals()[fn_name]()
        print(f"  ✓ {fn_name}")
    print("✅ 교차 테마 가드 회귀 테스트 전부 통과")
