"""theme_alerts.sent_at UTC → KST 보정 (+9시간, 1회 실행).

theme_alert_service가 sent_at을 utcnow()로 저장해 08:10 KST 스캔 알림이
전날 23:10으로 기록되던 문제의 과거 데이터 보정. 코드 수정(now_kst_naive)
이후의 신규 행은 이미 KST이므로, 이 스크립트는 코드 수정 직후 1회만 실행.

    cd backend && python3 scripts/migrate_sent_at_kst.py

안전장치: 시(hour) 분포를 검사해 UTC 서명(23시대 다수)이 없으면 중단
— 이미 보정된 DB에서 재실행해도 이중 시프트되지 않는다.
"""
import asyncio
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.database import engine  # noqa: E402


async def main() -> None:
    async with engine.begin() as conn:
        rows = (await conn.execute(text("SELECT id, sent_at FROM theme_alerts"))).all()
        if not rows:
            print("theme_alerts 비어 있음 — 보정 불필요.")
            return

        hours = Counter(str(sent_at)[11:13] for _, sent_at in rows if sent_at)
        utc_signature = sum(hours.get(h, 0) for h in ("21", "22", "23"))
        print(f"전체 {len(rows)}건, 시(hour) 분포: {dict(hours)}")

        # 스캔은 08:10 KST 실행 → UTC 저장이면 23시대가 다수여야 한다
        if utc_signature < len(rows) * 0.5:
            print("UTC 서명(21~23시대 다수) 미검출 — 이미 보정됐거나 KST 저장. 중단.")
            return

        await conn.execute(
            text("UPDATE theme_alerts SET sent_at = datetime(sent_at, '+9 hours')")
        )
        print(f"보정 완료: {len(rows)}건 sent_at +9h (UTC → KST)")


asyncio.run(main())
