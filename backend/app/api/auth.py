"""공개 API 인증 — 프론트엔드 프록시와 공유하는 Admin Key 검증"""
from __future__ import annotations

import secrets
from typing import Optional

from fastapi import Header, HTTPException, status

from app.config import settings


async def verify_admin_api_key(
    x_admin_api_key: Optional[str] = Header(default=None, alias="X-Admin-API-Key"),
) -> None:
    """`X-Admin-API-Key` 헤더 검증 (타이밍 공격 방지)."""
    expected = settings.admin_api_key

    if not expected:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ADMIN_API_KEY not configured on server",
        )
    if not x_admin_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Admin-API-Key header",
        )
    if not secrets.compare_digest(x_admin_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
