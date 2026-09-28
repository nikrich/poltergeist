"""GET /v1/vault/stats, /v1/vault/graph and /v1/vault/contexts."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ghostbrain import routing_config
from ghostbrain.api.models.graph import GraphResponse
from ghostbrain.api.models.vault import VaultStats
from ghostbrain.api.repo.graph import build_graph
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
