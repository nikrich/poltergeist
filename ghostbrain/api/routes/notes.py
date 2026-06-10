"""Notes endpoints — read by path (legacy), and the manual-jot family."""
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from fastapi import Path as PathParam
from fastapi.responses import Response

from ghostbrain.api.models.note import (
    CreateNoteRequest,
    RouteNoteRequest,
    UpdateNoteBodyRequest,
    UpdateNoteRequest,
)
from ghostbrain.api.repo.note import (
    NoteInvalidPath,
    NoteNotFound,
    get_note,
    save_note_body,
)
from ghostbrain.api.repo.notes_manual import (
    JotNotFound,
    create_and_route_jot,
    delete_jot,
    list_jots,
    move_jot,
    route_existing_jot,
    update_jot_body,
    write_inbox_jot,
)

# Known contexts must match the router's enum — keep this list in sync with
# ROUTER_JSON_SCHEMA in ghostbrain/worker/router.py. "needs_review" is
# intentionally excluded: it is a fallback state, not a valid user-selectable
# destination for manual re-routes.
_KNOWN_CONTEXTS = {"sanlam", "codeship", "reducedrecipes", "personal"}

router = APIRouter(prefix="/v1/notes", tags=["notes"])


@router.get("")
def get_notes(
    path: str | None = Query(None, min_length=1, max_length=500),
    source: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    q: str | None = Query(None),
    context: str | None = Query(None),
    tag: str | None = Query(None),
):
    """Dispatcher:
    - `?path=...`  → single-note read (legacy markdown viewer).
    - `?source=manual` → list manual jots for the Jot screen.
    """
    if path is not None:
        try:
            return get_note(path)
        except NoteInvalidPath as e:
            raise HTTPException(status_code=400, detail=str(e))
        except NoteNotFound:
            raise HTTPException(status_code=404, detail=f"Note not found: {path}")
    if source == "manual":
        return list_jots(limit=limit, offset=offset, q=q, context=context, tag=tag)
    if source is None:
        raise HTTPException(
            status_code=400, detail="provide `path` or `source=manual`",
        )
    raise HTTPException(
        status_code=400, detail=f"unsupported source filter: {source}",
    )


@router.post("", status_code=status.HTTP_200_OK)
def create_note(req: CreateNoteRequest) -> dict:
    """Create a manual jot, optionally routing it synchronously.

    When ``route=false`` the jot is written to the inbox with
    routingStatus="pending" and no LLM call is made.  The caller is expected
    to fire ``POST /v1/notes/{id}/route-auto`` once the user has finished
    editing (auto-route on leave).
    """
    body = req.body.strip()
    if not body:
        raise HTTPException(status_code=422, detail="body must not be empty")
    captured: datetime | None = None
    if req.capturedAt:
        try:
            captured = datetime.fromisoformat(req.capturedAt)
        except ValueError:
            raise HTTPException(status_code=422, detail="capturedAt must be ISO8601")
        if captured.tzinfo is None:
            raise HTTPException(
                status_code=422,
                detail="capturedAt must include a timezone offset (e.g. 2026-05-14T09:30:15+00:00)",
            )
    if not req.route:
        record = write_inbox_jot(body, captured_at=captured)
        return {
            "id": record["id"],
            "path": record["path"],
            "routingStatus": "pending",
        }
    return create_and_route_jot(body, captured_at=captured)


# ── Order-sensitive: /body must be registered BEFORE /{jot_id} ──────────────
# Starlette matches routes in registration order, and the literal segment
# "body" satisfies the /{jot_id} path regex ([^/]+). The jot route's
# min_length=8 validator would then 422 the request ("string_too_short")
# instead of falling through to this handler. Pinned by
# test_patch_body_not_shadowed_by_jot_route.
@router.patch("/body")
def patch_note_body(req: UpdateNoteBodyRequest) -> dict:
    """Rewrite the markdown body of any vault note by path.

    Frontmatter is preserved; `updated` bumped when the key exists. Unlike the
    jot PATCH, this does NOT re-derive tags — connector files own their schema.
    """
    if not req.body.strip():
        raise HTTPException(status_code=422, detail="body must not be empty")
    try:
        return save_note_body(req.path, req.body)
    except NoteInvalidPath as e:
        raise HTTPException(status_code=400, detail=str(e))
    except NoteNotFound:
        raise HTTPException(status_code=404, detail=f"Note not found: {req.path}")


@router.patch("/{jot_id}")
def patch_note(
    req: UpdateNoteRequest,
    jot_id: str = PathParam(..., min_length=8, max_length=128),
) -> dict:
    """Update the body (and re-derive tags) of an existing jot."""
    body = req.body
    if not body.strip():
        raise HTTPException(status_code=422, detail="body must not be empty")
    try:
        return update_jot_body(jot_id, body)
    except JotNotFound:
        raise HTTPException(status_code=404, detail=f"Jot not found: {jot_id}")


@router.post("/{jot_id}/route-auto")
def route_note_auto(
    jot_id: str = PathParam(..., min_length=8, max_length=128),
) -> dict:
    """LLM-auto-route an existing jot by re-reading its current body.

    Returns {id, path, routingStatus, context?}. Routing errors and
    low-confidence results fall back to manual_review (never 500s).
    404 when the jot does not exist.
    """
    try:
        return route_existing_jot(jot_id)
    except JotNotFound:
        raise HTTPException(status_code=404, detail=f"Jot not found: {jot_id}")


@router.post("/{jot_id}/route")
def route_note(
    req: RouteNoteRequest,
    jot_id: str = PathParam(..., min_length=8, max_length=128),
) -> dict:
    """Manually re-route a jot to a known context."""
    if req.context not in _KNOWN_CONTEXTS:
        raise HTTPException(
            status_code=400,
            detail=f"unknown context: {req.context!r}; valid: {sorted(_KNOWN_CONTEXTS)}",
        )
    try:
        return move_jot(
            jot_id,
            to_context=req.context,
            confidence=1.0,
            method="user",
            reasoning="manual re-route by user",
        )
    except JotNotFound:
        raise HTTPException(status_code=404, detail=f"Jot not found: {jot_id}")


@router.delete("/{jot_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(
    jot_id: str = PathParam(..., min_length=8, max_length=128),
) -> Response:
    """Delete a jot permanently."""
    try:
        delete_jot(jot_id)
    except JotNotFound:
        raise HTTPException(status_code=404, detail=f"Jot not found: {jot_id}")
    return Response(status_code=204)
