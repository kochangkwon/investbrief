from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()

# 기동 시 1회 커밋 해시 확정 (restart 별칭이 배포 커밋 대조에 사용 — StockAI /health 사양)
_REPO_DIR = Path(__file__).resolve().parents[3]


def _resolve_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=_REPO_DIR,
            capture_output=True,
            text=True,
            timeout=3,
        )
        return out.stdout.strip() if out.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


_COMMIT = _resolve_commit()


@router.get("/api/health")
async def health_check():
    return {"status": "ok", "service": "investbrief", "commit": _COMMIT}
