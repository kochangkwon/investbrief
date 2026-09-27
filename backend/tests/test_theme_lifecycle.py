"""테마 수명주기 자동화 회귀 테스트 — 키워드 4원칙 게이트 · 상한 교체 · 리포트.

실행: cd backend && python3 -m pytest tests/test_theme_lifecycle.py -q
      또는 python3 -m tests.test_theme_lifecycle
"""
from datetime import datetime, timedelta

from app.services import theme_discovery_service as tds
from app.services.theme_discovery_service import (
    MAX_ACTIVE_THEMES,
    MIN_KEYWORDS_PER_THEME,
    ROTATION_VICTIM_MAX_SCORE,
    build_keyword_semantic_prompt,
    format_auto_register_report,
    is_generic_keyword,
    keyword_duplicates_existing,
    select_rotation_victim,
    validate_theme_keywords,
)


# ── 원칙 3: 범용어 형태 규칙 ──────────────────────────────────────────


def test_generic_keyword_rules():
    # 발굴 프롬프트의 원칙 3 예시는 반드시 걸려야 한다
    assert is_generic_keyword("차세대반도체")
    assert is_generic_keyword("공급망 재편")
    assert is_generic_keyword("소재혁신")
    # 단독 광의어
    assert is_generic_keyword("AI")
    assert is_generic_keyword("로봇")
    assert is_generic_keyword("성장")
    assert is_generic_keyword("x")  # 1글자
    # 구체어는 통과
    assert not is_generic_keyword("HVDC")
    assert not is_generic_keyword("변압기")
    assert not is_generic_keyword("초고압케이블")
    assert not is_generic_keyword("로봇감속기")
    assert not is_generic_keyword("345kV")


# ── 원칙 4: 기존 키워드 중복 (정확·포함) ──────────────────────────────


def test_keyword_duplicates_existing():
    existing = {"HVDC", "변압기", "초고압 케이블"}
    assert keyword_duplicates_existing("hvdc", existing) == "HVDC"          # 대소문자 무시
    assert keyword_duplicates_existing("HVDC케이블", existing) == "HVDC"    # 기존 ⊂ 신규
    assert keyword_duplicates_existing("초고압케이블", existing) == "초고압 케이블"  # 공백 무시
    assert keyword_duplicates_existing("케이블", existing) == "초고압 케이블"  # 신규 ⊂ 기존 (더 넓은 매칭)
    assert keyword_duplicates_existing("리튬염", existing) is None
    assert keyword_duplicates_existing("", existing) is None


# ── 기계 판정 종합 ───────────────────────────────────────────────────


def test_validate_theme_keywords_drops_violations_and_keeps_rest():
    corp = {"한화시스템", "포스코인터내셔널", "LS일렉트릭"}
    existing = {"HVDC"}
    v = validate_theme_keywords(
        ["한화시스템", "변압기", "차세대반도체", "HVDC케이블", "ESS 배터리", "변압기"],
        existing, corp,
    )
    assert v.kept == ["변압기", "ESS 배터리"]           # 중복 "변압기"는 1회만
    reasons = dict(v.dropped)
    assert reasons["한화시스템"] == "원칙1 기업명"
    assert reasons["차세대반도체"] == "원칙3 범용어"
    assert reasons["HVDC케이블"].startswith("원칙4 중복")
    assert v.ok  # kept 2개 ≥ MIN_KEYWORDS_PER_THEME


def test_validate_theme_keywords_group_name_and_min_count():
    v = validate_theme_keywords(["삼성", "변압기"], set(), set())
    assert v.kept == ["변압기"]
    assert not v.ok                                     # 1개 < 최소 2개
    assert "유효 키워드 1개" in v.reason
    assert "삼성(원칙1 기업명)" in v.reason
    assert MIN_KEYWORDS_PER_THEME == 2


def test_validate_theme_keywords_all_pass():
    v = validate_theme_keywords(["HVDC", "변압기", "345kV"], set(), set())
    assert v.kept == ["HVDC", "변압기", "345kV"]
    assert v.dropped == []
    assert v.ok
    assert v.reason == ""


def test_semantic_prompt_mentions_rules_and_format():
    p = build_keyword_semantic_prompt("전력기기 슈퍼사이클", ["HVDC", "변압기"])
    assert "전력기기 슈퍼사이클" in p and "HVDC, 변압기" in p
    for rule in ("원칙 1", "원칙 2", "원칙 3"):
        assert rule in p
    assert "VERDICT: YES" in p and "VERDICT: NO" in p


# ── 상한 교체 대상 선택 ─────────────────────────────────────────────


