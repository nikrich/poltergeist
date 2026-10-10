"""The ratification backlog (M1: a plain list; ranking/cap/bundles in milestone 2)."""
from __future__ import annotations

import threading
import uuid as uuidlib

from ghostbrain.ontology import triage
from ghostbrain.ontology.extract import EXTRACTOR_VERSION
from ghostbrain.ontology.store import norm_topic
from ghostbrain.ontology.topics import UNCLASSIFIED

ACTIONS = ("ratify", "reject", "investigate", "yes", "no")
_SCOPE_ALIASES = {"ratify": "yes", "reject": "no"}


# Serialises scope decisions so two items for one topic can never both decide it.
_scope_lock = threading.Lock()


class ItemNotFound(LookupError):
    pass


class ItemClosed(RuntimeError):
    pass


class BadAction(ValueError):
    pass


def _artefact_info(svc, project_uuid: str) -> dict[str, dict]:
    return {b["aid"]: b for b in svc.store.bindings(project_uuid)}


def list_items(svc, project_uuid: str, limit: int = 50) -> list[dict]:
    info = _artefact_info(svc, project_uuid)
    out: list[dict] = []
    for it in svc.store.open_items(project_uuid):
        base = {"id": it["id"], "type": it["type"], "created": it["created"]}
        if it["type"] == "binding":
            out.append({**base, "candidate": None, "artefacts": it["payload"].get("artefacts", []),
                        "scope": None})
            continue
        if it["type"] == "scope":
            p = it["payload"]
            out.append({**base, "candidate": None, "artefacts": [], "scope": {
                "topic_uid": p["topic_uid"], "name": p["name"], "lean": p.get("lean"),
                "notes": p.get("notes", [])}})
            continue
        c = svc.store.candidate(it["candidate_id"])
        if c is None:
            continue
        evidence = [
            {"aid": e["aid"], "path": info.get(e["aid"], {}).get("path", ""),
             "title": info.get(e["aid"], {}).get("title", e["aid"]),
             "quote": e["quote"], "locator": e["locator"]}
            for e in svc.store.evidence(c["id"])
        ]
        out.append({**base, "artefacts": [], "scope": None, "candidate": {
            "id": c["id"], "kind": c["kind"], "name": c["name"], "statement": c["statement"],
            "value": c["value"], "confidence": c["confidence"], "evidence": evidence}})
    scopes = [i for i in out if i["type"] == "scope"]
    bindings = [i for i in out if i["type"] == "binding"]
    cands = sorted((i for i in out if i["type"] == "candidate"),
                   key=lambda i: (-i["candidate"]["confidence"], i["id"]))
    return (scopes + bindings + cands)[:limit]


def act(svc, item_id: int, action: str, *, name: str | None = None, statement: str | None = None,
        value: str | None = None, exclude: list[str] | None = None, note: str | None = None) -> int | None:
    if action not in ACTIONS:
        raise BadAction(f"unknown action: {action!r}")
    it = svc.store.item(item_id)
    if it is None:
        raise ItemNotFound(item_id)
    if it["status"] != "open":
        raise ItemClosed(f"item {item_id} is already {it['status']}")
    project = it["project_uuid"]
    if it["type"] == "scope":
        return _act_scope(svc, it, project, _SCOPE_ALIASES.get(action, action), exclude or [], note)
    if action in ("yes", "no"):
        raise BadAction(f"{action!r} only applies to scope items")
    if it["type"] == "binding":
        return _act_binding(svc, it, project, action, exclude or [], note)
    return _act_candidate(svc, it, project, action, name, statement, value, note)


def _commit_claimed(svc, item_id: int, type_: str, payload: dict, resolution: str, status: str) -> int:
    """Claim the item (the double-ratify guard), then append the decision to the log.

    If the append fails the claim is released, so the decision can be retried. The
    caller updates working state only after this returns.
    """
    if not svc.store.resolve_item(item_id, resolution, status=status):
        raise ItemClosed(f"item {item_id} was closed concurrently")
    try:
        return svc.commit(type_, payload)
    except BaseException:
        svc.store.reopen_item(item_id)
        raise


