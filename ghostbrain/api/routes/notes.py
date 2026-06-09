"""Notes endpoints — read by path (legacy), and the manual-jot family."""
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status

from ghostbrain.api.models.note import CreateNoteRequest
from ghostbrain.api.repo.note import NoteInvalidPath, NoteNotFound, get_note
from ghostbrain.api.repo.notes_manual import create_and_route_jot, list_jots

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
    """Create a manual jot and route it synchronously."""
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
    return create_and_route_jot(body, captured_at=captured)
