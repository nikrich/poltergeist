"""Onboard a project: bind strong matches, classify unsure notes into topics, and ask
one scope question per undecided topic. Decided topics route automatically."""
from __future__ import annotations

from collections import Counter

from ghostbrain.api.repo import projects as projects_repo
from ghostbrain.ontology import scope, topics


def core_topic(svc, project_uuid: str) -> dict:
    """The project's own topic, in scope from the start. Its creation is logged once (as a
    system scope decision) so the Topic node and its IN_SCOPE edge exist in gold and replay."""
    project = projects_repo.get_project_by_uuid(project_uuid) or {}
    t, created = svc.store.ensure_topic_created(project_uuid, str(project.get("name") or "core"),
                                                status="in")
    if created:
        svc.commit("scope", {"project": project_uuid, "topic_uid": t["uid"], "name": t["name"],
                             "decision": "in", "artefacts": [], "excluded": []}, actor="system")
    return t


def _project_dir(project: dict) -> str | None:
    if not project:
        return None
    return projects_repo.PROJECT_DIR_TEMPLATE.format(context=project["context"], slug=project["slug"])


def _lean(leans: list[str]) -> str:
    counts = Counter(leans).most_common()
    if len(counts) > 1 and counts[0][1] == counts[1][1]:
        return "unclear"
    return counts[0][0] if counts else "unclear"


def onboard(svc, project_uuid: str, *, run=None, search_fn=None) -> dict:
    store = svc.store
    project = projects_repo.get_project_by_uuid(project_uuid) or {}
    seeds = store.project_seeds(project_uuid) or []
    core_topic(svc, project_uuid)
    refs = scope.find_artefacts(seeds, search_fn=search_fn, project_dir=_project_dir(project))
    known = {b["aid"]: b["status"] for b in store.bindings(project_uuid)}
    in_refs: list[scope.ArtefactRef] = []
    out = {"binding_item": None, "in": 0, "unsure": 0, "auto_in": 0, "auto_out": 0,
           "scope_items": [], "classified": 0}

    def exclude(r: scope.ArtefactRef) -> None:
        store.upsert_binding(project_uuid, r.aid, r.path, r.title, "excluded")
        out["auto_out"] += 1

    to_classify: list[scope.ArtefactRef] = []
    for r in refs:
        if r.aid in known:
            continue
        decided = store.note_topic(project_uuid, r.aid)
        topic = store.topic(decided) if decided else None
        status = topic["status"] if topic else None
        if status == "out" and topic["name"] != topics.UNCLASSIFIED:
            exclude(r)
        elif r.band == "in":
            in_refs.append(r)
            out["in"] += 1
        else:
            out["unsure"] += 1
            if status == "in" and topic["name"] != topics.UNCLASSIFIED:
                in_refs.append(r)
                out["auto_in"] += 1
            else:
                to_classify.append(r)

    groups: dict[str, list[tuple[scope.ArtefactRef, topics.Verdict]]] = {}
    if to_classify:
        notes = []
        for r in to_classify:
            loaded = scope.read_artefact(r.path)
            text = scope.strip_links(loaded[1]) if loaded else ""
            notes.append(topics.NoteIn(r.aid, r.title, text))
        known_topics = [{"name": t["name"], "status": t["status"]} for t in store.topics(project_uuid)]
        verdicts = topics.classify_notes(str(project.get("name") or ""), seeds, known_topics, notes, run=run)
        # A classifier that answers short (or long) must not drop notes: pad with the bucket.
        verdicts = list(verdicts[:len(notes)]) + [topics.fallback_verdict(n) for n in notes[len(verdicts):]]
        out["classified"] = len(verdicts)
        for r, v in zip(to_classify, verdicts):
            t = store.ensure_topic(project_uuid, v.topic)
            store.set_note_topic(project_uuid, r.aid, t["uid"])
            if t["name"] == topics.UNCLASSIFIED:   # never auto-routed: failures always surface
                groups.setdefault(t["uid"], []).append((r, v))
            elif t["status"] == "in":
                in_refs.append(r)
                out["auto_in"] += 1
            elif t["status"] == "out":
                exclude(r)
            else:
                groups.setdefault(t["uid"], []).append((r, v))

    out["binding_item"] = scope.propose_binding(store, project_uuid, in_refs)
    for topic_uid, members in groups.items():
        t = store.topic(topic_uid)
        new_notes = [{"aid": r.aid, "path": r.path, "title": r.title, "reason": v.reason} for r, v in members]
        for r, _ in members:
            store.upsert_binding(project_uuid, r.aid, r.path, r.title, "scoping")
        # a parked topic question is still the live one; the reserved bucket only joins open items
        existing = store.open_scope_item(project_uuid, topic_uid,
                                         include_parked=t["name"] != topics.UNCLASSIFIED)
        if existing:
            payload = existing["payload"]
            seen = {n["aid"] for n in payload.get("notes", [])}
            payload["notes"] = payload.get("notes", []) + [n for n in new_notes if n["aid"] not in seen]
            store.update_item_payload(existing["id"], payload)
            continue
        item = store.add_item(project_uuid, "scope", payload={
            "topic_uid": topic_uid, "name": t["name"], "lean": _lean([v.lean for _, v in members]),
            "notes": new_notes})
        out["scope_items"].append(item)
    return out
