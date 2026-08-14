"""종목 선정·테마 스캔 개선 회귀 테스트 (2026-08-14 검토 반영).

순수 함수 위주 — API/DB 불필요 (단, 모듈 import에 FDR/httpx 등 필요).

실행:
    cd backend && python3 -m tests.test_selection_fixes
    # 또는: pytest tests/test_selection_fixes.py
"""
from app.services import theme_radar_service as radar
from app.services.feature_validation_service import extract_picker_signals
from app.services.prefilter_service import (
    _check_price_filters,
    _check_risk_flags_filter,
)
from app.services.stock_picker_service import _passes_absolute_cut, _score


# ── 1. 종목명 규칙: 상장사 화이트리스트 · GROUP 조건화 ─────────────────


def test_noise_token_still_blocks_plain_noise():
    """조사·숫자·금액단위 노이즈는 여전히 차단된다 (비상장 토큰)."""
    assert radar._is_noise_token("발표했다는")      # 조사 어미
    assert radar._is_noise_token("3000억원")        # 금액
    assert radar._is_noise_token("150달러")         # 숫자+단위
    assert not radar._is_noise_token("클로봇")      # 정상 종목명


def test_listed_name_whitelist_bypasses_noise_rules():
    """화이트리스트에 있는 상장사명은 노이즈 규칙을 우회한다.

    (에코프로: 끝 '로' / 쎄트렉아이: 끝 '이' / 대원: 끝 '원' — 전부
    기존 규칙에 오차단되던 실제 상장사)
    """
    for name in ("에코프로", "쎄트렉아이", "LG디스플레이", "대원", "카카오페이"):
        # 노이즈 규칙 자체에는 걸리지만…
        assert radar._is_noise_token(name), f"{name}: 규칙 미변경 전제 깨짐"
    # …후보 루프의 화이트리스트 분기 (candidate not in _listed_names and noise)
    listed = {"에코프로", "쎄트렉아이", "LG디스플레이", "대원", "카카오페이"}
    for name in listed:
        blocked = name not in listed and radar._is_noise_token(name)
        assert not blocked, f"{name}: 화이트리스트 우회 실패"


def test_group_prefix_conditional():
    """그룹명 단독 토큰: 계열사 동반 시에만 차단."""
    # 계열사명 동반 → 차단 (지주사 오탐)
    assert radar._group_prefix_is_noise(
        "한화", "한화에어로스페이스 수주 확대에 한화 그룹주 강세"
    )
    # 단독 등장 → 통과 (Claude 검증에 위임 — 신세계·오리온 등 본체 복구)
    assert not radar._group_prefix_is_noise("신세계", "신세계 면세점 매출 회복세")
    assert not radar._group_prefix_is_noise("오리온", "오리온 K푸드 수출 확대")


# ── 2. 프리필터: 가격 fail-closed · F5 재무 리스크 ────────────────────


def test_price_filter_fail_closed_on_insufficient_data():
    """가격 데이터 <60일 → 보수적 통과(None)가 아니라 명시적 제외(False)."""
    passed, reasons, _ = _check_price_filters([])
    assert passed is False and reasons
    passed, reasons, _ = _check_price_filters([1000.0] * 59)
    assert passed is False and reasons


def test_price_filter_normal_pass():
    """60일 이상 평탄한 가격 → 통과 + 메트릭 산출."""
    closes = [10000.0 + (i % 7) * 10 for i in range(90)]
    passed, reasons, metrics = _check_price_filters(closes)
    assert passed is True and not reasons
    assert "rsi" in metrics and "ma20_ratio" in metrics


def test_risk_flags_filter_policies():
    """F5: 위험 그룹 존재 → 제외 / 주의 이하 → 통과 / 조회실패·error → 보수적 통과."""
    danger_report = {"flags": {
        "C_차입리스크": {"level": "위험"},
        "D_희석리스크": {"level": "정상"},
    }}
    passed, reasons, metrics = _check_risk_flags_filter(danger_report)
    assert passed is False and "F5" in reasons[0] and "C_차입리스크" in reasons[0]

    caution_report = {"flags": {"C_차입리스크": {"level": "주의"}}}
    passed, _, metrics = _check_risk_flags_filter(caution_report)
    assert passed is True and metrics["risk_levels"]["C_차입리스크"] == "주의"

    assert _check_risk_flags_filter(None)[0] is None                 # 조회 실패
    assert _check_risk_flags_filter({"error": "corp 매핑 실패"})[0] is None  # 커버리지 밖


# ── 3. 검증 신호 추출: 홀드아웃 통과분만 ─────────────────────────────


def test_extract_picker_signals_requires_holdout():
    """train만 좋은 신호(스누핑)는 탈락, train+val+robust 모두 통과만 채택."""
    result = {"features": [
        # 채택: train ≥2, val >0, robust
        {"feature": "good", "train_diff": 3.0, "val_diff": 1.2,
         "consistent": True, "median": 5.0, "diff_10d": 2.5},
        # 탈락: val에서 방향 뒤집힘 (in-sample 스누핑 차단)
        {"feature": "flip", "train_diff": 4.0, "val_diff": -0.5,
         "consistent": True, "median": 1.0, "diff_10d": 2.0},
        # 탈락: robust 아님
        {"feature": "fragile", "train_diff": 3.0, "val_diff": 0.8,
         "consistent": False, "median": 1.0, "diff_10d": 2.2},
        # 탈락: train 기준 미달
        {"feature": "weak", "train_diff": 1.0, "val_diff": 0.5,
         "consistent": True, "median": 1.0, "diff_10d": 1.5},
    ]}
    signals = extract_picker_signals(result)
    assert [s["feature"] for s in signals] == ["good"]
    assert signals[0]["weight"] == 3.0      # 전체 diff가 아닌 train_diff (누수 방지)
    assert signals[0]["median"] == 5.0


# ── 4. 픽커: 절대 컷 ─────────────────────────────────────────────────


def test_absolute_cut():
    signals = [
        {"feature": "a", "weight": 3.0, "median": 10.0},
        {"feature": "b", "weight": 1.0, "median": 5.0},
    ]
    # a(가중 3/4)가 중앙값 이상 → 통과
    assert _passes_absolute_cut({"a": 12.0, "b": 1.0}, signals)
    # b(가중 1/4)만 중앙값 이상 → 탈락
    assert not _passes_absolute_cut({"a": 8.0, "b": 6.0}, signals)
    # 레거시 신호(median 없음) → 컷 무력 (통과)
    legacy = [{"feature": "a", "weight": 3.0}]
    assert _passes_absolute_cut({"a": -999}, legacy)


def test_score_filters_and_ranks():
    signals = [{"feature": "a", "weight": 2.0, "median": 5.0}]
    candidates = [
        {"code": "1", "name": "상", "theme": "t", "features": {"a": 9.0}},
        {"code": "2", "name": "중", "theme": "t", "features": {"a": 6.0}},
        {"code": "3", "name": "컷탈락", "theme": "t", "features": {"a": 1.0}},
        {"code": "4", "name": "결측", "theme": "t", "features": {}},
    ]
    scored = _score(candidates, signals)
    assert [c["code"] for c in scored] == ["1", "2"]   # 컷탈락·결측 제외, 내림차순
    assert scored[0]["score"] > scored[1]["score"]


if __name__ == "__main__":
    for fn_name in sorted(k for k in dir() if k.startswith("test_")):
        globals()[fn_name]()
        print(f"  ✓ {fn_name}")
    print("✅ 종목 선정·테마 스캔 회귀 테스트 전부 통과")
