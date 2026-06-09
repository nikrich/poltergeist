"""GET /v1/notes?path=<vault-relative> and POST /v1/notes."""
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status

from ghostbrain.api.models.note import CreateNoteRequest, Note
from ghostbrain.api.repo.note import NoteInvalidPath, NoteNotFound, get_note
from ghostbrain.api.repo.notes_manual import create_and_route_jot

router = APIRouter(prefix="/v1/notes", tags=["notes"])


@router.get("", response_model=Note)
def note(path: str = Query(..., min_length=1, max_length=500)) -> dict:
    try:
        return get_note(path)
    except NoteInvalidPath as e:
        raise HTTPException(status_code=400, detail=str(e))
    except NoteNotFound:
        raise HTTPException(status_code=404, detail=f"Note not found: {path}")


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
