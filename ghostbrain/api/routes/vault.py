"""GET /v1/vault/stats, /graph, /contexts, /suggest and /backlinks."""
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ghostbrain import routing_config
from ghostbrain.api.models.graph import GraphResponse
from ghostbrain.api.models.linking import SuggestResponse
from ghostbrain.api.models.vault import VaultStats
from ghostbrain.api.repo.graph import build_graph
from ghostbrain.api.repo.linking import suggest
from ghostbrain.api.repo.vault import get_vault_stats

router = APIRouter(prefix="/v1/vault", tags=["vault"])


class NewContext(BaseModel):
    name: str


def _contexts_body() -> dict:
    return {
        "contexts": list(routing_config.contexts()),
        "archived": list(routing_config.archived_contexts()),
    }


@router.get("/contexts")
def vault_contexts() -> dict:
    """Configured context list for renderer dropdowns (routing.yaml-driven)."""
    return _contexts_body()


@router.post("/contexts", status_code=201)
def create_context(body: NewContext) -> dict:
    try:
        routing_config.add_context(body.name)
    except routing_config.ContextError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return _contexts_body()


@router.delete("/contexts/{name}")
def delete_context(name: str) -> dict:
    try:
        routing_config.archive_context(name)
    except routing_config.ContextError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return _contexts_body()


@router.get("/stats", response_model=VaultStats)
def vault_stats() -> dict:
    return get_vault_stats()


@router.get("/graph", response_model=GraphResponse)
def vault_graph() -> dict:
    return build_graph()


@router.get("/suggest", response_model=SuggestResponse)
def vault_suggest(
    kind: Literal["page", "tag", "person"] = Query(...),
    q: str = Query("", max_length=200),
    limit: int = Query(20, ge=1, le=50),
) -> dict:
    """Editor autocomplete for `[[`, `#` and `@`. `indexing: true` = cold index, retry soon."""
    return suggest(kind, q, limit)
