"""GET /v1/connectors, GET /v1/connectors/{id}, POST sync endpoints."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request

from ghostbrain.api.models.connector import Connector, ConnectorDetail
from ghostbrain.api.repo.connectors import get_connector, list_connectors

router = APIRouter(prefix="/v1/connectors", tags=["connectors"])


# Mirror of the scheduler's job registry. Kept here so the sync endpoints can
# 404 unknown connector ids without touching the (maybe-not-running) scheduler.
SYNCABLE = {
    "github", "gmail", "slack", "calendar", "jira", "confluence",
    "outlook_mail", "teams_chat", "teams_meetings",
}


@router.get("", response_model=list[Connector])
def connectors() -> list[dict]:
    return list_connectors()


@router.get("/{connector_id}", response_model=ConnectorDetail)
def connector_detail(connector_id: str) -> dict:
    record = get_connector(connector_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Connector not found: {connector_id}")
    return record


@router.post("/{connector_id}/sync")
async def sync_one(connector_id: str, request: Request) -> dict:
    if connector_id not in SYNCABLE:
        raise HTTPException(status_code=404, detail=f"Connector not syncable: {connector_id}")
    sched = getattr(request.app.state, "scheduler", None)
    if sched is None:
        raise HTTPException(
            status_code=409,
            detail="Scheduler not running. Enable 'Run scheduler in-app' in Settings.",
        )
    result = await sched.run_now(connector_id)
    return asdict(result)


@router.post("/sync-all")
async def sync_all(request: Request) -> dict:
    sched = getattr(request.app.state, "scheduler", None)
    if sched is None:
        raise HTTPException(
            status_code=409,
            detail="Scheduler not running. Enable 'Run scheduler in-app' in Settings.",
        )
    results = await sched.run_all()
    return {name: asdict(r) for name, r in results.items()}
