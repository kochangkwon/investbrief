"""잔여 개선(지시서 v1) 회귀 테스트 — 순수 함수 위주.

실행: cd backend && python3 -m tests.test_remaining_improvements
"""
from datetime import date

from app.collectors.dart_collector import _dedup_by_rcept, _prev_business_day
from app.services.theme_alert_service import _extract_kospi_close
from app.services.theme_radar_service import (
    _dynamic_freshness_hours,
    _order_articles,
)


# ── P1-1: KOSPI 브리프 폴백 파서 ─────────────────────────────────────


def test_extract_kospi_close():
    assert _extract_kospi_close({"kospi": {"close": 6813.34}}) == 6813.34
    assert _extract_kospi_close({"kospi": {"close": 0}}) is None      # 0은 무효
    assert _extract_kospi_close({"kospi": {}}) is None
    assert _extract_kospi_close({}) is None
    assert _extract_kospi_close(None) is None
    assert _extract_kospi_close({"kospi": {"close": "abc"}}) is None  # 파싱 불가


# ── P2-1: DART 전일 영업일·dedup ─────────────────────────────────────


def test_prev_business_day():
    assert _prev_business_day(date(2026, 8, 14)) == date(2026, 8, 13)  # 금→목
    assert _prev_business_day(date(2026, 8, 17)) == date(2026, 8, 14)  # 월→금
    assert _prev_business_day(date(2026, 8, 16)) == date(2026, 8, 14)  # 일→금


def test_dedup_by_rcept():
    items = [
        {"rcept_no": "A", "title": "1"},
        {"rcept_no": "B", "title": "2"},
        {"rcept_no": "A", "title": "1-dup"},   # 전일+당일 중복
        {"rcept_no": "", "title": "no-key"},   # 키 없음 — 유지
    ]
    out = _dedup_by_rcept(items)
    assert [i["title"] for i in out] == ["1", "2", "no-key"]


# ── P3-2: 대표 기사 선정 ─────────────────────────────────────────────


def test_order_articles_prefers_name_in_headline():
    info = {
        "stock_name": "한미약품",
        "headline": "비만치료제 시장 확대 전망",          # 종목명 없음 (먼저 잡힌 약한 기사)
        "description": "", "matched_keyword": "비만치료제", "url": "u1",
        "pub_date": "2026-08-14 07:00",
        "alt_news": [{
            "headline": "한미약품, MASH 치료제 기술수출 계약",   # 종목명 포함 (강한 기사)
            "description": "", "matched_keyword": "기술수출", "url": "u2",
            "pub_date": "2026-08-14 06:00",
        }],
    }
    arts = _order_articles(info)
    assert arts[0]["headline"] == "한미약품, MASH 치료제 기술수출 계약"


def test_order_articles_latest_first_when_no_name():
    info = {
        "stock_name": "없는이름",
        "headline": "옛 기사", "description": "", "matched_keyword": "k",
        "url": "", "pub_date": "2026-08-13 09:00",
        "alt_news": [
            {"headline": "새 기사", "description": "", "matched_keyword": "k",
             "url": "", "pub_date": "2026-08-14 07:30"},
            {"headline": "날짜없음", "description": "", "matched_keyword": "k",
             "url": "", "pub_date": None},
        ],
    }
    arts = _order_articles(info)
    assert arts[0]["headline"] == "새 기사"
    assert arts[-1]["headline"] == "날짜없음"


def test_order_articles_single():
    info = {"stock_name": "A", "headline": "h", "description": "",
            "matched_keyword": "k", "url": "", "pub_date": None}
    assert len(_order_articles(info)) == 1


# ── P3-3: 동적 신선도 ────────────────────────────────────────────────


def test_dynamic_freshness():
    assert _dynamic_freshness_hours(24, 1, 1) == 24     # 평일 연속
    assert _dynamic_freshness_hours(24, 3, 0) == 72     # 주말 후 월요일
    assert _dynamic_freshness_hours(24, 2, 2) == 48     # 화 공휴일 후 수요일
    assert _dynamic_freshness_hours(24, 30, 1) == 168   # 갭 상한 7일
    assert _dynamic_freshness_hours(24, None, 0) == 72  # DB 실패 폴백: 월 72h
    assert _dynamic_freshness_hours(24, None, 2) == 24  # DB 실패 폴백: 평일
    assert _dynamic_freshness_hours(0, 5, 0) == 0       # 필터 무효 유지


if __name__ == "__main__":
    for fn_name in sorted(k for k in dir() if k.startswith("test_")):
        globals()[fn_name]()
        print(f"  ✓ {fn_name}")
    print("✅ 잔여 개선 회귀 테스트 전부 통과")
