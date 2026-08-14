"""모닝브리프 🔴 수정 회귀 테스트 (F1 등락률·F2 프록시·F3 판정불가).

실행: cd backend && python3 -m tests.test_brief_fixes
"""
import asyncio

from app.services.market_risk_simple import diagnose_simple
from app.services.telegram_service import _format_risk_header


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── F3: 입력 결손 → 판정불가 / 결손 명시 ──────────────────────────────


def test_risk_all_missing_is_undeterminable():
    """글로벌 전멸 + 수급 없음 → '정상'이 아니라 '판정불가' (8/10~14 실제 상황)."""
    r = _run(diagnose_simple(global_market={}, investor_flow_history=None))
    assert r["level"] == "판정불가"
    assert any("데이터 없음" in f for f in r["factors"])


def test_risk_partial_missing_noted_but_level_kept():
    """VIX만 결손 + 환율 정상 범위 → 정상 유지하되 결손 명시."""
    gm = {"usdkrw": {"close": 1350.0, "change_pct": 0.1}}
    flow = [{"foreign_net_billion": 100}] * 5
    r = _run(diagnose_simple(global_market=gm, investor_flow_history=flow))
    assert r["level"] == "정상"
    assert any("VIX" in f and "데이터 없음" in f for f in r["factors"])


def test_risk_signal_overrides_undeterminable():
    """2축 결손이어도 외인 5일 연속 매도 시그널이 뜨면 위험/주의 유지 (침묵 금지)."""
    flow = [{"foreign_net_billion": -100}] * 5
    r = _run(diagnose_simple(global_market={}, investor_flow_history=flow))
    assert r["level"] in ("주의", "위험")   # 판정불가로 강등되면 안 됨
    assert any("연속 순매도" in f for f in r["factors"])


def test_risk_normal_with_full_inputs():
    gm = {
        "vix": {"close": 15.0},
        "usdkrw": {"close": 1350.0, "change_pct": 0.1},
    }
    flow = [{"foreign_net_billion": 100}] * 5
    r = _run(diagnose_simple(global_market=gm, investor_flow_history=flow))
    assert r["level"] == "정상"
    assert r["factors"] == ["특이 위험 시그널 없음"]


def test_risk_header_renders_undeterminable():
    """텔레그램 헤더가 판정불가 레벨을 렌더링 (KeyError 없이)."""
    out = _format_risk_header({"level": "판정불가", "factors": ["진단 실행 실패"], "score": 0})
    assert "판정불가" in out


# ── F2: Finnhub 프록시 병합 (네트워크 없이 병합 로직만) ────────────────


def test_finnhub_proxy_merge_logic():
    from app.collectors import market_collector as mc
    # 프록시 대상 키·라벨 명시 확인
    assert set(mc._FINNHUB_PROXY) == {"sp500", "nasdaq", "dow"}
    for key in mc._FINNHUB_PROXY:
        assert key in mc.LABELS


# ── F1: 국내 수집이 단일(히스토리) 경로인지 ───────────────────────────


def test_domestic_uses_single_history_path():
    import inspect
    from app.collectors import stock_collector as sc
    src = inspect.getsource(sc)
    assert "fluctuationsRatio" not in src, "장전 0.0 반환하는 basic API 경로 잔존"
    assert "fetch_close_with_change" in src


if __name__ == "__main__":
    for fn_name in sorted(k for k in dir() if k.startswith("test_")):
        globals()[fn_name]()
        print(f"  ✓ {fn_name}")
    print("✅ 브리프 수정 회귀 테스트 전부 통과")
