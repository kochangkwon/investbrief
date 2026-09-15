"""효성(004800) 오태깅 detection 비활성화 (2026-09-16, 드라이런 기본 / --apply)

헤드라인 축약("효성, 美빅테크 수주" = 효성중공업)을 검증이 YES로 오판한
detection 2건(9/1, 9/16)을 비활성화한다 — StockAI 배치 재소환 차단.
"""
import sqlite3, sys
APPLY = "--apply" in sys.argv
c = sqlite3.connect("investbrief.db")
rows = list(c.execute(
    "SELECT id, headline, verdict, is_active FROM theme_detection "
    "WHERE stock_code='004800' AND theme_id=11 AND verdict='YES' AND is_active=1"))
for r in rows:
    print("비활성화 대상:", r)
if not rows:
    print("대상 없음")
elif APPLY:
    c.execute("UPDATE theme_detection SET is_active=0 "
              "WHERE stock_code='004800' AND theme_id=11 AND verdict='YES' AND is_active=1")
    c.execute("UPDATE theme_scan_results SET is_active=0 "
              "WHERE stock_code='004800' AND theme_name LIKE '전력%' AND is_active=1")
    c.commit(); print("APPLY 완료 —", c.total_changes, "행 변경")
else:
    print("(드라이런 — 적용은 --apply)")