def _act_binding(svc, it: dict, project: str, action: str, exclude: list[str],
                 note: str | None) -> int:
    artefacts = it["payload"].get("artefacts", [])
    excluded_set = set(exclude)
    keep = [a for a in artefacts if action == "ratify" and a["aid"] not in excluded_set]
    dropped = [a["aid"] for a in artefacts if a not in keep]
    if action == "investigate":
        type_, payload = "investigate", {"item_id": it["id"], "note": note or ""}
    else:
        type_, payload = "bind", {"project": project, "artefacts": keep, "excluded": dropped}
    resolution = "ratified" if action == "ratify" else action
    status = "parked" if action == "investigate" else "resolved"
    seq = _commit_claimed(svc, it["id"], type_, payload, resolution, status)
    for a in artefacts:
        state = "bound" if a in keep else ("proposed" if action == "investigate" else "excluded")
        svc.store.upsert_binding(project, a["aid"], a["path"], a["title"], state)
    return seq


def _act_candidate(svc, it: dict, project: str, action: str, name, statement, value, note) -> int:
    c = svc.store.candidate(it["candidate_id"])
    if c is None:
        raise ItemNotFound(it["id"])
    if action == "reject":
        payload = {"candidate_id": c["id"], "kind": c["kind"], "name": c["name"]}
        seq = _commit_claimed(svc, it["id"], "reject", payload, "reject", "resolved")
        svc.store.set_candidate_status(c["id"], "rejected")
        return seq
    if action == "investigate":
        payload = {"candidate_id": c["id"], "note": note or ""}
        seq = _commit_claimed(svc, it["id"], "investigate", payload, note or action, "parked")
        svc.store.set_candidate_status(c["id"], "investigating")
        return seq
    node = {
        "uid": c["existing_uid"] or uuidlib.uuid4().hex,
        "kind": c["kind"],
        "name": (name or c["name"]).strip(),
        "statement": (statement or c["statement"]).strip(),
        "value": value if value is not None else c["value"],
    }
    payload = {
        "candidate_id": c["id"], "project": project, "node": node,
        "relations": c["relations"],
        "evidence": [{"aid": e["aid"], "quote": e["quote"], "locator": e["locator"]}
                     for e in svc.store.evidence(c["id"])],
        "provenance": "extracted", "extractor_version": c["extractor_version"] or EXTRACTOR_VERSION,
    }
    seq = _commit_claimed(svc, it["id"], "ratify", payload, action, "resolved")
    svc.store.set_candidate_status(c["id"], "ratified")
    return seq


def _is_unclassified(svc, topic_uid: str, name: str) -> bool:
    t = svc.store.topic(topic_uid)
    return norm_topic(t["name"] if t else name) == norm_topic(UNCLASSIFIED)


def _act_unclassified(svc, it, project, action, exclude):
    """The reserved bucket of classifier failures is answered per item, never per topic.

    Only this item's notes are affected and the bucket topic is never decided. The decision is
    logged as a plain `bind` event, so replay never gives the bucket a Topic node or a scope edge.
    """
    notes = it["payload"].get("notes", [])
    drop = set(exclude) if action == "yes" else {n["aid"] for n in notes}
    keep = [{"aid": n["aid"], "path": n["path"], "title": n["title"]} for n in notes if n["aid"] not in drop]
    excluded = [n["aid"] for n in notes if n["aid"] in drop]
    payload = {"project": project, "artefacts": keep, "excluded": excluded}
    seq = _commit_claimed(svc, it["id"], "bind", payload, action, "resolved")
    for n in notes:
        svc.store.upsert_binding(project, n["aid"], n["path"], n["title"],
                                 "excluded" if n["aid"] in drop else "bound")
    return seq


