"""GET /v1/meetings + /v1/meetings/prep/{event_id}."""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from ghostbrain.api.models.meeting import MeetingsPage, Prep
from ghostbrain.api.repo.meeting_prep import get_prep, prewarm as prewarm_prep, set_prep
from ghostbrain.api.repo.meetings import list_meetings
from ghostbrain.worker.meeting_prep import (
    UnknownEvent,
    build_prep,
    event_hash,
    resolve_event_path,
)
import frontmatter

router = APIRouter(prefix="/v1/meetings", tags=["meetings"])


@router.get("", response_model=MeetingsPage)
def meetings(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    return list_meetings(limit=limit, offset=offset)


@router.get("/prep/{event_id}", response_model=Prep)
def get_meeting_prep(event_id: str) -> Prep:
    """Return cached prep (if hash matches) or generate synchronously."""
    path = resolve_event_path(event_id)
    if path is None:
        raise HTTPException(status_code=404, detail=f"unknown event: {event_id}")
    post = frontmatter.load(path)
    fm = post.metadata or {}
    expected = event_hash({
        "start": str(fm.get("start") or ""),
        "end": str(fm.get("end") or ""),
        "description": str(fm.get("description") or ""),
    })
    cached = get_prep(event_id, expected_hash=expected)
    if cached is not None:
        return cached
    try:
        prep = build_prep(event_id)
    except UnknownEvent as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    set_prep(prep)
    return prep


@router.post("/prep/{event_id}/prewarm")
def prewarm_meeting_prep(event_id: str) -> JSONResponse:
    """Fire-and-forget background generation. Returns 202."""
    path = resolve_event_path(event_id)
    if path is None:
        raise HTTPException(status_code=404, detail=f"unknown event: {event_id}")
    launched = prewarm_prep(event_id)
    return JSONResponse(
        status_code=202,
        content={"status": "started" if launched else "in_progress"},
    )
