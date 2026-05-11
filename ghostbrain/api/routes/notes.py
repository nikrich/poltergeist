"""GET /v1/notes?path=<vault-relative>."""
from fastapi import APIRouter, HTTPException, Query

from ghostbrain.api.models.note import Note
from ghostbrain.api.repo.note import NoteInvalidPath, NoteNotFound, get_note

router = APIRouter(prefix="/v1/notes", tags=["notes"])


@router.get("", response_model=Note)
def note(path: str = Query(..., min_length=1, max_length=500)) -> dict:
    try:
        return get_note(path)
    except NoteInvalidPath as e:
        raise HTTPException(status_code=400, detail=str(e))
    except NoteNotFound:
        raise HTTPException(status_code=404, detail=f"Note not found: {path}")
