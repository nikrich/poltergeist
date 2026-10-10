"""Permanent identities for the core layer, and the `seed` event that puts
Self, contexts and projects into the gold graph."""
from __future__ import annotations

from ghostbrain import routing_config
from ghostbrain.api.repo import projects as projects_repo
from ghostbrain.ontology.schema import SELF_UID
from ghostbrain.ontology.store import Store


def context_uuid(store: Store, name: str) -> str:
    return store.ensure_identity("context", name, name)


def seed_payload(store: Store) -> dict:
    nodes: list[dict] = [{"uid": SELF_UID, "kind": "Self", "props": {"name": "me"}}]
    edges: list[dict] = []
    ctx_uids: dict[str, str] = {}
    for name in sorted(routing_config.contexts()):
        uid = context_uuid(store, name)
        ctx_uids[name] = uid
        nodes.append({"uid": uid, "kind": "Context", "props": {"name": name}})
        edges.append({"type": "WORKS_IN", "src": SELF_UID, "dst": uid, "props": {}})
    for p in sorted(projects_repo.ensure_project_uuids(), key=lambda p: p["uuid"]):
        if p.get("archived") or p["context"] not in ctx_uids:
            continue
        nodes.append({"uid": p["uuid"], "kind": "Project", "props": {"name": p["name"]}})
        edges.append({"type": "IN", "src": p["uuid"], "dst": ctx_uids[p["context"]], "props": {}})
    return {"nodes": nodes, "edges": edges}
