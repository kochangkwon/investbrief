"""기존 theme_detection 레코드를 Claude로 재검증하고 오탐을 제거한다.

사용법:
    # Dry-run (기본): 검증만, 삭제 없음
    python3 -m scripts.verify_theme_detections

    # 삭제 포함
    python3 -m scripts.verify_theme_detections --apply

    # 특정 테마만
    python3 -m scripts.verify_theme_detections --theme "방산 수출 확대"

리포트: docs/03-analysis/theme-cleanup-report.md
백업: backend/investbrief.db.bak-YYYYMMDD-HHMMSS
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.theme import Theme, ThemeDetection
from app.services.theme_radar_service import _verify_theme_match

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("verify_theme_detections")

BACKEND_DIR = Path(__file__).resolve().parent.parent  # backend/
PROJECT_ROOT = BACKEND_DIR.parent                     # project root
DB_PATH = BACKEND_DIR / "investbrief.db"
REPORT_PATH = PROJECT_ROOT / "docs" / "03-analysis" / "theme-cleanup-report.md"


@dataclass
class VerificationRecord:
    detection_id: int
    theme_name: str
    matched_keyword: str
    stock_name: str
    stock_code: str
    headline: str
    verdict: bool
    reason: str
    error: Optional[str]


def _backup_database() -> Path:
    """investbrief.db를 타임스탬프 붙여 복사. 실패 시 sys.exit(1)."""
    if not DB_PATH.exists():
        logger.error("DB 파일 없음: %s", DB_PATH)
        sys.exit(1)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = DB_PATH.parent / f"investbrief.db.bak-{ts}"
    try:
        shutil.copy2(DB_PATH, backup_path)
    except Exception:
        logger.exception("DB 백업 실패")
        sys.exit(1)

    logger.info("DB 백업 완료: %s (%.1f KB)", backup_path, backup_path.stat().st_size / 1024)
    return backup_path


async def _load_all_detections(
    session: AsyncSession,
    theme_filter: Optional[str],
) -> list[tuple[ThemeDetection, Theme]]:
    """전체 theme_detection + theme 조인 로드."""
    stmt = select(ThemeDetection, Theme).join(
        Theme, Theme.id == ThemeDetection.theme_id
    )
    if theme_filter:
        stmt = stmt.where(Theme.name == theme_filter)
    stmt = stmt.order_by(Theme.id, ThemeDetection.detected_at)

    result = await session.execute(stmt)
    return [(row[0], row[1]) for row in result.all()]


async def _verify_record(
    detection: ThemeDetection,
    theme: Theme,
) -> VerificationRecord:
    """단일 레코드 검증 — _verify_theme_match 재사용."""
    try:
        verdict, reason = await _verify_theme_match(
            theme_name=theme.name,
            matched_keyword=detection.matched_keyword,
            stock_name=detection.stock_name,
            title=detection.headline,
            description="",  # 기존 레코드는 description 미보존, 제목만 사용
        )
        error = None
    except Exception as e:
        logger.exception("검증 중 예외: id=%d", detection.id)
        verdict = False
        reason = f"exception: {type(e).__name__}"
        error = str(e)

    return VerificationRecord(
        detection_id=detection.id,
        theme_name=theme.name,
        matched_keyword=detection.matched_keyword,
        stock_name=detection.stock_name,
        stock_code=detection.stock_code,
        headline=detection.headline,
        verdict=verdict,
        reason=reason,
        error=error,
    )


def _write_report(records: list[VerificationRecord], apply_mode: bool) -> Path:
    """재검증 결과를 markdown으로 저장."""
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

    total = len(records)
    yes_count = sum(1 for r in records if r.verdict)
    no_count = sum(1 for r in records if not r.verdict and r.error is None)
    error_count = sum(1 for r in records if r.error is not None)

    lines: list[str] = []
    lines.append("# 테마 감지 재검증 리포트")
    lines.append("")
    lines.append(f"- 실행 일시: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- 모드: {'APPLY (삭제 수행)' if apply_mode else 'DRY-RUN (삭제 없음)'}")
    lines.append(f"- 총 레코드: {total}건")
    lines.append(f"- YES 판정: {yes_count}건 (유지)")
    lines.append(f"- NO 판정: {no_count}건 (삭제 대상)")
    lines.append(f"- ERROR: {error_count}건 (보존 — API 장애 가능성)")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 테마별 그룹화
    by_theme: dict[str, list[VerificationRecord]] = {}
    for r in records:
        by_theme.setdefault(r.theme_name, []).append(r)

    for theme_name, theme_records in by_theme.items():
        lines.append(f"## {theme_name}")
        lines.append("")
        lines.append(f"총 {len(theme_records)}건 — "
                     f"YES {sum(1 for r in theme_records if r.verdict)} / "
                     f"NO {sum(1 for r in theme_records if not r.verdict and r.error is None)} / "
                     f"ERROR {sum(1 for r in theme_records if r.error is not None)}")
        lines.append("")
        lines.append("| ID | 종목 | 코드 | 키워드 | 판정 | 근거 | 헤드라인 |")
        lines.append("|----|------|------|--------|------|------|----------|")
        for r in theme_records:
            if r.error:
                verdict_str = "🟡 ERROR"
            elif r.verdict:
                verdict_str = "✅ YES"
            else:
                verdict_str = "❌ NO"
            # 파이프 이스케이프
            reason = r.reason.replace("|", "\\|")[:80]
            headline = r.headline.replace("|", "\\|")[:60]
            lines.append(
                f"| {r.detection_id} | {r.stock_name} | {r.stock_code} | "
                f"{r.matched_keyword} | {verdict_str} | {reason} | {headline} |"
            )
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 삭제 대상 ID 목록 (NO, ERROR 제외)")
    lines.append("")
    delete_ids = [r.detection_id for r in records if not r.verdict and r.error is None]
    if delete_ids:
        lines.append(f"총 {len(delete_ids)}건")
        lines.append("")
        lines.append("```")
        lines.append(", ".join(str(i) for i in delete_ids))
        lines.append("```")
    else:
        lines.append("없음")
    lines.append("")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    return REPORT_PATH


async def _delete_false_positives(
    session: AsyncSession,
    records: list[VerificationRecord],
) -> int:
    """NO 판정 레코드 삭제. ERROR는 보존."""
    delete_ids = [r.detection_id for r in records if not r.verdict and r.error is None]
    if not delete_ids:
        return 0

    result = await session.execute(
        delete(ThemeDetection).where(ThemeDetection.id.in_(delete_ids))
    )
    await session.commit()
    return result.rowcount or 0


async def main(apply_mode: bool, theme_filter: Optional[str]) -> int:
    logger.info(
        "재검증 시작 — 모드=%s theme_filter=%s",
        "APPLY" if apply_mode else "DRY-RUN", theme_filter or "(전체)",
    )

    # 1. 백업
    backup_path = _backup_database()

    # 2. 로드
    async with async_session() as session:
        pairs = await _load_all_detections(session, theme_filter)

    if not pairs:
        logger.warning("대상 레코드 없음")
        return 0

    logger.info("검증 대상: %d건", len(pairs))

    # 3. 검증 (순차)
    records: list[VerificationRecord] = []
    for i, (detection, theme) in enumerate(pairs, 1):
        logger.info(
            "(%d/%d) theme=%s stock=%s(%s) keyword=%s",
            i, len(pairs), theme.name, detection.stock_name,
            detection.stock_code, detection.matched_keyword,
        )
        record = await _verify_record(detection, theme)
        verdict_str = "ERROR" if record.error else ("YES" if record.verdict else "NO")
        logger.info("  → %s | %s", verdict_str, record.reason)
        records.append(record)

    # 4. 리포트
    report_path = _write_report(records, apply_mode)
    logger.info("리포트 생성: %s", report_path)

    # 5. 요약
    yes_count = sum(1 for r in records if r.verdict)
    no_count = sum(1 for r in records if not r.verdict and r.error is None)
    error_count = sum(1 for r in records if r.error is not None)
    logger.info(
        "요약: 총 %d건 | YES %d (유지) | NO %d (삭제대상) | ERROR %d (보존)",
        len(records), yes_count, no_count, error_count,
    )

    # 6. 삭제 (apply 모드만)
    if apply_mode:
        async with async_session() as session:
            deleted = await _delete_false_positives(session, records)
        logger.info("삭제 완료: %d건", deleted)
    else:
        logger.info("DRY-RUN — 삭제 미실행. 리포트 확인 후 --apply 로 재실행하세요.")
        logger.info("백업 파일: %s", backup_path)

    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="theme_detection 레코드 재검증 및 오탐 제거"
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="NO 판정 레코드를 실제로 삭제 (기본: dry-run)",
    )
    parser.add_argument(
        "--theme", type=str, default=None,
        help="특정 테마만 검증 (정확한 테마명)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    exit_code = asyncio.run(main(apply_mode=args.apply, theme_filter=args.theme))
    sys.exit(exit_code)
