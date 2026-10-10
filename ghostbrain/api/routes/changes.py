"""Change log routes (spec B §5; slice B2): list, detail, revert, undo.

Approve / reject of pending changes (B3) write through
``ghostbrain.changes.approve``. Revert and undo are user-only and go through
``ghostbrain.changes.revert``, which writes as ``restore``."""
from __future__ import annotations

import difflib
from collections.abc import Callable
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from ghostbrain import history
from ghostbrain.api.models.changes import STATUS_PATTERN, ChangeActionRequest
from ghostbrain.api.vault_http import request_actor
from ghostbrain.changes import approve as changes_approve
from ghostbrain.changes import log as changes_log
from ghostbrain.changes import revert as changes_revert
from ghostbrain.vault_write import USER, Actor

router = APIRouter(prefix="/v1/changes", tags=["changes"])

_UNAVAILABLE = "change log unavailable"


def _since(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        when = datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail="since must be ISO 8601") from None
    if when.tzinfo is None:
        raise HTTPException(status_code=422, detail="since must include a timezone offset")
    return when


@router.get("")
def list_route(
    status: str | None = Query(None, pattern=STATUS_PATTERN),
    actor: str | None = Query(None, min_length=1, max_length=80),
    since: str | None = Query(None, max_length=40),
    q: str | None = Query(None, max_length=200),
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    when = _since(since)
    try:
        items = changes_log.list_changes(
            status=status, actor=actor, since=when, path_query=q, limit=limit,
        )
        pending = changes_log.counts().get("pending", 0)
    except changes_log.ChangeLogError:
        raise HTTPException(status_code=503, detail=_UNAVAILABLE) from None
    return {
        "items": [c.to_api() for c in items],
        "pendingCount": pending,
        "degraded": changes_log.degraded() is not None,
    }


@router.delete("/degraded", status_code=204)
def dismiss_degraded(actor: Actor = Depends(request_actor)) -> Response:
    if actor != USER:
        raise HTTPException(status_code=403, detail="only you can dismiss this warning")
    changes_log.clear_degraded()
    return Response(status_code=204)


def _get(change_id: int) -> changes_log.Change:
    try:
        c = changes_log.get(change_id)
    except changes_log.ChangeLogError:
        raise HTTPException(status_code=503, detail=_UNAVAILABLE) from None
    if c is None:
        raise HTTPException(status_code=404, detail="no such change")
    return c


def _text(blob: str | None) -> str | None:
    if blob is None:
        return None
    try:
        return history.get_blob(blob).decode("utf-8", errors="replace")
    except (history.BlobNotFound, ValueError):
        return None


@router.get("/{change_id}")
def get_route(change_id: int) -> dict:
    c = _get(change_id)
    before = _text(c.before_blob)
    after = _text(c.pending_bytes_blob if c.status == "pending" else c.after_blob)
    state = changes_revert.drift(c)
    current_bytes = state[1] if state is not None else changes_revert.read_current(c.current_path)
    changed = state is not None and not changes_revert.matches_blob(state[1], state[0].expect)
    diff = "".join(difflib.unified_diff(
        (before or "").splitlines(keepends=True),
        (after or "").splitlines(keepends=True),
        fromfile=f"a/{c.rel_path}",
        tofile=f"b/{c.current_path}",
    ))
    return {
        **c.to_api(),
        "before": before,
        "after": after,
        "current": (
            current_bytes.decode("utf-8", errors="replace") if current_bytes is not None else None
        ),
        "changedSince": changed,
        "diff": diff,
    }


def _act(
    change_id: int,
    req: ChangeActionRequest | None,
    actor: Actor,
    fn: Callable[..., changes_revert.RevertResult],
) -> dict:
    if actor != USER:
        raise HTTPException(status_code=403, detail="only you can revert or re-apply changes")
    force = req.force if req is not None else False
    try:
        res = fn(change_id, force=force)
    except changes_revert.ChangeNotFound:
        raise HTTPException(status_code=404, detail="no such change") from None
    except changes_revert.NotRevertable as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except changes_revert.ChangedSince as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    except changes_revert.VersionGone as e:
        raise HTTPException(status_code=410, detail=str(e)) from None
    except changes_log.ChangeLogError:
        raise HTTPException(status_code=503, detail=_UNAVAILABLE) from None
    return {"id": res.change.id, "status": res.change.status, "path": res.path, "etag": res.etag}


@router.post("/{change_id}/revert")
def revert_route(
    change_id: int,
    req: ChangeActionRequest | None = None,
    actor: Actor = Depends(request_actor),
) -> dict:
    return _act(change_id, req, actor, changes_revert.revert)


@router.post("/{change_id}/undo")
def undo_route(
    change_id: int,
    req: ChangeActionRequest | None = None,
    actor: Actor = Depends(request_actor),
) -> dict:
    return _act(change_id, req, actor, changes_revert.undo_revert)


def _only_user(actor: Actor) -> None:
    if actor != USER:
        raise HTTPException(status_code=403, detail="only you can approve or reject changes")


@router.post("/{change_id}/approve")
def approve_route(
    change_id: int,
    req: ChangeActionRequest | None = None,
    actor: Actor = Depends(request_actor),
) -> dict:
    _only_user(actor)
    force = req.force if req is not None else False
    try:
        res = changes_approve.approve(change_id, force=force)
    except changes_revert.ChangeNotFound:
        raise HTTPException(status_code=404, detail="no such change") from None
    except changes_approve.NotApprovable as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except changes_approve.StaleProposal as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    except changes_revert.VersionGone as e:
        raise HTTPException(status_code=410, detail=str(e)) from None
    except changes_log.ChangeLogError:
        raise HTTPException(status_code=503, detail=_UNAVAILABLE) from None
    return {"id": res.change.id, "status": res.change.status, "path": res.path, "etag": res.etag}


@router.post("/{change_id}/reject")
def reject_route(change_id: int, actor: Actor = Depends(request_actor)) -> dict:
    _only_user(actor)
    try:
        c = changes_approve.reject(change_id)
    except changes_revert.ChangeNotFound:
        raise HTTPException(status_code=404, detail="no such change") from None
    except changes_approve.NotApprovable as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except changes_log.ChangeLogError:
        raise HTTPException(status_code=503, detail=_UNAVAILABLE) from None
    return {"id": c.id, "status": c.status}
