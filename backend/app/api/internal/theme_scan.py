"""StockAI 전용 내부 API — 일별 테마 스캔 결과 Pull 조회."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from app.api.internal.auth import verify_internal_api_key
from app.database import async_session
from app.models.theme import ThemeScanResult, ThemeScanRun

KST = ZoneInfo("Asia/Seoul")

router = APIRouter(
    prefix="/api/internal/theme-scan",
    tags=["internal"],
    dependencies=[Depends(verify_internal_api_key)],
)


@router.get("/runs/{target_date}")
async def get_scan_run_status(target_date: date) -> dict:
    """특정 날짜 스캔 실행 상태 조회 (StockAI 완료 여부 확인용)."""
    async with async_session() as session:
        run = (
            await session.execute(
                select(ThemeScanRun).where(ThemeScanRun.scan_date == target_date)
            )
        ).scalar_one_or_none()

    if not run:
        raise HTTPException(404, "Scan run not found")

    return {
        "scan_date": run.scan_date.isoformat(),
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "total_themes": run.total_themes,
        "total_stocks": run.total_stocks,
        "error_message": run.error_message,
    }


@router.get("/results")
async def get_theme_scan_results(
    target_date: Optional[date] = Query(None, alias="date"),
    require_completed: bool = Query(True),
) -> dict:
    """특정 날짜의 테마 스캔 결과 조회 (StockAI 전용).

    - `date` 미지정 시 KST 기준 오늘
    - `require_completed=True` (기본): 미완료 시 409 → StockAI 재시도/skip
    - `claude_validation_passed=True` 종목만 반환
    """
    if target_date is None:
        target_date = datetime.now(KST).date()

    async with async_session() as session:
        run = (
            await session.execute(
                select(ThemeScanRun).where(ThemeScanRun.scan_date == target_date)
            )
        ).scalar_one_or_none()

        if require_completed:
            if not run:
                raise HTTPException(
                    status_code=409,
                    detail=f"No scan run for {target_date}",
                )
            if run.status != "completed":
                raise HTTPException(
                    status_code=409,
                    detail=f"Scan status is '{run.status}', not 'completed'",
                )

        results = (
            (
                await session.execute(
                    select(ThemeScanResult)
                    .where(ThemeScanResult.scan_date == target_date)
                    .where(ThemeScanResult.claude_validation_passed.is_(True))
                    .order_by(ThemeScanResult.theme_name, ThemeScanResult.stock_code)
                )
            )
            .scalars()
            .all()
        )

    themes_dict: dict[str, list[dict]] = {}
    for r in results:
        themes_dict.setdefault(r.theme_name, []).append({
            "code": r.stock_code,
            "name": r.stock_name,
            "keywords": r.detected_keywords or [],
            "source_url": r.source_url,
            "detected_at": r.created_at.isoformat() if r.created_at else None,
        })

    return {
        "scan_date": target_date.isoformat(),
        "scan_status": run.status if run else "missing",
        "scan_completed_at": (
            run.completed_at.isoformat() if run and run.completed_at else None
        ),
        "themes": [
            {"theme": name, "stocks": stocks}
            for name, stocks in themes_dict.items()
        ],
        "total_stocks": sum(len(s) for s in themes_dict.values()),
    }
