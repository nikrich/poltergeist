"""Page history (spec A3): list a note's versions, read one, restore one.

Snapshots are taken by the vault write path itself; these routes only read
the store and restore through ``vault_write.write(actor=RESTORE)``, which
snapshots the version being replaced first."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

import ghostbrain.paths as _paths
from ghostbrain import history, vault_write
from ghostbrain.api.models.history import BLOB_PATTERN, RestoreRequest
from ghostbrain.api.vault_http import if_match
from ghostbrain.vault_write import RESTORE

router = APIRouter(prefix="/v1/notes/history", tags=["history"])


def _canonical(path: str) -> str:
    """The rel path the write path logs under (resolved, POSIX). Raises
    vault_write.InvalidPath (→ 400) for anything outside the vault."""
    target = vault_write.resolve_safe(path)
    return target.relative_to(_paths.vault_path().resolve()).as_posix()


def _entry(s: history.Snapshot) -> dict:
    return {"ts": s.ts, "path": s.rel_path, "blob": s.blob, "actor": s.actor,
            "reason": s.reason, "size": s.size}


def _find(rel: str, blob: str) -> history.Snapshot:
    match = next((s for s in history.list_snapshots(rel) if s.blob == blob), None)
    if match is None:
        raise HTTPException(status_code=404, detail="no such version of this note")
    return match


def _blob_text(blob: str) -> str:
    try:
        return history.get_blob(blob).decode("utf-8")
    except history.BlobNotFound:
        raise HTTPException(status_code=404, detail="this version is no longer available")
    except UnicodeDecodeError:
        raise HTTPException(status_code=422, detail="this version is not UTF-8 text")


@router.get("")
def list_history(
    path: str = Query(..., min_length=1, max_length=500),
    limit: int = Query(200, ge=1, le=1000),
) -> dict:
    rel = _canonical(path)
    return {"path": rel, "items": [_entry(s) for s in history.list_snapshots(rel, limit=limit)]}


@router.get("/blob")
def get_version(
    path: str = Query(..., min_length=1, max_length=500),
    blob: str = Query(..., pattern=BLOB_PATTERN),
) -> dict:
    rel = _canonical(path)
    _find(rel, blob)
    content = _blob_text(blob)
    try:
        current: str | None = (
            vault_write.resolve_safe(rel).read_bytes().decode("utf-8", errors="replace")
        )
    except FileNotFoundError:
        current = None
    return {"path": rel, "blob": blob, "content": content, "current": current}


@router.post("/restore")
def restore_version(req: RestoreRequest, base_etag: str | None = Depends(if_match)) -> dict:
    rel = _canonical(req.path)
    match = _find(rel, req.blob)
    text = _blob_text(req.blob)
    exists = vault_write.current_etag(rel) is not None
    res = vault_write.write(
        rel,
        content=text,
        op="modify" if exists else "create",
        actor=RESTORE,
        reason=f"restored the version from {match.ts}",
        base_etag=base_etag,
    )
    return {
        "path": res.path,
        "etag": res.etag,
        "body": vault_write.read(rel).body,
        "restored": req.blob,
        "historyOk": res.history_ok,
    }
