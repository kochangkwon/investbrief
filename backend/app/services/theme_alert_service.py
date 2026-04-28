"""테마 알림 발송 + 측정 인프라 기록 (v3 Phase 1)

InvestBrief 적용 사항:
- 키움 의존성 제거 → FinanceDataReader(FDR)로 가격 스냅샷
- notification_service → telegram_service.send_text 사용
- skip_telegram=True 옵션: DB 저장만 수행 (theme_radar_service에서 이미 발송한 경우 이중 발송 방지)
"""
from __future__ import annotations

import asyncio
import html
import logging
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import FinanceDataReader as fdr
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.theme_alert import ThemeAlert, ThemeAlertCandidate
from app.services import telegram_service

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# 가격 스냅샷 헬퍼 (FDR 기반 — 전영업일 종가)
# ─────────────────────────────────────────────────────────
def _fetch_close_price_sync(stock_code: str) -> Optional[int]:
    """FDR로 종목 최근 종가 조회 (동기 — to_thread로 호출)."""
    try:
        end = date.today()
        start = end - timedelta(days=10)
        df = fdr.DataReader(stock_code, start, end)
        if df is None or df.empty:
            return None
        close = float(df["Close"].iloc[-1])
        return int(close) if close else None
    except Exception as e:
        logger.warning("FDR 가격 조회 실패 %s: %s", stock_code, e)
        return None


async def _fetch_close_price(stock_code: str) -> Optional[int]:
    return await asyncio.to_thread(_fetch_close_price_sync, stock_code)


def _fetch_kospi_close_sync() -> Optional[float]:
    """코스피 최근 종가 (alpha 비교용)."""
    try:
        end = date.today()
        start = end - timedelta(days=10)
        df = fdr.DataReader("KS11", start, end)
        if df is None or df.empty:
            return None
        return float(df["Close"].iloc[-1])
    except Exception as e:
        logger.warning("FDR KOSPI 조회 실패: %s", e)
        return None


async def _fetch_kospi_close() -> Optional[float]:
    return await asyncio.to_thread(_fetch_kospi_close_sync)


# ─────────────────────────────────────────────────────────
# 메시지 빌더
# ─────────────────────────────────────────────────────────
def _build_message(theme_name: str, candidates: List[Dict[str, Any]]) -> str:
    def esc(text: str) -> str:
        return html.escape(text or "")

    lines = [f"🎯 <b>테마 알림 — {esc(theme_name)}</b>", ""]
    lines.append(f"수혜주 후보 ({len(candidates)}종목):")
    lines.append("")
    for c in candidates[:10]:
        sub = c.get("sub_theme") or ""
        title = (c.get("matched_news_title") or "")[:60]
        line = f"• <b>{esc(c.get('stock_name', ''))}</b> ({c.get('stock_code', '')})"
        if sub:
            line += f"\n   └ {esc(sub)}"
        if title:
            line += f"  ·  {esc(title)}"
        lines.append(line)
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────
# 메인 발송 + 기록 함수
# ─────────────────────────────────────────────────────────
async def send_theme_alert(
    theme_id: str,
    theme_name: str,
    candidates: List[Dict[str, Any]],
    db: AsyncSession,
    *,
    use_inline_buttons: bool = False,
    skip_telegram: bool = False,
) -> Optional[str]:
    """알림 발송 + DB 기록.

    Parameters
    ----------
    theme_id, theme_name : 테마 식별자
    candidates : [{stock_code, stock_name, sub_theme?, matched_news_title?}, ...]
    db : AsyncSession
    use_inline_buttons : Phase 1에서는 미사용 (False 권장)
    skip_telegram : True면 DB 저장만 (theme_radar_service가 이미 발송한 경우)

    Returns
    -------
    alert_uid : str | None  (실패 시 None)
    """
    if not candidates:
        logger.info("send_theme_alert: candidates 비어있음, 스킵 (theme=%s)", theme_id)
        return None

    alert_uid = uuid.uuid4().hex[:16]

    # 1. 가격 스냅샷 (병렬)
    enriched: List[Dict[str, Any]] = []
    price_tasks = [_fetch_close_price(c["stock_code"]) for c in candidates]
    kospi_task = _fetch_kospi_close()
    prices = await asyncio.gather(*price_tasks, return_exceptions=True)
    kospi_close = await kospi_task

    for c, price in zip(candidates, prices):
        item = dict(c)
        if isinstance(price, Exception):
            logger.warning("가격 스냅샷 실패 %s: %s", c.get("stock_code"), price)
            item["price_at_alert"] = None
        else:
            item["price_at_alert"] = price
        enriched.append(item)

    # 2. DB 저장
    try:
        alert = ThemeAlert(
            alert_uid=alert_uid,
            theme_id=theme_id,
            theme_name=theme_name,
            candidate_count=len(enriched),
            sent_at=datetime.utcnow(),
        )
        db.add(alert)
        await db.flush()  # alert.id 확보

        for c in enriched:
            cand = ThemeAlertCandidate(
                alert_id=alert.id,
                stock_code=c["stock_code"],
                stock_name=c.get("stock_name", ""),
                sub_theme=c.get("sub_theme"),
                matched_news_title=c.get("matched_news_title"),
                price_at_alert=c.get("price_at_alert"),
                kospi_at_alert=kospi_close,
            )
            db.add(cand)

        await db.commit()
        logger.info(
            "ThemeAlert 기록 완료: uid=%s theme=%s candidates=%d",
            alert_uid, theme_name, len(enriched),
        )
    except Exception:
        await db.rollback()
        logger.exception("ThemeAlert DB 저장 실패")
        return None

    # 3. 텔레그램 발송 (skip_telegram=True면 생략)
    if not skip_telegram:
        try:
            message = _build_message(theme_name, enriched)
            ok = await telegram_service.send_text(message)
            if not ok:
                logger.error("테마 알림 발송 실패 (DB는 기록됨): %s", alert_uid)
        except Exception:
            logger.exception("테마 알림 발송 중 예외 (DB는 기록됨): %s", alert_uid)

    return alert_uid
