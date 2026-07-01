"""POST /v1/search — semantic search across the vault.

Also exposes the search-index status and a manual reindex trigger so the UI can
show when the index was last rebuilt and force a refresh.
"""
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from ghostbrain.api.models.search import SearchRequest, SearchResponse
from ghostbrain.api.repo.search import (
    index_status,
    search as repo_search,
    start_reindex,
)

router = APIRouter(prefix="/v1/search", tags=["search"])


@router.post("", response_model=SearchResponse)
def search(payload: SearchRequest) -> dict:
    return repo_search(q=payload.q, limit=payload.limit)


@router.get("/status")
def search_index_status() -> dict:
    """{ lastIndexedAt, noteCount, model, running } — cheap, no model load."""
    return index_status()


@router.post("/reindex")
def search_reindex() -> JSONResponse:
    """Trigger a background semantic refresh. 202 when started, 409 if one is
    already running."""
    result = start_reindex()
    if not result["started"]:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"started": False, "detail": "a reindex is already running"},
        )
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=result)
