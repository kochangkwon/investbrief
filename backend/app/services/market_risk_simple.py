"""시장 위험 모드 단순 진단 — 3개 변수 종합.

⚠️ 임계값(VIX 25, 환율 +2%, 외인 5일 매도)은 운영 데이터로 보정 필요.
보수적으로 설정 (false positive 적게).
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ⚠️ 운영 후 보정 (현재는 보수적 임계값)
VIX_WARNING = 22
VIX_CRITICAL = 28
USDKRW_5D_PCT_WARNING = 1.5
USDKRW_5D_PCT_CRITICAL = 3.0
FOREIGN_SELL_DAYS_WARNING = 3
FOREIGN_SELL_DAYS_CRITICAL = 5


async def diagnose_simple(
    global_market: dict[str, Any],
    investor_flow_history: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """시장 위험 단순 진단.

    Args:
        global_market: P0-1 입력의 글로벌 시장 데이터
        investor_flow_history: 최근 5일 외인 net_billion (None이면 외인 시그널 스킵)

    Returns:
        {
            "level": "정상" | "주의" | "위험",
            "factors": [str, ...],
            "score": int,  # 0-100 (debug용)
        }
    """
    score = 0
    factors: list[str] = []

    # 1. VIX
    vix_data = global_market.get("vix") or global_market.get("VIX")
    if vix_data:
        vix = vix_data.get("close", 0)
        if vix >= VIX_CRITICAL:
            score += 50
            factors.append(f"VIX {vix:.1f} (위험 임계 {VIX_CRITICAL}+)")
        elif vix >= VIX_WARNING:
            score += 25
            factors.append(f"VIX {vix:.1f} (주의 임계 {VIX_WARNING}+)")

    # 2. 환율 5일 변동 (일변동 대용)
    usdkrw_data = global_market.get("usdkrw") or global_market.get("USDKRW")
    if usdkrw_data:
        chg = usdkrw_data.get("change_pct", 0)
        est_5d = abs(chg) * 2.5
        if est_5d >= USDKRW_5D_PCT_CRITICAL:
            score += 30
            factors.append(f"USD/KRW 급변 {chg:+.2f}% (위험)")
        elif est_5d >= USDKRW_5D_PCT_WARNING:
            score += 15
            factors.append(f"USD/KRW 변동 {chg:+.2f}% (주의)")

    # 3. 외인 5일 연속 매도
    if investor_flow_history:
        sells_in_row = 0
        for day in investor_flow_history[:5]:
            net = day.get("foreign_net_billion", 0)
            if net < 0:
                sells_in_row += 1
            else:
                break
        if sells_in_row >= FOREIGN_SELL_DAYS_CRITICAL:
            score += 30
            factors.append(f"외인 {sells_in_row}일 연속 순매도 (위험)")
        elif sells_in_row >= FOREIGN_SELL_DAYS_WARNING:
            score += 15
            factors.append(f"외인 {sells_in_row}일 연속 순매도 (주의)")

    # 분류
    if score >= 50:
        level = "위험"
    elif score >= 20:
        level = "주의"
    else:
        level = "정상"

    if not factors and level == "정상":
        factors = ["특이 위험 시그널 없음"]

    return {
        "level": level,
        "factors": factors,
        "score": score,
    }


async def get_investor_flow_history(days: int = 5) -> list[dict[str, Any]]:
    """최근 N일 외인 net 흐름 (P0-2 collector 활용).

    조회 부하 큼 — P0-5에서는 옵션. 없으면 외인 시그널 스킵.
    """
    try:
        from app.collectors import investor_flow_collector
        results = []
        end_date = investor_flow_collector.latest_trading_date()
        check_date = end_date
        for _ in range(days * 2):  # 휴장일 흡수
            if len(results) >= days:
                break
            flow = await investor_flow_collector.get_market_flow(check_date)
            if flow:
                results.append({
                    "date": check_date.isoformat(),
                    "foreign_net_billion": flow.get("foreign_net_billion", 0),
                })
            check_date -= timedelta(days=1)
            if check_date.weekday() >= 5:
                check_date -= timedelta(days=2)
        return results
    except Exception:
        logger.exception("외인 5일 흐름 조회 실패")
        return []
