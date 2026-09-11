"""GET /health — liveness probe used by ghostbrain.doctor.checks_app.

Sits behind the auth middleware like every other route (the doctor check
sends the bearer token), so it doubles as an auth sanity check too.
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def get_health() -> dict:
    from ghostbrain.api.main import API_VERSION

    return {"ok": True, "version": API_VERSION}
