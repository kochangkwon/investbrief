"""kospi_at_alert / kospi_return_Nd 백필 (지시서 P1-1).

`theme_alert_candidates.kospi_at_alert`가 751건 중 162건만 채워져 있어
알파(시장 대비 초과수익) 측정이 불가능한 상태를 보정한다.
`daily_briefs.domestic_market.kospi.close`(해당일 없으면 직전 브리프)로 채운다.

실행 (반드시 migrate_sent_at_kst.py **이후**):
    cd backend && python3 scripts/backfill_kospi_at_alert.py          # dry-run
    cd backend && python3 scripts/backfill_kospi_at_alert.py --apply  # 실제 반영

안전장치: sent_at 시(hour) 분포에 UTC 서명(21~23시대 다수)이 남아 있으면
sent_at 보정 미실행 상태로 판단하고 중단한다.
"""
import asyncio
import bisect
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.database import async_session  # noqa: E402
from app.models.brief import DailyBrief  # noqa: E402
from app.models.theme_alert import ThemeAlert, ThemeAlertCandidate  # noqa: E402
from app.services.theme_alert_service import _extract_kospi_close  # noqa: E402

TARGETS = (30, 60, 90)


def _close_on_or_before(dates: list[date], closes: dict[date, float], d: date) -> Optional[float]:
    i = bisect.bisect_right(dates, d) - 1
    return closes[dates[i]] if i >= 0 else None


async def main() -> None:
    apply = "--apply" in sys.argv

    async with async_session() as db:
        briefs = (await db.execute(
            select(DailyBrief.date, DailyBrief.domestic_market).order_by(DailyBrief.date)
        )).all()
        closes: dict[date, float] = {}
        for d, dm in briefs:
            c = _extract_kospi_close(dm)
            if c:
                closes[d] = c
        dates = sorted(closes)
        if not dates:
            print("daily_briefs에 KOSPI 종가 없음 — 중단.")
            return
        print(f"KOSPI 시계열: {len(dates)}일 ({dates[0]} ~ {dates[-1]})")

        rows = (await db.execute(
            select(ThemeAlertCandidate, ThemeAlert.sent_at)
            .join(ThemeAlert, ThemeAlertCandidate.alert_id == ThemeAlert.id)
        )).all()

        # UTC 서명 검사 — sent_at 보정 전이면 앵커가 하루 밀려 백필이 오염됨
        hours = Counter(str(sent_at)[11:13] for _, sent_at in rows if sent_at)
        utc_sig = sum(hours.get(h, 0) for h in ("21", "22", "23"))
        if utc_sig > len(rows) * 0.5:
            print("sent_at에 UTC 서명 잔존 — scripts/migrate_sent_at_kst.py 먼저 실행하세요. 중단.")
            return

        filled_anchor = 0
        filled_returns = 0
        today = date.today()
        for cand, sent_at in rows:
            if sent_at is None:
                continue
            d0 = sent_at.date()
            k0 = _close_on_or_before(dates, closes, d0)
            if k0 is None:
                continue
            if cand.kospi_at_alert is None:
                cand.kospi_at_alert = k0
                filled_anchor += 1
            base = cand.kospi_at_alert
            if not base:
                continue
            for n in TARGETS:
                ret_col = f"kospi_return_{n}d"
                stock_ret = getattr(cand, f"return_{n}d")
                if getattr(cand, ret_col) is not None or stock_ret is None:
                    continue  # 이미 있음 / 종목 수익률도 미성숙
                dn = d0 + timedelta(days=n)
                if dn > today or dn > dates[-1]:
                    continue
                kn = _close_on_or_before(dates, closes, dn)
                if kn is None:
                    continue
                setattr(cand, ret_col, round((kn - base) / base * 100, 2))
                filled_returns += 1

        print(f"채움 대상: kospi_at_alert {filled_anchor}건, kospi_return_Nd {filled_returns}건 "
              f"(전체 후보 {len(rows)}건)")

        if not apply:
            print("dry-run — 반영하려면 --apply 로 재실행.")
            return
        try:
            await db.commit()
            print("백필 반영 완료.")
        except Exception as e:
            await db.rollback()
            print(f"commit 실패: {e}")


asyncio.run(main())
