"""/v1/ontology — project ontologies, the ratification backlog and the gold graph."""
from __future__ import annotations

import threading
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import APIRouter, HTTPException, Query

from ghostbrain.api.models.ontology import (
    ActionResult, EnableRequest, ExtractRequest, ExtractStatus, OntologyActionRequest, OntologyGraph,
    OntologyItem, OntologyNodeDetail, OntologyProject, OntologyStatus, OnboardResult, OntologyTopic, RebuildResult, RevertRequest,
)
from ghostbrain.api.repo import projects as projects_repo
from ghostbrain.ontology import backlog, onboarding, pipeline, projection_md
from ghostbrain.ontology.graph import GraphUnavailable
from ghostbrain.ontology.schema import DOMAIN_KINDS, ui_kind
from ghostbrain.ontology.service import get_service
from ghostbrain.paths import vault_path

router = APIRouter(prefix="/v1/ontology", tags=["ontology"])


def _unavailable(e: GraphUnavailable) -> HTTPException:
    return HTTPException(status_code=503, detail=str(e))


def _project_view(svc, project_uuid: str, seeds: list[str]) -> dict:
    p = projects_repo.get_project_by_uuid(project_uuid) or {}
    return {
        "uuid": project_uuid, "id": p.get("id", ""), "name": p.get("name", "(missing project)"),
        "context": p.get("context", ""), "seeds": seeds,
        "bound": len(svc.store.bindings(project_uuid, "bound")),
        "pending_items": len(svc.store.open_items(project_uuid)),
    }


_onboarding_locks: dict[str, threading.Lock] = {}
_onboarding_locks_guard = threading.Lock()


def _onboarding_lock(project_uuid: str) -> threading.Lock:
    with _onboarding_locks_guard:
        return _onboarding_locks.setdefault(project_uuid, threading.Lock())


@contextmanager
def _onboarding(project_uuid: str) -> Iterator[None]:
    """One onboarding run per project at a time; a second concurrent call is refused (409)."""
    lock = _onboarding_lock(project_uuid)
    if not lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="onboarding already running for this project")
    try:
        yield
    finally:
        lock.release()


def _require_enabled(svc, project_uuid: str) -> list[str]:
    seeds = svc.store.project_seeds(project_uuid)
    if seeds is None:
        raise HTTPException(status_code=404, detail=f"ontology not enabled for project {project_uuid}")
    return seeds


@router.get("/status", response_model=OntologyStatus)
def status() -> dict:
    return get_service().status()


@router.get("/projects", response_model=list[OntologyProject])
def list_enabled() -> list[dict]:
    svc = get_service()
    return [_project_view(svc, p["project_uuid"], p["seeds"]) for p in svc.store.enabled_projects()]


@router.post("/projects/enable", response_model=OntologyProject)
def enable(payload: EnableRequest) -> dict:
    seeds = [s.strip() for s in payload.seeds if s.strip()]
    if not seeds:
        raise HTTPException(status_code=422, detail="at least one non-empty seed term is required")
    projects_repo.ensure_project_uuids()
    match = next((p for p in projects_repo.list_projects() if p["id"] == payload.project_id), None)
    if match is None:
        raise HTTPException(status_code=422, detail=f"unknown project: {payload.project_id}")
    svc = get_service()
    with _onboarding(match["uuid"]):
        svc.store.enable_project(match["uuid"], seeds)
        svc.seed()
        onboarding.onboard(svc, match["uuid"])
    return _project_view(svc, match["uuid"], seeds)


@router.post("/projects/{project_uuid}/scope", response_model=OnboardResult, response_model_by_alias=True)
def rescope(project_uuid: str) -> dict:
    svc = get_service()
    _require_enabled(svc, project_uuid)
    with _onboarding(project_uuid):
        return onboarding.onboard(svc, project_uuid)


_TOPIC_NOTE_STATE = {"in": "bound", "out": "excluded", "pending": "scoping"}


@router.get("/projects/{project_uuid}/topics", response_model=list[OntologyTopic])
def list_topics(project_uuid: str) -> list[dict]:
    svc = get_service()
    _require_enabled(svc, project_uuid)
    state = {b["aid"]: b["status"] for b in svc.store.bindings(project_uuid)}

    def count(t: dict) -> int:
        # in: notes bound under it; out: notes it excluded; pending: notes awaiting the answer
        want = _TOPIC_NOTE_STATE.get(t["status"])
        return sum(1 for aid in svc.store.notes_for_topic(project_uuid, t["uid"]) if state.get(aid) == want)

    return [{"uid": t["uid"], "name": t["name"], "status": t["status"], "notes": count(t)}
            for t in svc.store.topics(project_uuid)]