def _act_scope(svc, it, project, action, exclude, note):
    p = it["payload"]
    if action == "investigate":
        return _commit_claimed(svc, it["id"], "investigate", {"item_id": it["id"], "note": note or ""},
                               note or "investigate", "parked")
    if _is_unclassified(svc, p["topic_uid"], p["name"]):
        return _act_unclassified(svc, it, project, action, exclude)
    with _scope_lock:
        return _decide_topic(svc, it["id"], project, action, exclude)


def _decide_topic(svc, item_id, project, action, exclude):
    """Decide a topic in or out. Runs under _scope_lock, so the checks below are not racy."""
    it = svc.store.item(item_id)
    if it is None or it["status"] != "open":
        raise ItemClosed(f"item {item_id} is already {it['status'] if it else 'gone'}")
    p = it["payload"]
    topic_uid = p["topic_uid"]
    topic = svc.store.topic(topic_uid)
    if topic is None or topic["status"] != "pending":
        raise ItemClosed(f"topic {p['name']!r} was already decided")
    # Any other live question about the same topic is answered by this decision too.
    others = [o for o in svc.store.scope_items(project, topic_uid) if o["id"] != item_id]
    notes, seen = [], set()
    for n in [n for o in [it, *others] for n in o["payload"].get("notes", [])]:
        if n["aid"] not in seen:
            seen.add(n["aid"])
            notes.append(n)
    seq = _apply_topic_decision(svc, it, project, topic_uid, p["name"], notes, action, exclude)
    for o in others:
        svc.store.close_item(o["id"], f"superseded by item {item_id}")
    return seq


def _apply_topic_decision(svc, it, project, topic_uid, name, notes, action, exclude):
    # Notes raised by extraction are already bound to the project; a scope answer only says
    # whether the topic's facts belong. It never excludes them and never rebinds them.
    raised = {n["aid"] for n in notes if n.get("raised_by") == "extraction"}
    sourced = [n for n in notes if n["aid"] not in raised]
    if action == "yes":
        drop = set(exclude)
        bound = {b["aid"] for b in svc.store.bindings(project, "bound")}
        keep = [{"aid": n["aid"], "path": n["path"], "title": n["title"]} for n in notes
                if n["aid"] not in drop and (n["aid"] not in raised or n["aid"] in bound)]
        excluded = [n["aid"] for n in sourced if n["aid"] in drop]
        payload = {"project": project, "topic_uid": topic_uid, "name": name, "decision": "in",
                   "artefacts": keep, "excluded": excluded}
        seq = _commit_claimed(svc, it["id"], "scope", payload, "yes", "resolved")
        svc.store.set_topic_status(topic_uid, "in")
        for n in sourced:
            svc.store.upsert_binding(project, n["aid"], n["path"], n["title"],
                                     "excluded" if n["aid"] in drop else "bound")
        for c in svc.store.candidates_for_topic(project, topic_uid, "waiting_scope"):
            triage.release_waiting(svc.store, project, c["id"])
        return seq
    # no: every onboarding-sourced note of the topic is excluded, even if bound earlier
    all_aids = sorted(set(svc.store.notes_for_topic(project, topic_uid)) | {n["aid"] for n in sourced})
    payload = {"project": project, "topic_uid": topic_uid, "name": name, "decision": "out",
               "artefacts": [], "excluded": all_aids}
    seq = _commit_claimed(svc, it["id"], "scope", payload, "no", "resolved")
    svc.store.set_topic_status(topic_uid, "out")
    info = {b["aid"]: b for b in svc.store.bindings(project)}
    by_note = {n["aid"]: n for n in notes}
    for aid in all_aids:
        src = info.get(aid) or by_note.get(aid) or {"path": "", "title": aid}
        svc.store.upsert_binding(project, aid, src["path"], src["title"], "excluded")
    for c in svc.store.candidates_for_topic(project, topic_uid, "waiting_scope"):
        svc.store.set_candidate_status(c["id"], "rejected")
    return seq
