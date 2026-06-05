"""Scheduler control + status endpoints.

Lifecycle: the scheduler instance is stashed on `app.state.scheduler` by the
sidecar startup (see `ghostbrain.api.__main__`). When the user has the
`schedulerEnabled` setting off, the API runs without an instance and every
endpoint here returns `enabled: false` instead of failing.
"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request

from ghostbrain.scheduler import Scheduler, diagnostics

router = APIRouter(prefix="/v1/scheduler", tags=["scheduler"])

# Mirror the runner registry so /v1/connectors/:id/sync knows what's valid
# without reaching into the scheduler instance.
KNOWN_CONNECTORS = (
    "github", "gmail", "slack", "calendar", "jira", "confluence",
    "outlook_mail", "teams_chat", "teams_meetings",
)


def _scheduler(request: Request) -> Scheduler | None:
    return getattr(request.app.state, "scheduler", None)


@router.get("/status")
def scheduler_status(request: Request) -> dict:
    sched = _scheduler(request)
    if sched is None:
        return {"enabled": False, "jobs": {}}
    snap = sched.status_snapshot()
    return {"enabled": True, **snap}


@router.get("/diagnostics")
def scheduler_diagnostics(request: Request) -> dict:
    sched = _scheduler(request)
    return {
        "enabled": sched is not None,
        **diagnostics(),
    }
