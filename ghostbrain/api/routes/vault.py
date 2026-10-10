"""GET /v1/vault/stats, /graph, /contexts, /suggest, /backlinks and /resolve."""
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel

from ghostbrain import routing_config
from ghostbrain.api.models.graph import EgoGraphResponse, GraphResponse
from ghostbrain.api.models.linking import BacklinksResponse, ResolveResponse, SuggestResponse
from ghostbrain.api.models.vault import VaultStats
from ghostbrain.api.repo.ego_graph import FocusNotFound, ego_graph
from ghostbrain.api.repo.graph import build_graph
from ghostbrain.api.repo.linking import InvalidLinkPath, backlinks, resolve_link, suggest
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


def _json(model: type[BaseModel], body: dict) -> Response:
    return Response(model.model_validate(body).model_dump_json(), media_type="application/json")


# Each mode is validated against its own model only: a Union response_model
# would try the ego model on every whole-vault node first (~2.5x slower at 30k).
@router.get(
    "/graph",
    response_model=None,
    responses={200: {"model": GraphResponse | EgoGraphResponse}},
)
def vault_graph(
    focus: str | None = Query(None, min_length=1, max_length=500),
    depth: int = Query(2, ge=1, le=3),
) -> Response:
    """Without `focus`: the whole-vault graph (BrainConstellation, Graph tab's
    whole-vault mode). With `focus`: its link neighbourhood up to `depth` hops,
    ghosts included, capped at 300 nodes nearest first."""
    if focus is None:
        return _json(GraphResponse, build_graph())
    try:
        return _json(EgoGraphResponse, ego_graph(focus, depth))
    except InvalidLinkPath as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FocusNotFound as e:
        raise HTTPException(status_code=404, detail="note not found") from e


@router.get("/suggest", response_model=SuggestResponse)
def vault_suggest(
    kind: Literal["page", "tag", "person"] = Query(...),
    q: str = Query("", max_length=200),
    limit: int = Query(20, ge=1, le=50),
) -> dict:
    """Editor autocomplete for `[[`, `#` and `@`. `indexing: true` = cold index, retry soon."""
    return suggest(kind, q, limit)


@router.get("/backlinks", response_model=BacklinksResponse)
def vault_backlinks(
    path: str = Query(..., min_length=1, max_length=500),
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    """Notes linking to `path` (with or without `.md`), newest first."""
    try:
        return backlinks(path, limit)
    except InvalidLinkPath as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/resolve", response_model=ResolveResponse)
def vault_resolve(target: str = Query(..., min_length=1, max_length=500)) -> dict:
    """Where a click on `[[target]]` should go. `exists: false` = not written yet."""
    try:
        return resolve_link(target)
    except InvalidLinkPath as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
