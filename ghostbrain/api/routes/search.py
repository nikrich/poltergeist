"""POST /v1/search — semantic search across the vault."""
from fastapi import APIRouter

from ghostbrain.api.models.search import SearchRequest, SearchResponse
from ghostbrain.api.repo.search import search as repo_search

router = APIRouter(prefix="/v1/search", tags=["search"])


@router.post("", response_model=SearchResponse)
def search(payload: SearchRequest) -> dict:
    return repo_search(q=payload.q, limit=payload.limit)
