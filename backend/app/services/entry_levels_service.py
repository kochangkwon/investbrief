"""ATR 기반 진입가/손절가/목표가 자동 산출.

⚠️ 절대 권고가 아닌 참고 가격대. 사용자 트레이딩 스타일에 따라 조정.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any, Optional

from app.collectors import price_collector

logger = logging.getLogger(__name__)


# 표준 ATR 기법 — 운영 후 보정 가능
ATR_PERIOD = 14
STOP_LOSS_ATR_MULTIPLIER = 1.5  # 손절: 1.5×ATR (Wilder 권장 범위)
TARGET_1_ATR_MULTIPLIER = 3.0   # 1차 목표: 3×ATR (R:R 1:2)
DIP_ENTRY_PCT = 0.99            # 조정 진입: 현재가 -1%
TARGET_2_LOOKBACK_DAYS = 60     # 2차 목표: 60일 고가


def _calculate_atr_sync(stock_code: str) -> Optional[dict[str, Any]]:
    """ATR 기반 진입/손절/목표 계산.

    Returns:
        {
            "current": float,
            "atr": float,
            "entry_market": float,
            "entry_dip": float,
            "stop_loss": float,
            "stop_loss_pct": float,
            "target_1": float,
            "target_1_pct": float,
            "target_2": float,
            "target_2_pct": float,
            "risk_reward": float,
        }
        실패 시 None.
    """
    try:
        start = date.today() - timedelta(days=TARGET_2_LOOKBACK_DAYS + 30)
        df = price_collector.fetch_close_history(stock_code, start=start)
        if df is None or len(df) < ATR_PERIOD + 1:
            return None

        # ATR 계산 (True Range = max(H-L, |H-prev_close|, |L-prev_close|))
        high = df["High"]
        low = df["Low"]
        close = df["Close"]
        prev_close = close.shift(1)

        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()

        import pandas as pd
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = float(tr.rolling(ATR_PERIOD).mean().iloc[-1])

        if atr <= 0 or atr != atr:  # NaN 체크
            return None

        current = float(close.iloc[-1])

        # 진입가
        entry_market = current
        entry_dip = round(current * DIP_ENTRY_PCT, 0)

        # 손절가
        stop_loss = round(current - atr * STOP_LOSS_ATR_MULTIPLIER, 0)
        stop_loss_pct = round((stop_loss - current) / current * 100, 2)

        # 1차 목표가 (R:R 1:2)
        target_1 = round(current + atr * TARGET_1_ATR_MULTIPLIER, 0)
        target_1_pct = round((target_1 - current) / current * 100, 2)

        # 2차 목표가 (60일 고가)
        target_2 = round(float(close.iloc[-min(TARGET_2_LOOKBACK_DAYS, len(close)):].max()), 0)
        # 60일 고가가 현재가보다 낮으면 (계단형 하락 중) → 1차 목표×1.2 사용
        if target_2 <= current:
            target_2 = round(target_1 * 1.2, 0)
        target_2_pct = round((target_2 - current) / current * 100, 2)

        # R:R 비율
        risk = current - stop_loss
        reward_1 = target_1 - current
        risk_reward = round(reward_1 / risk, 2) if risk > 0 else 0.0

        return {
            "current": round(current, 0),
            "atr": round(atr, 2),
            "entry_market": round(entry_market, 0),
            "entry_dip": entry_dip,
            "stop_loss": stop_loss,
            "stop_loss_pct": stop_loss_pct,
            "target_1": target_1,
            "target_1_pct": target_1_pct,
            "target_2": target_2,
            "target_2_pct": target_2_pct,
            "risk_reward": risk_reward,
        }
    except Exception:
        logger.exception("진입/손절/목표 계산 실패: %s", stock_code)
        return None


async def get_entry_levels(stock_code: str) -> Optional[dict[str, Any]]:
    """비동기 래퍼."""
    return await asyncio.to_thread(_calculate_atr_sync, stock_code)


def format_levels_oneline(levels: Optional[dict[str, Any]]) -> str:
    """1줄 포맷 (텔레그램용).

    예: "📍 진입 95,200 / 손절 92,000 (-3.4%) / 목표 101,700 (R:R 1:2)"
    """
    if not levels:
        return ""

    return (
        f"📍 진입 {levels['entry_market']:,.0f} "
        f"/ 손절 {levels['stop_loss']:,.0f} ({levels['stop_loss_pct']:+.1f}%) "
        f"/ 목표 {levels['target_1']:,.0f} (R:R 1:{levels['risk_reward']:.1f})"
    )


def format_levels_detail(levels: Optional[dict[str, Any]]) -> list[str]:
    """상세 포맷 (브리프 등 여러 줄).

    Returns: 줄 단위 리스트 (있을 때만)
    """
    if not levels:
        return []

    lines = [
        f"📍 진입가: 시장가 {levels['entry_market']:,.0f} / "
        f"조정 매수 {levels['entry_dip']:,.0f}",
        f"⛔ 손절가: {levels['stop_loss']:,.0f} ({levels['stop_loss_pct']:+.1f}%, "
        f"ATR×{STOP_LOSS_ATR_MULTIPLIER})",
        f"🎯 1차 목표: {levels['target_1']:,.0f} ({levels['target_1_pct']:+.1f}%, "
        f"R:R 1:{levels['risk_reward']:.1f})",
        f"🎯 2차 목표: {levels['target_2']:,.0f} ({levels['target_2_pct']:+.1f}%, "
        f"60일 고가)",
    ]
    return lines
