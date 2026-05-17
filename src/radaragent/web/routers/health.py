from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness probe for the reverse proxy / container orchestrator."""
    return {"status": "ok"}
