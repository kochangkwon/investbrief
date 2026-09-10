"""대형주 전용 수급 임계 (STOCKAI_LARGECAP_TRACK L1, 2026-09-10).

단일 잣대(공매도 15%·대차 1.5배)가 대형주의 평상시 수치를 경고로 읽던 문제.
실측 탈락 사례(삼성바이오 F8 1.57 / 현대차 F7 17.6% / LG이노텍 F8 1.51)가
대형주 임계(25%·2.0)로는 통과해야 한다. 중소형 임계는 무변경.
"""
from app.services.prefilter_service import (
    PREFILTER_LARGECAP_MIN_MCAP,
    _check_supply_demand_filter,
)

MCAP_LARGE = PREFILTER_LARGECAP_MIN_MCAP          # 정확히 10조 — 경계 포함
MCAP_SMALL = PREFILTER_LARGECAP_MIN_MCAP - 1


def _sig(sw5=None, rising=False, surge=None):
    return {"short_weight_5d": sw5, "short_weight_rising": rising,
            "lending_surge": surge}


def test_real_incident_cases_pass_as_largecap():
    """실측 탈락 3건 — 대형주 임계로는 전부 통과."""
    cases = [
        _sig(surge=1.57),                 # 삼성바이오 F8
        _sig(sw5=17.6, rising=True),      # 현대차 F7
        _sig(surge=1.51),                 # LG이노텍 F8
    ]
    for sig in cases:
        ok, reasons, _ = _check_supply_demand_filter(sig, mcap=MCAP_LARGE)
        assert ok is True, reasons


def test_smallcap_thresholds_unchanged():
    """같은 수치가 중소형(또는 시총 미확인)에선 기존대로 탈락."""
    for mcap in (MCAP_SMALL, None):
        ok, reasons, _ = _check_supply_demand_filter(_sig(surge=1.57), mcap=mcap)
        assert ok is False and any(r.startswith("F8:") for r in reasons)
        ok, reasons, _ = _check_supply_demand_filter(
            _sig(sw5=17.6, rising=True), mcap=mcap)
        assert ok is False and any(r.startswith("F7:") for r in reasons)


def test_largecap_still_fails_above_its_own_limit():
    """대형주도 자기 임계는 넘으면 탈락 — 완화지 면제가 아니다. [L] 표기 확인."""
    ok, reasons, _ = _check_supply_demand_filter(
        _sig(sw5=26.0, rising=True, surge=2.1), mcap=MCAP_LARGE)
    assert ok is False
    assert any(r.startswith("F7[L]:") for r in reasons)
    assert any(r.startswith("F8[L]:") for r in reasons)


def test_signal_none_passthrough_unchanged():
    ok, reasons, metrics = _check_supply_demand_filter(None, mcap=MCAP_LARGE)
    assert ok is None and reasons == [] and metrics == {}
