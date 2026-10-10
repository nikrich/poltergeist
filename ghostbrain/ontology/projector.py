"""Projects the append-only log onto the gold graph.

Every handler is deterministic in (graph state, event), so `rebuild()` (clear and
replay) always equals incremental `apply()`; test_ontology_projector pins this.
"""
from __future__ import annotations

from ghostbrain.ontology.graph import GoldGraph
from ghostbrain.ontology.store import Event, Store


def _seed(g: GoldGraph, ev: Event) -> None:
    for n in ev.payload["nodes"]:
        g.upsert_node(n["uid"], n["kind"], {**n.get("props", {}), "provenance": "seeded"})
    for e in ev.payload["edges"]:
        g.upsert_edge(e["type"], e["src"], e["dst"], e.get("props", {}))


def _bind(g: GoldGraph, ev: Event) -> None:
    project = ev.payload["project"]
    for a in ev.payload["artefacts"]:
        g.upsert_node(a["aid"], "Artefact", {"name": a["title"], "note_path": a["path"]})
        g.upsert_edge("ABOUT", a["aid"], project, {"ratification_id": ev.seq})


def _ratify(g: GoldGraph, ev: Event) -> None:
    p = ev.payload
    node = p["node"]
    g.upsert_node(node["uid"], node["kind"], {
        "name": node["name"], "statement": node["statement"], "value": node.get("value"),
        "ratification_id": ev.seq, "valid_from": ev.ts, "provenance": p["provenance"],
        "extractor_version": p["extractor_version"],
    })
    g.upsert_edge("PART_OF", node["uid"], p["project"], {"ratification_id": ev.seq})
    for rel in p.get("relations", []):
        g.upsert_edge(rel["type"], node["uid"], rel["target_uid"], {"ratification_id": ev.seq})
    for e in p.get("evidence", []):
        g.upsert_node(e["aid"], "Artefact", {})
        g.upsert_edge("EVIDENCED_BY", node["uid"], e["aid"],
                      {"quote": e["quote"], "locator": e.get("locator", ""), "ratification_id": ev.seq})


def _revert(g: GoldGraph, ev: Event) -> None:
    g.delete_node(ev.payload["uid"])


def _relabel(g: GoldGraph, ev: Event) -> None:
    g.set_props(ev.payload["uid"], {"name": ev.payload["name"]})


def _scope(g: GoldGraph, ev: Event) -> None:
    p = ev.payload
    edge = "IN_SCOPE" if p["decision"] == "in" else "OUT_OF_SCOPE"
    g.upsert_node(p["topic_uid"], "Topic", {"name": p["name"], "project": p["project"]})
    g.upsert_edge(edge, p["topic_uid"], p["project"], {"ratification_id": ev.seq, "valid_from": ev.ts})
    if p["decision"] == "in":
        for a in p.get("artefacts", []):
            g.upsert_node(a["aid"], "Artefact", {"name": a["title"], "note_path": a["path"]})
            g.upsert_edge("ABOUT", a["aid"], p["project"], {"ratification_id": ev.seq})
            g.upsert_edge("HAS_TOPIC", a["aid"], p["topic_uid"], {"ratification_id": ev.seq})
        for aid in p.get("excluded", []):
            g.delete_edge("ABOUT", aid, p["project"])
    else:
        for aid in [a["aid"] for a in p.get("artefacts", [])] + list(p.get("excluded", [])):
            g.delete_edge("ABOUT", aid, p["project"])


_HANDLERS = {"seed": _seed, "bind": _bind, "ratify": _ratify, "revert": _revert, "relabel": _relabel,
             "scope": _scope}


def apply(graph: GoldGraph, event: Event) -> None:
    with graph.transaction():
        handler = _HANDLERS.get(event.type)
        if handler is not None:
            handler(graph, event)
        graph.set_meta(event.seq)


def catch_up(store: Store, graph: GoldGraph) -> int:
    applied = 0
    for ev in store.events(after=graph.get_meta()):
        apply(graph, ev)
        applied += 1
    return applied


def rebuild(store: Store, graph: GoldGraph) -> int:
    with graph.transaction():
        graph.clear()
        graph.set_meta(0)
    return catch_up(store, graph)