@router.post("/projects/{project_uuid}/extract", response_model=ExtractStatus)
def start_extract(project_uuid: str, payload: ExtractRequest) -> dict:
    svc = get_service()
    _require_enabled(svc, project_uuid)
    runner = pipeline.get_runner(svc)
    if not runner.start(project_uuid, payload.limit):
        raise HTTPException(status_code=409, detail="an extraction run is already in progress")
    return runner.status()


@router.get("/projects/{project_uuid}/extract", response_model=ExtractStatus)
def extract_status(project_uuid: str) -> dict:  # noqa: ARG001 - one runner per sidecar
    return pipeline.get_runner(get_service()).status()


@router.get("/backlog", response_model=list[OntologyItem])
def list_backlog(project: str = Query(...)) -> list[dict]:
    return backlog.list_items(get_service(), project)


@router.post("/backlog/{item_id}/action", response_model=ActionResult)
def act(item_id: int, payload: OntologyActionRequest) -> dict:
    try:
        seq = backlog.act(get_service(), item_id, payload.action, name=payload.name,
                          statement=payload.statement, value=payload.value,
                          exclude=payload.exclude, note=payload.note)
    except backlog.ItemNotFound:
        raise HTTPException(status_code=404, detail=f"no backlog item {item_id}") from None
    except backlog.ItemClosed as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    except backlog.BadAction as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    return {"ok": True, "seq": seq}


@router.get("/graph", response_model=OntologyGraph)
def graph(project: str = Query(...), focus: str | None = None, depth: int = Query(2, ge=1, le=3)) -> dict:
    svc = get_service()
    p = projects_repo.get_project_by_uuid(project) or {}
    try:
        with svc.graph_session() as g:
            nodes, edges, truncated = g.neighbourhood(focus or project, depth)
    except GraphUnavailable as e:
        raise _unavailable(e) from None
    degree = Counter([e["src"] for e in edges] + [e["dst"] for e in edges])
    return {
        "focus": focus or project, "depth": depth, "truncated": truncated,
        "nodes": [{"path": n["uid"], "title": n["name"], "context": p.get("name", ""),
                   "kind": ui_kind(n["kind"]), "degree": degree[n["uid"]], "ghost": False,
                   "hop": n["hop"], "note_path": n["note_path"]} for n in nodes],
        "edges": [{"source": e["src"], "target": e["dst"], "weight": 1.0, "kind": e["type"].lower()}
                  for e in edges],
    }


@router.get("/nodes/{uid}", response_model=OntologyNodeDetail)
def node_detail(uid: str) -> dict:
    svc = get_service()
    try:
        with svc.graph_session() as g:
            node = g.node_detail(uid)
    except GraphUnavailable as e:
        raise _unavailable(e) from None
    if node is None:
        raise HTTPException(status_code=404, detail=f"no gold node {uid}")
    generated = None
    if node["kind"] in DOMAIN_KINDS:
        project = projects_repo.get_project_by_uuid(node["project_uid"]) if node["project_uid"] else None
        if project is not None:
            rel = projection_md.generated_note_path(project, node)
            generated = rel if (vault_path() / rel).is_file() else None
    ratified = node.get("valid_from")
    return {
        "uid": uid, "kind": ui_kind(node["kind"]), "name": node["name"] or uid,
        "statement": node["statement"], "value": node["value"], "provenance": node["provenance"],
        "ratified_at": None if ratified is None else str(ratified),
        "note_path": node["note_path"], "generated_note_path": generated,
        "evidence": node["evidence"],
        "relations": [{**r, "kind": ui_kind(r["kind"])} for r in node["relations"]],
    }


@router.post("/nodes/{uid}/revert", response_model=ActionResult)
def revert(uid: str, payload: RevertRequest) -> dict:
    svc = get_service()
    try:
        with svc.graph_session() as g:
            node = g.node(uid)
            if node is None:
                raise HTTPException(status_code=404, detail=f"no gold node {uid}")
            if node["kind"] not in DOMAIN_KINDS:
                raise HTTPException(status_code=422, detail=f"{node['kind']} nodes cannot be reverted")
    except GraphUnavailable as e:
        raise _unavailable(e) from None
    return {"ok": True, "seq": svc.commit("revert", {"uid": uid, "project": payload.project})}


@router.post("/rebuild", response_model=RebuildResult)
def rebuild() -> dict:
    try:
        return {"applied": get_service().rebuild()}
    except GraphUnavailable as e:
        raise _unavailable(e) from None
