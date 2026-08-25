"""네이버 글로벌 지표 엔드포인트 실측 확인 (P2 심볼 확정용).

VIX·환율 폴백은 후보 URL을 순차 시도하도록 구현돼 있다. 이 스크립트로
어느 후보가 실제로 응답하는지 확인하고, 승자 URL만 남기면 호출이 빨라진다.

    cd backend && .venv/bin/python scripts/probe_naver_global.py

전 후보가 실패하면 브라우저에서 m.stock.naver.com 해외증시·시장지표 페이지의
네트워크 탭에서 실제 XHR 엔드포인트를 확인해
price_collector._NAVER_GLOBAL_CANDIDATES에 추가한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.collectors.price_collector import (  # noqa: E402
    _NAVER_GLOBAL_CANDIDATES,
    _NAVER_MCAP_HEADERS,
    _naver_rows,
    _naver_sorted_closes,
    fetch_naver_global_quote,
)


def main() -> None:
    print("=" * 68)
    print("네이버 글로벌 지표 후보 엔드포인트 점검")
    print("=" * 68)

    for kind, candidates in _NAVER_GLOBAL_CANDIDATES.items():
        print(f"\n[{kind}] 후보 {len(candidates)}개")
        for url in candidates:
            try:
                resp = httpx.get(url, headers=_NAVER_MCAP_HEADERS, timeout=8.0)
                status = resp.status_code
            except Exception as e:
                print(f"  ✗ {type(e).__name__}: {str(e)[:70]}")
                print(f"    {url}")
                continue

            if status != 200:
                print(f"  ✗ HTTP {status}")
                print(f"    {url}")
                continue

            try:
                payload = resp.json()
            except Exception:
                print(f"  ✗ HTTP 200이나 JSON 아님 — {resp.text[:60]}")
                print(f"    {url}")
                continue

            rows = _naver_rows(payload)
            closes = _naver_sorted_closes(rows)
            if closes:
                print(f"  ✅ 성공 — 종가 {closes[:3]} (행 {len(rows)}개)")
                print(f"    {url}")
                print(f"    첫 행 키: {sorted(rows[0].keys())[:10]}")
            else:
                print(f"  ⚠️ HTTP 200이나 파싱 실패 (행 {len(rows)}개)")
                print(f"    {url}")
                print(f"    응답 앞부분: {str(payload)[:200]}")

    print("\n" + "=" * 68)
    print("실제 폴백 함수 동작 (구현과 동일 경로)")
    print("=" * 68)
    for kind in _NAVER_GLOBAL_CANDIDATES:
        result = fetch_naver_global_quote(kind)
        if result:
            print(f"  {kind:8s} ✅ {result['close']:,.2f} ({result['change_pct']:+.2f}%)")
        else:
            print(f"  {kind:8s} ❌ 폴백 불가 — 후보 URL 갱신 필요")


if __name__ == "__main__":
    main()
