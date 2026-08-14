"""재무 리스크 플래그 — DART 공시 재무데이터 기반 네거티브 스크리닝.

계산 함수는 모두 순수 함수(입력: 재무데이터 dict → 출력: 지표 dict).
추정·보간 없음. 계정이 없으면 null + 사유를 기록한다.

계정 매칭 사양은 2026-08-09 DART 실호출로 검증했다(docs/dart_samples/).
검증에서 확인된 사실:
  - 건설중인자산은 재무상태표 별도 계정으로 제출되지 않는 기업이 많다(주석 기재).
    → A지표군은 해당 기업에서 null.
  - 현금흐름표 조정 항목을 "조정" 한 줄로 뭉쳐 제출하는 기업(삼성전자, 에코프로비엠 등)은
    감가상각비·무형자산상각비·이자비용 계정이 없다. → EBITDA/이자보상배율 null.
  - account_id가 "-표준계정코드 미사용-"인 계정이 있으므로(삼성전자 단기차입금 등)
    account_id 매칭 후 account_nm 정확일치로 폴백한다.
  - 유동/비유동 리스부채가 같은 account_nm으로 2행 오므로 부채는 행 단위 합산한다.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

THRESHOLD_PATH = Path(__file__).resolve().parents[2] / "config" / "risk_thresholds.json"

_LEVEL_ORDER = {"정상": 0, "주의": 1, "위험": 2}

# 손익계산서 sj_div — 기업에 따라 CIS(포괄손익) 또는 IS(손익)로 온다
_IS_DIVS = ("CIS", "IS")

# 이자발생부채 구성 계정 (재무상태표)
_DEBT_IDS = {
    "ifrs-full_ShorttermBorrowings",
    "ifrs-full_CurrentPortionOfLongtermBorrowings",
    "ifrs-full_LongtermBorrowings",
    "ifrs-full_NoncurrentPortionOfNoncurrentLoansReceived",
    "ifrs-full_NoncurrentPortionOfNoncurrentBondsIssued",
    "dart_CurrentPortionOfBonds",
    "ifrs-full_CurrentLeaseLiabilities",
    "ifrs-full_NoncurrentLeaseLiabilities",
}
_DEBT_NAMES = {
    "단기차입금",
    "장기차입금",
    "유동성장기차입금",
    "유동성장기부채",
    "사채",
    "유동성사채",
    "리스부채",
    "유동 리스부채",
    "비유동 리스부채",
}

# 단일 계정 사양: key -> (sj_div 후보, account_id 후보, account_nm 후보)
_SPECS: dict[str, tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = {
    "ppe": (
        ("BS",),
        ("ifrs-full_PropertyPlantAndEquipment",),
        ("유형자산",),
    ),
    "cip": (
        ("BS",),
        ("ifrs-full_ConstructionInProgress", "dart_ConstructionInProgress"),
        ("건설중인자산", "건설중자산"),
    ),
    "cash": (
        ("BS",),
        ("ifrs-full_CashAndCashEquivalents",),
        ("현금및현금성자산",),
    ),
    "operating_profit": (
        _IS_DIVS,
        ("dart_OperatingIncomeLoss", "ifrs-full_ProfitLossFromOperatingActivities"),
        ("영업이익", "영업이익(손실)", "영업손실"),
    ),
    "interest_expense": (
        _IS_DIVS + ("CF",),
        ("ifrs-full_InterestExpense", "dart_AdjustmentsForInterestExpenses"),
        ("이자비용", "이자비용 조정", "이자비용에 대한 조정"),
    ),
    "ocf": (
        ("CF",),
        ("ifrs-full_CashFlowsFromUsedInOperatingActivities",),
        ("영업활동현금흐름", "영업활동으로 인한 현금흐름"),
    ),
    "capex_tangible": (
        ("CF",),
        ("ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",),
        ("유형자산의 취득",),
    ),
    "capex_intangible": (
        ("CF",),
        ("ifrs-full_PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities",),
        ("무형자산의 취득",),
    ),
    "depreciation": (
        ("CF",),
        ("ifrs-full_AdjustmentsForDepreciationExpense",),
        ("감가상각비에 대한 조정", "감가상각비"),
    ),
    "amortization": (
        ("CF",),
        ("ifrs-full_AdjustmentsForAmortisationExpense",),
        ("무형자산상각비에 대한 조정", "무형자산상각비"),
    ),
}

_TERM_FIELDS = {
    "term": "thstrm_amount",
    "prior": "frmtrm_amount",
    "prior2": "bfefrmtrm_amount",
}


# --------------------------------------------------------------------------
# 임계값 로딩 (파일 mtime 감지 — 서버 재시작 없이 반영)
# --------------------------------------------------------------------------
_threshold_cache: dict[str, Any] = {"mtime": None, "data": {}}


def load_thresholds() -> dict[str, Any]:
    try:
        mtime = THRESHOLD_PATH.stat().st_mtime
    except OSError:
        logger.error("임계값 파일 없음: %s", THRESHOLD_PATH)
        return {}

    if _threshold_cache["mtime"] != mtime:
        try:
            _threshold_cache["data"] = json.loads(
                THRESHOLD_PATH.read_text(encoding="utf-8")
            )
            _threshold_cache["mtime"] = mtime
            logger.info("임계값 재로딩: %s", THRESHOLD_PATH)
        except Exception:
            logger.exception("임계값 파일 파싱 실패")
            return _threshold_cache["data"]

    return _threshold_cache["data"]


# --------------------------------------------------------------------------
# 파싱 (순수 함수)
# --------------------------------------------------------------------------
def _to_float(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    s = str(raw).replace(",", "").strip()
    if not s or s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def extract_accounts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """DART 재무제표 rows → 지표 계산용 계정 dict.

    Returns:
        {
          "accounts": {key: {"term":float|None, "prior":..., "prior2":...,
                             "source": "계정과목명 [account_id]"}},
          "debt": {"term":..., "prior":..., "prior2":...,
                   "included_accounts": ["단기차입금", ...]},
          "period_names": {"term": "제 10 기", ...},
        }
    """
    accounts: dict[str, Any] = {}

    for key, (divs, ids, names) in _SPECS.items():
        match = None
        # account_id 우선
        for row in rows:
            if row.get("sj_div") in divs and row.get("account_id") in ids:
                match = row
                break
        # account_nm 정확일치 폴백
        if match is None:
            for row in rows:
                if row.get("sj_div") in divs and (row.get("account_nm") or "").strip() in names:
                    match = row
                    break
        if match is None:
            continue

        accounts[key] = {
            term: _to_float(match.get(field)) for term, field in _TERM_FIELDS.items()
        }
        accounts[key]["source"] = (
            f"{match.get('sj_nm', '')}/{match.get('account_nm', '')} "
            f"[{match.get('account_id', '')}]"
        )

    # 이자발생부채 — 행 단위 합산
    debt: dict[str, Any] = {"term": None, "prior": None, "prior2": None,
                            "included_accounts": []}
    sums: dict[str, Optional[float]] = {"term": None, "prior": None, "prior2": None}
    for row in rows:
        if row.get("sj_div") != "BS":
            continue
        name = (row.get("account_nm") or "").strip()
        if row.get("account_id") not in _DEBT_IDS and name not in _DEBT_NAMES:
            continue
        debt["included_accounts"].append(f"{name} [{row.get('account_id', '')}]")
        for term, field in _TERM_FIELDS.items():
            val = _to_float(row.get(field))
            if val is not None:
                sums[term] = (sums[term] or 0.0) + val
    debt.update(sums)

    period_names = {}
    if rows:
        period_names = {
            "term": rows[0].get("thstrm_nm"),
            "prior": rows[0].get("frmtrm_nm"),
            "prior2": rows[0].get("bfefrmtrm_nm"),
        }

    return {"accounts": accounts, "debt": debt, "period_names": period_names}


# --------------------------------------------------------------------------
# 지표 계산 (순수 함수)
# --------------------------------------------------------------------------
def _get(accounts: dict[str, Any], key: str, term: str = "term") -> Optional[float]:
    entry = accounts.get(key)
    return entry.get(term) if entry else None


def _ratio(numer: Optional[float], denom: Optional[float]) -> Optional[float]:
    if numer is None or denom is None or denom == 0:
        return None
    return numer / denom


def compute_group_a(data: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """A: 감가상각 절벽 (건설중인자산)."""
    acc = data["accounts"]
    unavailable: list[dict[str, str]] = []

    cip_term = _get(acc, "cip")
    cip_prior = _get(acc, "cip", "prior")
    ppe_term = _get(acc, "ppe")

    cip_ratio = _ratio(cip_term, ppe_term)
    if cip_ratio is None:
        reason = (
            "건설중인자산 계정 없음 (재무상태표 별도 계정 미제출)"
            if cip_term is None
            else "유형자산 총액 없음"
        )
        unavailable.append({"metric": "A1", "reason": reason})

    cip_yoy = None
    if cip_term is not None and cip_prior:
        cip_yoy = (cip_term - cip_prior) / cip_prior
    else:
        unavailable.append({
            "metric": "A2",
            "reason": "건설중인자산 계정 없음" if cip_term is None else "전기 건설중인자산 데이터 없음",
        })

    return {"cip_ratio": cip_ratio, "cip_yoy": cip_yoy}, unavailable


def compute_group_b(data: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """B: 이익-현금 괴리."""
    acc = data["accounts"]
    unavailable: list[dict[str, str]] = []

    ocf = _get(acc, "ocf")
    op = _get(acc, "operating_profit")

    ocf_gap = None
    if ocf is not None and op is not None:
        ocf_gap = ocf - op
    else:
        missing = "영업활동현금흐름" if ocf is None else "영업이익"
        unavailable.append({"metric": "B1", "reason": f"{missing} 계정 없음"})

    def _capex(term: str) -> Optional[float]:
        tan = _get(acc, "capex_tangible", term)
        intan = _get(acc, "capex_intangible", term)
        if tan is None and intan is None:
            return None
        return (tan or 0.0) + (intan or 0.0)

    capex_term = _capex("term")
    capex_ratio = None
    if capex_term is None:
        unavailable.append({"metric": "B2", "reason": "유형/무형자산 취득 계정 없음"})
    elif ocf is None:
        unavailable.append({"metric": "B2", "reason": "영업활동현금흐름 계정 없음"})
    elif ocf <= 0:
        unavailable.append({"metric": "B2", "reason": "OCF<=0"})
    else:
        capex_ratio = capex_term / ocf

    over_years = 0
    compared = 0
    for term in ("term", "prior", "prior2"):
        capex_t = _capex(term)
        ocf_t = _get(acc, "ocf", term)
        if capex_t is None or ocf_t is None:
            continue
        compared += 1
        if capex_t > ocf_t:
            over_years += 1
    capex_over_years: Optional[int] = over_years
    if compared == 0:
        capex_over_years = None
        unavailable.append({"metric": "B3", "reason": "CAPEX/OCF 비교 가능한 연도 없음"})

    return {
        "ocf_gap": ocf_gap,
        "capex_ratio": capex_ratio,
        "capex_초과연수": capex_over_years,
        "capex_비교연도수": compared,
    }, unavailable


def compute_group_c(data: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """C: 차입 리스크."""
    acc = data["accounts"]
    debt = data["debt"]
    unavailable: list[dict[str, str]] = []

    cash = _get(acc, "cash")
    net_debt = None
    if debt["term"] is not None and cash is not None:
        net_debt = debt["term"] - cash
    else:
        missing = "이자발생부채 계정 없음" if debt["term"] is None else "현금및현금성자산 계정 없음"
        unavailable.append({"metric": "C1", "reason": missing})

    op = _get(acc, "operating_profit")
    dep = _get(acc, "depreciation")
    amort = _get(acc, "amortization")
    ebitda = None
    if op is None:
        unavailable.append({"metric": "C2", "reason": "영업이익 계정 없음"})
    elif dep is None or amort is None:
        unavailable.append({
            "metric": "C2",
            "reason": "현금흐름표에 감가상각비/무형자산상각비 계정 없음 (조정 항목 통합 제출)",
        })
    else:
        ebitda = op + dep + amort

    net_debt_to_ebitda = None
    if net_debt is None or ebitda is None:
        unavailable.append({"metric": "C3", "reason": "net_debt 또는 EBITDA 산출 불가"})
    elif ebitda <= 0:
        unavailable.append({"metric": "C3", "reason": "EBITDA<=0"})
    else:
        net_debt_to_ebitda = net_debt / ebitda

    interest = _get(acc, "interest_expense")
    interest_coverage = None
    if op is None or interest is None:
        unavailable.append({
            "metric": "C4",
            "reason": "영업이익 계정 없음" if op is None else "이자비용 계정 없음",
        })
    elif interest <= 0:
        unavailable.append({"metric": "C4", "reason": "이자비용<=0"})
    else:
        interest_coverage = op / interest

    debt_growth = None
    if debt["term"] is not None and debt["prior"]:
        debt_growth = (debt["term"] - debt["prior"]) / debt["prior"]
    else:
        unavailable.append({"metric": "C5", "reason": "전기 이자발생부채 데이터 없음"})

    return {
        "net_debt": net_debt,
        "ebitda": ebitda,
        "net_debt_to_ebitda": net_debt_to_ebitda,
        "interest_coverage": interest_coverage,
        "debt_growth": debt_growth,
    }, unavailable


def compute_group_d(
    decisions: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, str]], Optional[str]]:
    """D: 희석 리스크 (유상증자). 최근 24개월 내 가장 최근 결정 1건 기준."""
    unavailable: list[dict[str, str]] = []
    if not decisions:
        return (
            {"dilution_ratio": None, "purpose_breakdown": None, "non_growth_ratio": None},
            [{"metric": "D", "reason": "최근 24개월 유상증자 결정 공시 없음"}],
            None,
        )

    latest = max(decisions, key=lambda d: d.get("rcept_no", ""))
    rcept_no = latest.get("rcept_no", "")
    disclosure_date = f"{rcept_no[:4]}-{rcept_no[4:6]}-{rcept_no[6:8]}" if len(rcept_no) >= 8 else None

    new_shares = _to_float(latest.get("nstk_ostk_cnt"))
    before_shares = _to_float(latest.get("bfic_tisstk_ostk"))
    dilution_ratio = _ratio(new_shares, before_shares)
    if dilution_ratio is None:
        unavailable.append({"metric": "D1", "reason": "신주 수 또는 증자 전 발행주식수 데이터 없음"})

    purpose_fields = {
        "시설자금": "fdpp_fclt",
        "영업양수자금": "fdpp_bsninh",
        "운영자금": "fdpp_op",
        "채무상환자금": "fdpp_dtrp",
        "타법인증권취득자금": "fdpp_ocsa",
        "기타": "fdpp_etc",
    }
    breakdown = {
        label: _to_float(latest.get(field)) for label, field in purpose_fields.items()
    }
    total = sum(v for v in breakdown.values() if v is not None)

    non_growth_ratio = None
    if total <= 0:
        unavailable.append({"metric": "D2", "reason": "목적별 조달금액 데이터 없음"})
        unavailable.append({"metric": "D3", "reason": "목적별 조달금액 데이터 없음"})
        breakdown = None
    else:
        non_growth = (breakdown["운영자금"] or 0.0) + (breakdown["채무상환자금"] or 0.0)
        non_growth_ratio = non_growth / total

    return (
        {
            "dilution_ratio": dilution_ratio,
            "purpose_breakdown": breakdown,
            "purpose_total": total or None,
            "non_growth_ratio": non_growth_ratio,
            "발행방식": latest.get("ic_mthn"),
        },
        unavailable,
        disclosure_date,
    )


# --------------------------------------------------------------------------
# 판정
# --------------------------------------------------------------------------
def judge(value: Optional[float], cfg: Optional[dict[str, Any]]) -> str:
    """단일 지표 판정: 정상 / 주의 / 위험 / 판정불가."""
    if value is None or not cfg:
        return "판정불가"

    below = cfg.get("direction") == "below"
    danger, caution = cfg.get("danger"), cfg.get("caution")

    if below:
        if danger is not None and value <= danger:
            return "위험"
        if caution is not None and value <= caution:
            return "주의"
    else:
        if danger is not None and value >= danger:
            return "위험"
        if caution is not None and value >= caution:
            return "주의"
    return "정상"


def _group_level(levels: list[str]) -> str:
    scored = [lv for lv in levels if lv != "판정불가"]
    if not scored:
        return "판정불가"
    return max(scored, key=lambda lv: _LEVEL_ORDER[lv])


# --------------------------------------------------------------------------
# 리포트 조립 (순수 함수)
# --------------------------------------------------------------------------
def build_report(
    stock_code: str,
    corp_name: str,
    fs_div: str,
    annual: dict[str, Any],
    decisions: list[dict[str, Any]],
    latest_quarter: Optional[str],
    query_date: str,
    bsns_year: int,
) -> dict[str, Any]:
    """지표 계산 + 판정 → 최종 출력 스키마."""
    th = load_thresholds()

    a_metrics, a_unavail = compute_group_a(annual)
    b_metrics, b_unavail = compute_group_b(annual)
    c_metrics, c_unavail = compute_group_c(annual)
    d_metrics, d_unavail, disclosure_date = compute_group_d(decisions)

    a_levels = [
        judge(a_metrics["cip_ratio"], th.get("A1_cip_ratio")),
        judge(a_metrics["cip_yoy"], th.get("A2_cip_yoy")),
    ]
    b_levels = [
        judge(b_metrics["capex_ratio"], th.get("B2_capex_ratio")),
        judge(b_metrics["capex_초과연수"], th.get("B3_capex_초과연수")),
    ]
    c_levels = [
        judge(c_metrics["net_debt_to_ebitda"], th.get("C3_net_debt_to_ebitda")),
        judge(c_metrics["interest_coverage"], th.get("C4_interest_coverage")),
        judge(c_metrics["debt_growth"], th.get("C5_debt_growth")),
    ]
    d_levels = [
        judge(d_metrics["dilution_ratio"], th.get("D1_dilution_ratio")),
        judge(d_metrics["non_growth_ratio"], th.get("D3_non_growth_ratio")),
    ]

    fiscal_years = [str(bsns_year - 2), str(bsns_year - 1), str(bsns_year)]

    unavailable = a_unavail + b_unavail + c_unavail + d_unavail

    return {
        "stock_code": stock_code,
        "corp_name": corp_name,
        "fs_basis": fs_div,
        "fiscal_years": fiscal_years,
        "period_names": annual.get("period_names", {}),
        "latest_quarter": latest_quarter,
        "flags": {
            "A_감가상각절벽": {"level": _group_level(a_levels), "metrics": a_metrics},
            "B_이익현금괴리": {"level": _group_level(b_levels), "metrics": b_metrics},
            "C_차입리스크": {
                "level": _group_level(c_levels),
                "metrics": c_metrics,
                "included_accounts": annual["debt"]["included_accounts"],
            },
            "D_희석리스크": {
                "level": _group_level(d_levels),
                "metrics": d_metrics,
                "disclosure_date": disclosure_date,
            },
        },
        "unavailable": unavailable,
        "unavailable_count": len(unavailable),
        "source_accounts": {
            key: entry["source"] for key, entry in annual["accounts"].items()
        },
        "data_source": f"DART fnlttSinglAcntAll + piicDecsn (조회일: {query_date})",
        "disclaimer": "공시 데이터 기반 정량 계산. 투자 판단·추천 아님.",
    }


def log_source_values(stock_code: str, annual: dict[str, Any]) -> None:
    """검증용 — 각 지표에 사용된 원천 계정과목명과 원본 값을 로그로 남긴다."""
    periods = annual.get("period_names", {})
    logger.info(
        "[risk_flags] %s 원천계정 (기간: %s / %s / %s)",
        stock_code, periods.get("prior2"), periods.get("prior"), periods.get("term"),
    )
    for key, entry in annual["accounts"].items():
        logger.info(
            "  %-18s %-60s 전전기=%s 전기=%s 당기=%s",
            key, entry["source"], entry["prior2"], entry["prior"], entry["term"],
        )
    debt = annual["debt"]
    logger.info(
        "  %-18s %s 전전기=%s 전기=%s 당기=%s",
        "이자발생부채합계", debt["included_accounts"],
        debt["prior2"], debt["prior"], debt["term"],
    )


async def get_risk_flags(
    session: Optional["AsyncSession"], stock_code: str
) -> dict[str, Any]:
    """종목 재무 리스크 플래그 조회 (수집 → 계산 → 판정)."""
    from app.collectors import dart_financial

    today = date.today()
    corp = await dart_financial.get_corp_code(stock_code)
    if not corp:
        return {
            "stock_code": stock_code,
            "error": "corp_code 매핑 실패 (비상장 또는 DART 미등록)",
            "disclaimer": "공시 데이터 기반 정량 계산. 투자 판단·추천 아님.",
        }

    corp_code = corp["corp_code"]
    year = dart_financial.latest_annual_year(today)
    statements = await dart_financial.fetch_financial_statements(
        corp_code, str(year), dart_financial.REPRT_ANNUAL, session
    )
    if not statements:
        return {
            "stock_code": stock_code,
            "corp_name": corp["corp_name"],
            "error": f"{year}년 사업보고서 재무제표 조회 실패",
            "disclaimer": "공시 데이터 기반 정량 계산. 투자 판단·추천 아님.",
        }

    annual = extract_accounts(statements["rows"])
    log_source_values(stock_code, annual)

    bgn = (today - timedelta(days=730)).strftime("%Y%m%d")
    decisions = await dart_financial.fetch_paid_in_capital_increase(
        corp_code, bgn, today.strftime("%Y%m%d"), session
    )

    quarter = await dart_financial.fetch_latest_quarter(corp_code, session, today)

    return build_report(
        stock_code=stock_code,
        corp_name=corp["corp_name"],
        fs_div=statements["fs_div"],
        annual=annual,
        decisions=decisions,
        latest_quarter=quarter["label"] if quarter else None,
        query_date=today.isoformat(),
        bsns_year=year,
    )


def has_flag(report: dict[str, Any], min_level: str = "주의") -> bool:
    """플래그 발동 여부 (브리프에 표시할지 판단)."""
    flags = report.get("flags") or {}
    threshold = _LEVEL_ORDER.get(min_level, 1)
    return any(
        _LEVEL_ORDER.get(g.get("level", ""), -1) >= threshold for g in flags.values()
    )
