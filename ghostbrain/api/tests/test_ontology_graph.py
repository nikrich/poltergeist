import pytest

pytest.importorskip("arcadedb_embedded")

from ghostbrain.ontology.graph import GoldGraph  # noqa: E402


@pytest.fixture
def graph(tmp_path):
    g = GoldGraph(tmp_path / "gold").open()
    yield g
    g.close()


def _seed(g):
    with g.transaction():
        g.upsert_node("p1", "Project", {"name": "Orbit"})
        g.upsert_node("r1", "Rule", {"name": "lapse day", "value": "31", "statement": "Lapse on day 31."})
        g.upsert_node("a1", "Artefact", {"name": "Spec", "note_path": "20-contexts/work/spec.md"})
        assert g.upsert_edge("PART_OF", "r1", "p1", {})
        assert g.upsert_edge("EVIDENCED_BY", "r1", "a1", {"quote": "day 31"})


def test_upsert_is_idempotent_and_updates(graph):
    _seed(graph)
    with graph.transaction():
        graph.upsert_node("p1", "Project", {"name": "Orbit v2"})
        graph.upsert_edge("PART_OF", "r1", "p1", {})
    snap = graph.snapshot()
    assert [n["uid"] for n in snap["nodes"]].count("p1") == 1
    assert graph.node("p1")["name"] == "Orbit v2"
    assert len([e for e in snap["edges"] if e["type"] == "PART_OF"]) == 1


def test_kind_change_keeps_single_node(graph):
    _seed(graph)
    with graph.transaction():
        graph.upsert_node("r1", "Concept", {"name": "lapse"})
    assert [n["uid"] for n in graph.snapshot()["nodes"]].count("r1") == 1


def test_edge_to_missing_node_returns_false(graph):
    _seed(graph)
    with graph.transaction():
        assert graph.upsert_edge("PART_OF", "nope", "p1", {}) is False


def test_neighbourhood_hops_and_cap(graph):
    _seed(graph)
    nodes, edges, truncated = graph.neighbourhood("p1", depth=2)
    hops = {n["uid"]: n["hop"] for n in nodes}
    assert hops == {"p1": 0, "r1": 1, "a1": 2}
    assert {"src": "r1", "type": "EVIDENCED_BY", "dst": "a1"} in edges
    assert truncated is False
    nodes, _, truncated = graph.neighbourhood("p1", depth=2, cap=2)
    assert len(nodes) == 2 and truncated is True


def test_domain_nodes_and_export(graph):
    _seed(graph)
    [n] = graph.domain_nodes("p1")
    assert (n["uid"], n["kind"], n["value"]) == ("r1", "Rule", "31")
    [x] = graph.project_export("p1")
    assert x["evidence"] == [{"note_path": "20-contexts/work/spec.md", "title": "Spec", "quote": "day 31"}]


def test_meta_and_clear_and_delete(graph):
    _seed(graph)
    with graph.transaction():
        graph.set_meta(7)
    assert graph.get_meta() == 7
    with graph.transaction():
        graph.delete_node("a1")
    assert graph.node("a1") is None
    with graph.transaction():
        graph.clear()
    assert graph.snapshot() == {"nodes": [], "edges": []}
    assert graph.get_meta() == 0


def test_rejects_unknown_kind_and_bad_prop(graph):
    with pytest.raises(ValueError):
        with graph.transaction():
            graph.upsert_node("x", "Bogus", {})
    with pytest.raises(ValueError):
        with graph.transaction():
            graph.upsert_node("x", "Rule", {"Bad-Name": 1})


def test_reopen_persists(tmp_path):
    g = GoldGraph(tmp_path / "gold").open()
    _seed(g)
    g.close()
    g2 = GoldGraph(tmp_path / "gold").open()
    assert g2.node("r1")["value"] == "31"
    g2.close()


def test_neighbourhood_cap_admits_domain_nodes_first(graph):
    with graph.transaction():
        graph.upsert_node("p1", "Project", {"name": "Proj"})
        for i in range(350):
            graph.upsert_node(f"a{i:03d}", "Artefact", {"name": f"note {i}"})
            graph.upsert_edge("ABOUT", f"a{i:03d}", "p1", {})
        for i in range(10):
            graph.upsert_node(f"z-rule{i}", "Rule", {"name": f"rule {i}"})
            graph.upsert_edge("PART_OF", f"z-rule{i}", "p1", {})
            # Evidence sits at the end of the uid order, so only preference admits it.
            graph.upsert_edge("EVIDENCED_BY", f"z-rule{i}", f"a{349 - i:03d}", {"quote": "q"})
    for depth in (1, 2):
        nodes, edges, truncated = graph.neighbourhood("p1", depth=depth)
        uids = {n["uid"] for n in nodes}
        assert len(nodes) == 300 and truncated is True
        assert {f"z-rule{i}" for i in range(10)} <= uids
        assert {f"a{349 - i:03d}" for i in range(10)} <= uids
        assert {"src": "z-rule0", "type": "EVIDENCED_BY", "dst": "a349"} in edges
    assert graph.neighbourhood("p1", depth=2) == graph.neighbourhood("p1", depth=2)


def test_schema_failure_closes_db_and_raises_unavailable(tmp_path, monkeypatch):
    from ghostbrain.ontology.graph import GraphUnavailable

    def boom(self, arc):
        raise RuntimeError("schema exploded")

    monkeypatch.setattr(GoldGraph, "_ensure_schema", boom)
    g = GoldGraph(tmp_path / "gold")
    with pytest.raises(GraphUnavailable, match="schema exploded"):
        g.open()
    assert g._db is None
    monkeypatch.undo()
    GoldGraph(tmp_path / "gold").open().close()  # the lock was released


def test_delete_edge_removes_only_that_edge(graph):
    _seed(graph)
    with graph.transaction():
        graph.delete_edge("EVIDENCED_BY", "r1", "a1")
        graph.delete_edge("EVIDENCED_BY", "r1", "nope")   # missing: no-op
    types = [e["type"] for e in graph.snapshot()["edges"]]
    assert "EVIDENCED_BY" not in types and "PART_OF" in types
    with pytest.raises(ValueError):
        with graph.transaction():
            graph.delete_edge("BOGUS", "r1", "a1")
