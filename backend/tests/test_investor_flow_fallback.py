"""수급 3단 폴백 회귀 테스트 — 2026-10-02~06 KRX 비밀번호 만료 사고 재발 방지.

실행: cd backend && python3 -m pytest tests/test_investor_flow_fallback.py -q
"""
from datetime import date

import pandas as pd

from app.collectors import investor_flow_collector as ifc
from app.collectors._krx_flow_worker import classify_login_output
from app.services.market_risk_simple import pick_stored_krx_flows


def _frame(foreign, inst, retail):
    return pd.DataFrame(
        {"순매수": [foreign * 1e8, inst * 1e8, retail * 1e8]},
        index=["외국인", "기관합계", "개인"],
    )


# ── KRX: 빈 DataFrame(휴장일)을 0억원으로 보고하지 않는다 ──────────────


def test_market_flow_from_frames_empty_is_none():
    assert ifc.market_flow_from_frames(pd.DataFrame(), pd.DataFrame(), date(2026, 9, 25)) is None
    assert ifc.market_flow_from_frames(None, None, date(2026, 9, 25)) is None


def test_market_flow_from_frames_sums_markets():
    out = ifc.market_flow_from_frames(_frame(-100, 20, 80), _frame(-50, 5, 45), date(2026, 10, 5))
    assert out == {
        "foreign_net_billion": -150.0,
        "institution_net_billion": 25.0,
        "retail_net_billion": 125.0,
        "trade_date": "2026-10-05",
    }


def test_market_flow_from_frames_partial_market():
    out = ifc.market_flow_from_frames(_frame(-100, 20, 80), pd.DataFrame(), date(2026, 10, 5))
    assert out["foreign_net_billion"] == -100.0


# ── 네이버: 개장 전 당일 0 레코드 거부 ────────────────────────────────


def _naver(bizdate, f="+1,000", i="-500", p="-500"):
    return {
        "KOSPI": {"bizdate": bizdate, "foreignValue": f, "institutionalValue": i, "personalValue": p},
        "KOSDAQ": {"bizdate": bizdate, "foreignValue": f, "institutionalValue": i, "personalValue": p},
    }


def test_naver_rejects_bizdate_mismatch():
    # 2026-10-06 08:31 실사고: 기준일 10-05인데 bizdate=20261006 · 전부 0
    assert ifc.naver_trend_to_flow(_naver("20261006", "0", "0", "0"), date(2026, 10, 5)) is None
    # 값이 있어도 날짜가 다르면 거부 (오늘값을 다른 날짜로 오염 금지)
    assert ifc.naver_trend_to_flow(_naver("20261002"), date(2026, 10, 5)) is None


def test_naver_rejects_all_zero():
    assert ifc.naver_trend_to_flow(_naver("20261005", "0", "0", "0"), date(2026, 10, 5)) is None


def test_naver_accepts_matching_date():
    out = ifc.naver_trend_to_flow(_naver("20261005"), date(2026, 10, 5))
    assert out["trade_date"] == "2026-10-05"
    assert out["foreign_net_billion"] == 2000.0 and out["institution_net_billion"] == -1000.0


def test_naver_mixed_bizdate_rejected():
    payload = _naver("20261005")
    payload["KOSDAQ"]["bizdate"] = "20261006"
    assert ifc.naver_trend_to_flow(payload, date(2026, 10, 5)) is None


# ── 워커 종료코드: 비밀번호 만료(CD010) 구분 ─────────────────────────


def test_classify_login_output():
    assert classify_login_output("KRX 로그인 시도...\nKRX 로그인 완료.") == 0
    assert classify_login_output("KRX 로그인 실패: 자격 증명을 확인하세요.") == 3
    assert classify_login_output(
        "⚠️ KRX 비밀번호 변경이 필요합니다.\nKRX 로그인 실패: 자격 증명을 확인하세요."
    ) == 4  # 만료가 로그인 실패보다 우선


def test_krx_reason_text_mentions_password_expiry():
    ifc._clear_krx_error()
    assert "비밀번호 만료" in ifc.krx_reason_text("password_expired")
    assert "KRX_PW" in ifc.krx_reason_text("password_expired")
    assert "응답 없음" in ifc.krx_reason_text("timeout")
    assert "데이터 없음" in ifc.krx_reason_text("no_data")


# ── 히스토리: 저장된 KRX 실측만 사용 ─────────────────────────────────


def test_pick_stored_krx_flows_filters_fallback_sources():
    rows = [
        {"source": "krx", "trade_date": "2026-09-30", "foreign_net_billion": -21416.0},
        {"source": "naver", "trade_date": "2026-10-02", "foreign_net_billion": 0.0},
        {"source": "cache", "trade_date": "2026-09-30", "foreign_net_billion": -21416.0},
        {"market_flow": {"source": "krx", "trade_date": "2026-09-29", "foreign_net_billion": -31259.0}},
        None, {}, {"source": "krx"},
    ]
    picked = pick_stored_krx_flows(rows)
    assert set(picked) == {"2026-09-30", "2026-09-29"}
    assert picked["2026-09-29"]["foreign_net_billion"] == -31259.0


# ── 비밀번호 수명 지문 ───────────────────────────────────────────────


def test_password_fingerprint_resets_on_change(tmp_path, monkeypatch):
    monkeypatch.setattr(ifc, "_RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(ifc, "_KRX_PW_META_PATH", tmp_path / "krx_pw_meta.json")
    assert ifc.record_krx_password_fingerprint("") is None
    m1 = ifc.record_krx_password_fingerprint("secret-1")
    assert m1["first_seen"] == date.today().isoformat()
    assert "secret" not in (tmp_path / "krx_pw_meta.json").read_text()
    m2 = ifc.record_krx_password_fingerprint("secret-1")
    assert m2["fingerprint"] == m1["fingerprint"]
    m3 = ifc.record_krx_password_fingerprint("secret-2")
    assert m3["fingerprint"] != m1["fingerprint"]
    assert ifc.krx_password_age_days() == 0
    assert ifc.krx_password_expiry_notice() is None
