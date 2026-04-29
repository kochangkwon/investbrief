"""내부 API 인증 — StockAI ↔ InvestBrief 공유 키 검증"""
from __future__ import annotations

import secrets
from typing import Optional

from fastapi import Header, HTTPException, status

from app.config import settings


async def verify_internal_api_key(
    x_internal_api_key: Optional[str] = Header(default=None, alias="X-Internal-API-Key"),
) -> None:
    """`X-Internal-API-Key` 헤더 검증 (타이밍 공격 방지)."""
    expected_key = settings.stockai_internal_api_key

    if not expected_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="STOCKAI_INTERNAL_API_KEY not configured on server",
        )

    if not x_internal_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Internal-API-Key header",
        )

    if not secrets.compare_digest(x_internal_api_key, expected_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
