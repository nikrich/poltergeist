"""GET /v1/vault/stats, /v1/vault/graph and /v1/vault/contexts."""
from fastapi import APIRouter

from ghostbrain import routing_config
from ghostbrain.api.models.graph import GraphResponse
from ghostbrain.api.models.vault import VaultStats
from ghostbrain.api.repo.graph import build_graph
from ghostbrain.api.repo.vault import get_vault_stats

router = APIRouter(prefix="/v1/vault", tags=["vault"])


@router.get("/contexts")
def vault_contexts() -> dict:
    """Configured context list for renderer dropdowns (routing.yaml-driven)."""
    return {"contexts": list(routing_config.contexts())}


@router.get("/stats", response_model=VaultStats)
def vault_stats() -> dict:
    return get_vault_stats()


@router.get("/graph", response_model=GraphResponse)
def vault_graph() -> dict:
    return build_graph()
