import random

import pytest

pytest.importorskip("arcadedb_embedded")

from ghostbrain.ontology import projector  # noqa: E402
from ghostbrain.ontology.graph import GoldGraph  # noqa: E402
from ghostbrain.ontology.store import Store  # noqa: E402

SEED = {"nodes": [{"uid": "self", "kind": "Self", "props": {"name": "me"}},
                  {"uid": "c1", "kind": "Context", "props": {"name": "work"}},
                  {"uid": "p1", "kind": "Project", "props": {"name": "Orbit"}}],
        "edges": [{"type": "WORKS_IN", "src": "self", "dst": "c1", "props": {}},
                  {"type": "IN", "src": "p1", "dst": "c1", "props": {}}]}


def _ratify(i, uid, kind="Rule", value="31", aid="a1", rel=None):
    return {"candidate_id": i, "project": "p1",
            "node": {"uid": uid, "kind": kind, "name": f"n{i}", "statement": f"s{i}", "value": value},
            "relations": rel or [], "evidence": [{"aid": aid, "quote": f"q{i}", "locator": ""}],
            "provenance": "extracted", "extractor_version": "v1"}


@pytest.fixture
def env(tmp_path):
    store = Store(tmp_path / "o.db")
    g = GoldGraph(tmp_path / "gold").open()
    yield store, g, tmp_path
    g.close()
    store.close()


def test_ratify_projects_node_part_of_and_evidence(env):
    store, g, _ = env
    store.append_event("seed", SEED)
    store.append_event("bind", {"project": "p1", "artefacts": [{"aid": "a1", "path": "x.md", "title": "X"}]})
    seq = store.append_event("ratify", _ratify(1, "r1"))
    assert projector.catch_up(store, g) == 3
    n = g.node("r1")
    assert n["kind"] == "Rule" and n["ratification_id"] == seq and n["provenance"] == "extracted"
    edges = g.snapshot()["edges"]
    assert {"src": "r1", "type": "PART_OF", "dst": "p1", "quote": None, "locator": None} in edges
    assert any(e["type"] == "EVIDENCED_BY" and e["dst"] == "a1" and e["quote"] == "q1" for e in edges)
    assert g.get_meta() == seq
    assert projector.catch_up(store, g) == 0


def test_revert_and_relabel(env):
    store, g, _ = env
    store.append_event("seed", SEED)
    store.append_event("ratify", _ratify(1, "r1"))
    store.append_event("relabel", {"uid": "p1", "name": "Orbit Programme"})
    store.append_event("revert", {"uid": "r1"})
    projector.catch_up(store, g)
    assert g.node("r1") is None
    assert g.node("p1")["name"] == "Orbit Programme"


def _random_log(store, rng):
    store.append_event("seed", SEED)
    uids: list[str] = []
    for i in range(1, 40):
        roll = rng.random()
        if rng.random() < 0.1:
            arts = [f"a{n}" for n in range(1, 6) if rng.random() < 0.4]
            store.append_event("scope", {
                "project": "p1", "topic_uid": f"t{rng.randint(1, 3)}", "name": "claims triage",
                "decision": rng.choice(["in", "out"]),
                "artefacts": [{"aid": a, "path": f"{a}.md", "title": a.upper()} for a in arts],
                "excluded": [f"a{n}" for n in range(1, 6) if rng.random() < 0.3]})
        elif roll < 0.15:
            store.append_event("bind", {"project": "p1", "artefacts": [
                {"aid": f"a{rng.randint(1, 5)}", "path": f"n{i}.md", "title": f"T{i}"}]})
        elif roll < 0.65 or not uids:
            uid = f"u{rng.randint(1, 12)}"
            rel = [{"type": "DEPENDS_ON", "target_uid": rng.choice(uids)}] if uids and rng.random() < 0.4 else []
            store.append_event("ratify", _ratify(i, uid, kind=rng.choice(["Rule", "Concept", "Decision"]),
                                                 value=str(rng.randint(1, 60)), aid=f"a{rng.randint(1, 5)}", rel=rel))
            uids.append(uid)
        elif roll < 0.8:
            store.append_event("revert", {"uid": rng.choice(uids)})
        elif roll < 0.9:
            store.append_event("relabel", {"uid": rng.choice(uids + ["p1"]), "name": f"L{i}"})
        else:
            store.append_event("reject", {"candidate_id": i})


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_rebuild_equals_incremental(tmp_path, seed):
    """The key invariant: replaying the log from scratch equals applying it event by event."""
    store = Store(tmp_path / "o.db")
    _random_log(store, random.Random(seed))
    inc = GoldGraph(tmp_path / "inc").open()
    for ev in store.events():          # one event at a time, reopening midway
        projector.apply(inc, ev)
        if ev.seq == 20:
            inc.close()
            inc = GoldGraph(tmp_path / "inc").open()
    full = GoldGraph(tmp_path / "full").open()
    projector.rebuild(store, full)
    assert inc.snapshot() == full.snapshot()
    assert projector.rebuild(store, full) == store.head()   # rebuild is repeatable
    assert inc.snapshot() == full.snapshot()
    inc.close()
    full.close()
    store.close()


def _scope(decision, artefacts, excluded=(), topic="t1"):
    return {"project": "p1", "topic_uid": topic, "name": "claims triage", "decision": decision,
            "artefacts": artefacts, "excluded": list(excluded)}


def test_scope_in_binds_notes_and_links_topic(env):
    store, g, _ = env
    store.append_event("seed", SEED)
    store.append_event("scope", _scope("in", [{"aid": "a1", "path": "x.md", "title": "X"}]))
    projector.catch_up(store, g)
    edges = {(e["src"], e["type"], e["dst"]) for e in g.snapshot()["edges"]}
    assert {("t1", "IN_SCOPE", "p1"), ("a1", "ABOUT", "p1"), ("a1", "HAS_TOPIC", "t1")} <= edges
    assert g.node("t1")["kind"] == "Topic" and g.node("t1")["name"] == "claims triage"


def test_scope_out_removes_previously_bound_about_edges(env):
    store, g, _ = env
    store.append_event("seed", SEED)
    store.append_event("bind", {"project": "p1", "artefacts": [{"aid": "a1", "path": "x.md", "title": "X"}]})
    store.append_event("scope", _scope("out", [], excluded=["a1"]))
    projector.catch_up(store, g)
    edges = {(e["src"], e["type"], e["dst"]) for e in g.snapshot()["edges"]}
    assert ("t1", "OUT_OF_SCOPE", "p1") in edges
    assert ("a1", "ABOUT", "p1") not in edges
