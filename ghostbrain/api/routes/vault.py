"""GET /v1/vault/stats and /v1/vault/graph."""
from fastapi import APIRouter

from ghostbrain.api.models.graph import GraphResponse
from ghostbrain.api.models.vault import VaultStats
from ghostbrain.api.repo.graph import build_graph
from ghostbrain.api.repo.vault import get_vault_stats

router = APIRouter(prefix="/v1/vault", tags=["vault"])


@router.get("/stats", response_model=VaultStats)
def vault_stats() -> dict:
    return get_vault_stats()


@router.get("/graph", response_model=GraphResponse)
def vault_graph() -> dict:
    return build_graph()
