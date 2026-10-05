"""KRX 수급 조회 단명 워커 (지시서 G-2).

매 조회를 신선한 서브프로세스로 실행해 pykrx 로그인 토큰(1시간 만료)·세션 오염을
원천 차단한다. 부모(백엔드)의 os.environ(KRX_ID/KRX_PW)을 상속받아 import 시 새로 로그인.

사용: python -m app.collectors._krx_flow_worker YYYYMMDD

출력 규약:
- stdout: JSON {"market_flow": {...}|null, "top_traders": [...]} (성공 시 이것만 출력)
- stderr: pykrx 진단 메시지·에러
- exit 0: 정상(market_flow 유무는 호출 측 판단)
- exit 3: KRX 로그인 실패(자격증명 문제 의심)
- exit 4: KRX 비밀번호 변경 필요(CD010 — data.krx.co.kr 는 90일마다 비밀번호 변경을 강제한다)
- exit 2: 인자/실행 오류

pykrx는 로그인 실패를 stdout에 print하므로, 조회 구간의 stdout을 버퍼로 가로채
JSON stdout 오염을 막고 로그인 실패를 탐지한다.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
from datetime import date

from app.collectors.investor_flow_collector import (
    _fetch_market_flow_sync,
    _fetch_top_foreign_traders_sync,
)

_LOGIN_FAIL_MARKERS = ("KRX 로그인 실패", "자격 증명")
# pykrx auth.login_krx: CD010 → "⚠️ KRX 비밀번호 변경이 필요합니다." 출력 후 실패.
# 2026-10-01 실사고: .env 설정(07-03) 90일째에 만료 → 10-02~06 네이버 폴백 연속.
_PW_EXPIRED_MARKERS = ("비밀번호 변경이 필요", "CD010")


def classify_login_output(captured: str) -> int:
    """pykrx stdout → 종료코드 (0 정상, 3 로그인 실패, 4 비밀번호 만료). 순수 함수."""
    if any(m in captured for m in _PW_EXPIRED_MARKERS):
        return 4
    if any(m in captured for m in _LOGIN_FAIL_MARKERS):
        return 3
    return 0


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python -m app.collectors._krx_flow_worker YYYYMMDD", file=sys.stderr)
        return 2
    try:
        target = date(
            int(sys.argv[1][0:4]), int(sys.argv[1][4:6]), int(sys.argv[1][6:8])
        )
    except (ValueError, IndexError):
        print(f"invalid date: {sys.argv[1]!r}", file=sys.stderr)
        return 2

    # pykrx가 stdout에 찍는 로그인/진단 메시지를 가로채 JSON stdout 오염 방지
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        market_flow = _fetch_market_flow_sync(target)
        top_traders = _fetch_top_foreign_traders_sync(target)
    captured = buf.getvalue()

    if captured.strip():
        print(captured, file=sys.stderr)

    rc = classify_login_output(captured)
    if rc == 4:
        print("KRX_PASSWORD_EXPIRED", file=sys.stderr)
        return 4
    if rc == 3:
        print("KRX_LOGIN_FAILED", file=sys.stderr)
        return 3

    json.dump(
        {"market_flow": market_flow, "top_traders": top_traders},
        sys.stdout,
        ensure_ascii=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
