"""오탐 감지 결과를 Pull 목록에서 제외 (이력 보존형 비활성화).

StockAI Pull API는 `claude_validation_passed=True AND is_active=True`로 필터하므로,
오탐이 발견되면 이 스크립트로 `is_active=0`을 찍어 즉시 배제한다. 레코드는
삭제하지 않아 성과 측정·재발 분석 데이터가 남는다.

    # 확인 (dry-run)
    cd backend && .venv/bin/python scripts/deactivate_false_positive.py \\
        --date 2026-08-26 --code 001680
    # 실제 반영
    ... --date 2026-08-26 --code 001680 --apply \\
        --reason "일반명사 '대상' 오추출 (제목에 회사 없음)"

theme_detection 쪽도 함께 내려 중복검증 윈도우에서 빠지게 한다
(--keep-detection 으로 생략 가능).
"""
import argparse
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "investbrief.db"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="scan_date (YYYY-MM-DD)")
    ap.add_argument("--code", required=True, help="종목코드 6자리")
    ap.add_argument("--reason", default="", help="비활성화 사유 (로그용)")
    ap.add_argument("--apply", action="store_true", help="실제 반영 (없으면 dry-run)")
    ap.add_argument("--keep-detection", action="store_true",
                    help="theme_detection은 그대로 두기")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    targets = conn.execute(
        "SELECT id, scan_date, theme_name, stock_name, stock_code, is_active "
        "FROM theme_scan_results WHERE scan_date = ? AND stock_code = ?",
        (args.date, args.code),
    ).fetchall()

    if not targets:
        print(f"대상 없음: scan_date={args.date} stock_code={args.code}")
        return

    print(f"대상 {len(targets)}건 (사유: {args.reason or '미기재'})")
    for t in targets:
        state = "활성" if t["is_active"] else "이미 비활성"
        print(f"  [{state}] {t['stock_name']}({t['stock_code']}) | {t['theme_name']}")

    det = conn.execute(
        "SELECT COUNT(*) FROM theme_detection "
        "WHERE stock_code = ? AND date(detected_at) = ? AND is_active = 1",
        (args.code, args.date),
    ).fetchone()[0]
    if not args.keep_detection:
        print(f"  theme_detection 동반 비활성화 대상: {det}건")

    if not args.apply:
        print("\ndry-run — 반영하려면 --apply 추가")
        return

    conn.execute(
        "UPDATE theme_scan_results SET is_active = 0 "
        "WHERE scan_date = ? AND stock_code = ?",
        (args.date, args.code),
    )
    if not args.keep_detection:
        conn.execute(
            "UPDATE theme_detection SET is_active = 0 "
            "WHERE stock_code = ? AND date(detected_at) = ?",
            (args.code, args.date),
        )
    conn.commit()

    remaining = conn.execute(
        "SELECT COUNT(*) FROM theme_scan_results "
        "WHERE scan_date = ? AND is_active = 1 AND claude_validation_passed = 1",
        (args.date,),
    ).fetchone()[0]
    print(f"\n반영 완료. {args.date} Pull 대상 잔여: {remaining}건")


if __name__ == "__main__":
    main()
