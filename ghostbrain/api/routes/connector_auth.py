"""Auth-session endpoints: start / status / submit / cancel / disconnect."""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from ghostbrain.api.auth import registry
from ghostbrain.api.auth.session import AuthSessionManager, Session

router = APIRouter(prefix="/v1/connectors", tags=["connector-auth"])


class StartBody(BaseModel):
    params: dict = {}


class SubmitBody(BaseModel):
    session_id: str
    data: dict = {}


class CancelBody(BaseModel):
    session_id: str


def _manager(request: Request) -> AuthSessionManager:
    mgr = getattr(request.app.state, "auth_sessions", None)
    if mgr is None:
        mgr = AuthSessionManager()
        request.app.state.auth_sessions = mgr
    mgr.sweep(now=time.monotonic())
    return mgr


def _view(sess: Session) -> dict:
    n = sess.next
    return {
        "session_id": sess.id,
        "status": sess.status,
        "account": sess.account,
        "error": sess.error,
        "next": {
            "kind": n.kind,
            "auth_url": n.auth_url,
            "verification_uri": n.verification_uri,
            "user_code": n.user_code,
            "fields": n.fields,
            "message": n.message,
        },
    }


def _provider(connector_id: str):
    try:
        return registry.provider_for(connector_id)
    except KeyError:
        raise HTTPException(404, f"No auth provider for connector: {connector_id}")


@router.post("/{connector_id}/auth/start")
def auth_start(connector_id: str, body: StartBody, request: Request) -> dict:
    provider = _provider(connector_id)
    sess = _manager(request).start(connector_id, provider, body.params)
    return _view(sess)


@router.get("/{connector_id}/auth/status")
def auth_status(connector_id: str, request: Request, session_id: str = Query(...)) -> dict:
    sess = _manager(request).status(session_id)
    if sess is None or sess.connector_id != connector_id:
        raise HTTPException(404, "Unknown or expired auth session")
    return _view(sess)


@router.post("/{connector_id}/auth/submit")
def auth_submit(connector_id: str, body: SubmitBody, request: Request) -> dict:
    provider = _provider(connector_id)
    try:
        sess = _manager(request).submit(body.session_id, provider, body.data)
    except KeyError:
        raise HTTPException(404, "Unknown or expired auth session")
    return _view(sess)


@router.post("/{connector_id}/auth/cancel")
def auth_cancel(connector_id: str, body: CancelBody, request: Request) -> dict:
    _manager(request).cancel(body.session_id)
    return {"ok": True}
