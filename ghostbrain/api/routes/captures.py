"""GET /v1/captures, GET /v1/captures/{id}."""
from fastapi import APIRouter, HTTPException, Query

from ghostbrain.api.models.capture import Capture, CapturesPage
from ghostbrain.api.repo.captures import get_capture, list_captures

router = APIRouter(prefix="/v1/captures", tags=["captures"])


@router.get("", response_model=CapturesPage)
def captures(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    source: str | None = Query(None),
) -> dict:
    return list_captures(limit=limit, offset=offset, source=source)


@router.get("/{capture_id:path}", response_model=Capture)
def capture_detail(capture_id: str) -> dict:
    # `:path` lets Starlette accept ids that contain `/` (e.g. github
    # captures use `github:pr:owner/repo#NNN`). Without it, an encoded `/`
    # in the path segment fails to match the route.
    record = get_capture(capture_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Capture not found: {capture_id}")
    return record
