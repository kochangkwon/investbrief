"""일반명사 동철 종목명 후보 자동 산출 (2026-08-26 사고 재발 방지).

`theme_detection`의 verdict 통계에서 "일반명사로 매일 매칭되는 종목명"을
데이터로 찾아낸다. 추측으로 AMBIGUOUS_COMMON_NOUN_NAMES를 늘리지 말고
이 스크립트 결과를 근거로 추가할 것.

    cd backend && .venv/bin/python scripts/surface_ambiguous_names.py

판정 지표 (일반명사 오추출의 특징):
  ① NO 누적이 많다               — 검증이 계속 걷어내고 있다
  ② 여러 테마에 무차별 매칭된다   — 특정 산업 재료가 아니라 일상어다
  ③ 헤드라인이 아닌 본문에서 추출 — 회사 언급이 아니라 문장 속 단어다
  ④ YES 비율이 낮다              — 실제 수혜주로 인정된 적이 거의 없다

세 지표가 겹치면 후보다. 최종 판단은 사람이 문맥을 보고 한다.
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.stock_name_rules import AMBIGUOUS_COMMON_NOUN_NAMES  # noqa: E402

DB_PATH = Path(__file__).resolve().parents[1] / "investbrief.db"

MIN_NO = 3          # NO 누적 최소
MIN_THEMES = 3      # 걸친 테마 수 최소
MAX_YES_RATIO = 0.2  # YES 비율 상한


def main() -> None:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        """
        SELECT stock_name, stock_code,
               SUM(verdict = 'NO')  AS no_cnt,
               SUM(verdict = 'YES') AS yes_cnt,
               COUNT(DISTINCT theme_id) AS themes,
               SUM(instr(headline, stock_name) = 0) AS body_only
        FROM theme_detection
        WHERE verdict IS NOT NULL
        GROUP BY stock_name, stock_code
        HAVING no_cnt >= ?
        ORDER BY no_cnt DESC
        """,
        (MIN_NO,),
    ).fetchall()

    print("=" * 74)
    print("일반명사 동철 종목명 후보 (theme_detection 실측)")
    print(f"기준: NO>={MIN_NO}, 테마>={MIN_THEMES}, YES비율<={MAX_YES_RATIO:.0%}")
    print("=" * 74)

    flagged = []
    for r in rows:
        total = (r["no_cnt"] or 0) + (r["yes_cnt"] or 0)
        yes_ratio = (r["yes_cnt"] or 0) / total if total else 0.0
        body_ratio = (r["body_only"] or 0) / total if total else 0.0
        already = r["stock_name"] in AMBIGUOUS_COMMON_NOUN_NAMES

        is_candidate = (
            r["themes"] >= MIN_THEMES
            and yes_ratio <= MAX_YES_RATIO
            and not already
        )
        mark = "✅등록됨" if already else ("🔴후보" if is_candidate else "  ")
        print(
            f"  {mark} {r['stock_name']:10s}({r['stock_code']}) "
            f"NO={r['no_cnt']:2d} YES={r['yes_cnt']:2d} "
            f"테마={r['themes']:2d} 본문추출={body_ratio:.0%}"
        )
        if is_candidate:
            flagged.append(r)

    if not flagged:
        print("\n신규 후보 없음.")
        return

    print("\n" + "=" * 74)
    print("후보별 실제 오추출 문맥 (사람이 확인 후 등록 판단)")
    print("=" * 74)
    for r in flagged:
        print(f"\n[{r['stock_name']}]")
        for h in conn.execute(
            "SELECT headline, verdict FROM theme_detection "
            "WHERE stock_name = ? ORDER BY detected_at DESC LIMIT 4",
            (r["stock_name"],),
        ):
            where = "제목" if r["stock_name"] in h["headline"] else "본문"
            print(f"   [{h['verdict']}][{where}] {h['headline'][:72]}")

    print(
        "\n등록: app/services/stock_name_rules.py 의 "
        "AMBIGUOUS_COMMON_NOUN_NAMES 에 근거 주석과 함께 추가"
    )


if __name__ == "__main__":
    main()
