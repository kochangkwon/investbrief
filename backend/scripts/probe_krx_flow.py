"""KRX 수급 조회 원인 진단 프로브 (서버 로그가 없을 때 실행).

사용 (Mac, backend 디렉터리):
    cd ~/dev/investbrief/backend && .venv/bin/python -m scripts.probe_krx_flow [YYYYMMDD]

출력: pykrx 버전, 자격증명 설정 여부(값 미출력), 각 단계 소요 시간, pykrx가 stdout에
찍는 로그인 메시지, 예외 traceback. 결과를 그대로 붙여넣으면 원인을 특정할 수 있다.
"""
from __future__ import annotations

import contextlib
import io
import json
import logging
import os
import sys
import time
import traceback
from datetime import date

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from app.config import settings  # noqa: E402
from app.collectors import investor_flow_collector as ifc  # noqa: E402


def main() -> int:
    for k, v in (("KRX_ID", settings.krx_id), ("KRX_PW", settings.krx_pw)):
        if v and not os.environ.get(k):
            os.environ[k] = v
    cred = bool(os.environ.get("KRX_ID")) and bool(os.environ.get("KRX_PW"))

    if len(sys.argv) > 1:
        a = sys.argv[1]
        target = date(int(a[0:4]), int(a[4:6]), int(a[6:8]))
    else:
        target = ifc.latest_trading_date()

    try:
        import pykrx
        ver = getattr(pykrx, "__version__", "?")
    except Exception as e:
        ver = f"import 실패: {e}"
    print(f"== pykrx {ver} | python {sys.version.split()[0]} | 자격증명 {'설정됨' if cred else '누락'} | 기준일 {target}")

    print("== 마지막 워커 실패 기록 (runtime/krx_last_error.json)")
    print(json.dumps(ifc.load_last_krx_error(), ensure_ascii=False, indent=1))

    for label, fn in (("시장 수급", ifc._fetch_market_flow_sync), ("외인 TOP", ifc._fetch_top_foreign_traders_sync)):
        print(f"\n== {label} ({target})")
        buf = io.StringIO()
        t0 = time.monotonic()
        try:
            with contextlib.redirect_stdout(buf):
                result = fn(target)
            print(f"   소요 {time.monotonic() - t0:.1f}s")
            if buf.getvalue().strip():
                print("   pykrx stdout:", buf.getvalue().strip()[:800])
            if isinstance(result, list):
                print(f"   결과: {len(result)}건", result[:3])
            else:
                print("   결과:", result)
        except Exception:
            print(f"   예외 ({time.monotonic() - t0:.1f}s):")
            traceback.print_exc()
            if buf.getvalue().strip():
                print("   pykrx stdout:", buf.getvalue().strip()[:800])

    print("\n== 원시 요청 1회 (로그인·세션 확인)")
    try:
        from pykrx.website.krx.market.core import 투자자별_거래실적_개별추이_일반  # type: ignore
        t0 = time.monotonic()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            df = 투자자별_거래실적_개별추이_일반().fetch(
                target.strftime("%Y%m%d"), target.strftime("%Y%m%d"), "STK", "3", "1"
            )
        print(f"   소요 {time.monotonic() - t0:.1f}s rows={len(df)} cols={list(df.columns)[:6]}")
        if buf.getvalue().strip():
            print("   stdout:", buf.getvalue().strip()[:800])
    except Exception:
        traceback.print_exc()
    return 0


if __name__ == "__main__":
    sys.exit(main())