def _stats(now):
    old = now - timedelta(days=60)
    return [
        {"name": "A_productive", "created_at": old, "yes_30d": 5, "stocks_60d": 3},
        {"name": "B_zero_old", "created_at": old - timedelta(days=30), "yes_30d": 0, "stocks_60d": 0},
        {"name": "C_zero_newer", "created_at": old, "yes_30d": 0, "stocks_60d": 0},
        {"name": "D_one", "created_at": old, "yes_30d": 1, "stocks_60d": 0},
        {"name": "E_fresh_zero", "created_at": now - timedelta(days=3), "yes_30d": 0, "stocks_60d": 0},
    ]


def test_select_rotation_victim_picks_lowest_then_oldest():
    now = datetime(2026, 9, 28, 7, 45)
    grace = now - timedelta(days=tds.ROTATION_GRACE_DAYS)
    victim = select_rotation_victim(_stats(now), grace_cutoff=grace)
    assert victim["name"] == "B_zero_old"   # score 0 동점 중 가장 오래된 것
    assert victim["score"] == 0


def test_select_rotation_victim_respects_grace_exclude_and_threshold():
    now = datetime(2026, 9, 28, 7, 45)
    grace = now - timedelta(days=tds.ROTATION_GRACE_DAYS)
    stats = _stats(now)
    # 이미 교체된 테마 제외 → 다음 0점 테마
    v = select_rotation_victim(stats, grace_cutoff=grace, exclude={"B_zero_old"})
    assert v["name"] == "C_zero_newer"
    # 0점들 제외 → score 1 (임계 이하) 선택
    v = select_rotation_victim(stats, grace_cutoff=grace, exclude={"B_zero_old", "C_zero_newer"})
    assert v["name"] == "D_one" and v["score"] == ROTATION_VICTIM_MAX_SCORE
    # 남은 건 생산성 높은 A와 유예기간 중인 E → 교체 대상 없음 (보류)
    v = select_rotation_victim(
        stats, grace_cutoff=grace, exclude={"B_zero_old", "C_zero_newer", "D_one"}
    )
    assert v is None


def test_select_rotation_victim_never_evicts_productive_theme():
    now = datetime(2026, 9, 28, 7, 45)
    grace = now - timedelta(days=tds.ROTATION_GRACE_DAYS)
    stats = [{"name": "P", "created_at": now - timedelta(days=90), "yes_30d": 2, "stocks_60d": 0}]
    assert select_rotation_victim(stats, grace_cutoff=grace) is None


# ── 텔레그램 리포트 블록 ───────────────────────────────────────────


def test_format_auto_register_report_sections():
    report = format_auto_register_report(
        registered=[{"name": "전력기기", "keywords": ["HVDC", "변압기"],
                     "dropped": [("한화시스템", "원칙1 기업명")]}],
        replaced=[({"name": "구테마", "yes_30d": 0, "stocks_60d": 0}, "전력기기")],
        deferred=["보류테마"],
        manual=[({"name": "수동테마", "keywords": ["AI", "데이터센터"]}, "AI 판정 NO: 원칙2 데이터센터")],
        skipped_dup=["기존테마"],
        active_count=15,
    )
    assert "신규 테마 1건 자동 등록" in report
    assert "HVDC, 변압기" in report
    assert "키워드 정리: 한화시스템(원칙1 기업명)" in report
    assert "구테마 → 전력기기" in report and "30일 YES 0건" in report
    assert '/theme-on "테마명"' in report
    assert "상한 초과 보류 1건" in report and f"15/{MAX_ACTIVE_THEMES}" in report
    assert '/theme-add "수동테마" AI,데이터센터' in report
    assert "원칙2 데이터센터" in report
    assert "기존 테마 1건 스킵: 기존테마" in report
    assert f"📊 활성 테마 15/{MAX_ACTIVE_THEMES}" in report


def test_format_auto_register_report_minimal():
    report = format_auto_register_report(
        registered=[], replaced=[], deferred=[], manual=[], skipped_dup=[], active_count=9,
    )
    assert "자동 등록" not in report and "교체" not in report
    assert f"활성 테마 9/{MAX_ACTIVE_THEMES}" in report


# ── 텔레그램 /theme-on·off 인자 파싱 ─────────────────────────────────


def test_parse_quoted_theme_name():
    from app.services.telegram_bot import _parse_quoted_theme_name
    assert _parse_quoted_theme_name('"전력기기 슈퍼사이클"', "u") == ("전력기기 슈퍼사이클", "")
    name, err = _parse_quoted_theme_name("전력기기", '/theme-on "테마명"')
    assert name is None and "큰따옴표" in err
    name, err = _parse_quoted_theme_name("", '/theme-off "테마명"')
    assert name is None and err.startswith("사용법")


if __name__ == "__main__":
    import sys
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failed += 1
                print(f"FAIL {name}: {e}")
    sys.exit(1 if failed else 0)
