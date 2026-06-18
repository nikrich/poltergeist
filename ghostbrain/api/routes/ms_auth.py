# ghostbrain/api/routes/ms_auth.py
"""POST /start, GET /status, POST /disconnect for Microsoft interactive sign-in.

The MSAL flow runs in the sidecar; the renderer triggers + polls these. A single
InteractiveAuth instance is held on app.state so /start and /status share it."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ghostbrain.connectors._runner import load_routing
from ghostbrain.connectors.microsoft.graph.interactive_auth import (
    AlreadyRunning,
    InteractiveAuth,
)

router = APIRouter(prefix="/v1/connectors/microsoft/auth", tags=["microsoft-auth"])


def _holder(request: Request) -> InteractiveAuth:
    holder = getattr(request.app.state, "ms_auth", None)
    if holder is None:
        holder = InteractiveAuth()
        request.app.state.ms_auth = holder
    return holder


def _config() -> dict:
    return load_routing().get("microsoft") or {}


@router.post("/start")
def start(request: Request) -> dict:
    try:
        _holder(request).start(_config())
    except AlreadyRunning as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"state": "pending"}


@router.get("/status")
def status(request: Request) -> dict:
    st = _holder(request).status(_config())
    return {"state": st.state, "account": st.account, "error": st.error}


@router.post("/disconnect")
def disconnect(request: Request) -> dict:
    _holder(request).disconnect(_config())
    return {"state": "idle"}
