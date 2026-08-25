"""글로벌 시장 폴백 회귀 테스트 (P2 네이버 폴백 · P3 경보 임계값).

네트워크 호출은 하지 않는다 — 파싱·병합·판정 로직만 순수 함수로 검증.

실행: cd backend && python3 -m tests.test_global_fallback
"""
from app.collectors.price_collector import (
    _naver_row_close,
    _naver_rows,
    _naver_sorted_closes,
)
from app.services.scheduler import _global_market_alert_text


# ── 네이버 응답 파싱 (스키마 변형 흡수) ───────────────────────────────


def test_rows_from_plain_list():
    payload = [{"closePrice": "1,350.50"}, {"closePrice": "1,344.00"}]
    assert len(_naver_rows(payload)) == 2


def test_rows_from_result_wrapper():
    payload = {"isSuccess": True, "result": [{"closePrice": "18.24"}]}
    assert len(_naver_rows(payload)) == 1


def test_rows_from_nested_datas():
    payload = {"result": {"datas": [{"nv": "1350.5"}, {"nv": "1344"}]}}
    assert len(_naver_rows(payload)) == 2


def test_rows_from_unknown_shape_is_empty():
    assert _naver_rows({"unexpected": {"deep": 1}}) == []
    assert _naver_rows(None) == []
    assert _naver_rows("문자열") == []


def test_row_close_parses_comma_and_alt_fields():
    assert _naver_row_close({"closePrice": "1,350.50"}) == 1350.5
    assert _naver_row_close({"nv": "18.24"}) == 18.24
    assert _naver_row_close({"price": 1350}) == 1350.0
    assert _naver_row_close({"closePrice": "0"}) is None      # 0은 무효
    assert _naver_row_close({"closePrice": "abc"}) is None
    assert _naver_row_close({}) is None


def test_sorted_closes_newest_first_by_date():
    """날짜 필드가 있으면 최신순 정렬 — 응답 순서에 의존하지 않는다."""
    rows = [
        {"localTradedAt": "2026-08-22", "closePrice": "1,300.00"},
        {"localTradedAt": "2026-08-25", "closePrice": "1,350.00"},
        {"localTradedAt": "2026-08-24", "closePrice": "1,340.00"},
    ]
    assert _naver_sorted_closes(rows) == [1350.0, 1340.0, 1300.0]


def test_sorted_closes_keeps_order_without_date():
    rows = [{"closePrice": "10"}, {"closePrice": "20"}]
    assert _naver_sorted_closes(rows) == [10.0, 20.0]


def test_sorted_closes_drops_unparseable():
    rows = [{"closePrice": "10"}, {"closePrice": "-"}, {"closePrice": "20"}]
    assert _naver_sorted_closes(rows) == [10.0, 20.0]


# ── 실측 확정 스키마 픽스처 (2026-08-25 probe 결과) ──────────────────
# 네이버 응답 필드가 바뀌면 여기서 먼저 깨진다.

_VIX_FIXTURE = [
    {"closePrice": "15.85", "localTradedAt": "2026-08-25",
     "fluctuationsRatio": "4.76", "compareToPreviousClosePrice": "0.72",
     "compareToPreviousPrice": {"code": "2", "text": "상승"},
     "worldIndexSymbol": ".VIX", "stockExchangeType": "CBOE"},
    {"closePrice": "15.13", "localTradedAt": "2026-08-22",
     "fluctuationsRatio": "5.49", "worldIndexSymbol": ".VIX"},
    {"closePrice": "16.01", "localTradedAt": "2026-08-21",
     "fluctuationsRatio": "1.20", "worldIndexSymbol": ".VIX"},
]

_USDKRW_FIXTURE = [
    {"closePrice": "1,381.90", "localTradedAt": "2026-08-25",
     "fluctuationsRatio": "0.15", "fluctuationsType": {"code": "5", "text": "하락"},
     "cashBuyValue": "1,406.06", "cashSellValue": "1,357.74"},
    {"closePrice": "1,384.00", "localTradedAt": "2026-08-22",
     "fluctuationsRatio": "0.22"},
    {"closePrice": "1,387.00", "localTradedAt": "2026-08-21"},
]


def test_vix_fixture_parses_to_confirmed_value():
    closes = _naver_sorted_closes(_naver_rows(_VIX_FIXTURE))
    assert closes[:3] == [15.85, 15.13, 16.01]   # probe 실측과 일치


def test_usdkrw_fixture_parses_to_confirmed_value():
    closes = _naver_sorted_closes(_naver_rows(_USDKRW_FIXTURE))
    assert closes[:3] == [1381.9, 1384.0, 1387.0]


def test_change_pct_computed_from_closes_not_ratio_field():
    """등락률은 종가 차분으로 계산해야 한다 — 부호 함정 회피.

    네이버 fluctuationsRatio는 **부호 없는 절대값**이고 방향은 별도 필드로
    온다(환율 픽스처: ratio 0.15인데 실제로는 하락). 그 필드를 그대로 쓰면
    하락을 +0.15%로 표시하는 사고가 난다.
    """
    closes = _naver_sorted_closes(_naver_rows(_USDKRW_FIXTURE))
    computed = (closes[0] - closes[1]) / closes[1] * 100
    assert round(computed, 2) == -0.15                      # 하락으로 정확히 계산
    assert float(_USDKRW_FIXTURE[0]["fluctuationsRatio"]) == 0.15   # 원본은 부호 없음

    vix_closes = _naver_sorted_closes(_naver_rows(_VIX_FIXTURE))
    assert round((vix_closes[0] - vix_closes[1]) / vix_closes[1] * 100, 2) == 4.76


# ── P3: 경보는 개수가 아니라 "위험진단 가능 여부" 기준 ────────────────


def test_alert_on_total_failure():
    text = _global_market_alert_text({})
    assert text is not None and "전멸" in text


def test_alert_when_essential_axis_missing():
    """프록시 3종만 있는 실제 상황(8/24~25) — 필수 축 결손 경보."""
    gm = {"sp500": {}, "nasdaq": {}, "dow": {}}
    text = _global_market_alert_text(gm)
    assert text is not None
    assert "VIX" in text and "환율" in text
    assert "판정불가" in text


def test_silent_when_essentials_present_even_if_few():
    """VIX·환율만 확보돼도(3종) 경보 없음 — 알림 피로 해소의 핵심."""
    gm = {"vix": {}, "usdkrw": {}, "sp500": {}}
    assert _global_market_alert_text(gm) is None


def test_partial_essential_still_alerts():
    gm = {"vix": {}, "sp500": {}, "nasdaq": {}, "dow": {}}
    text = _global_market_alert_text(gm)
    assert text is not None and "환율" in text and "VIX" not in text.split("결손:")[1].split("없음")[0]


def test_full_collection_silent():
    gm = {k: {} for k in
          ("sp500", "nasdaq", "dow", "nikkei", "shanghai",
           "vix", "usdkrw", "wti", "gold", "us10y")}
    assert _global_market_alert_text(gm) is None


if __name__ == "__main__":
    for fn_name in sorted(k for k in dir() if k.startswith("test_")):
        globals()[fn_name]()
        print(f"  ✓ {fn_name}")
    print("✅ 글로벌 폴백 회귀 테스트 전부 통과")
