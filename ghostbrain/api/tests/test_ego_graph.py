"""Ego graph: BFS over the link index around one focus page."""
from __future__ import annotations

from pathlib import Path

import pytest

from ghostbrain.api.repo.ego_graph import EGO_NODE_CAP, FocusNotFound, ego_graph
from ghostbrain.api.repo.linking import InvalidLinkPath
from ghostbrain.vault_index.links import LinkIndex

A = "20-contexts/work/a.md"
B = "20-contexts/work/b.md"
C = "20-contexts/work/c.md"


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _index(root: Path) -> LinkIndex:
    # Long interval: ensure_fresh() serves the refreshed data without a background rescan.
    idx = LinkIndex(root, refresh_interval=3600)
    idx.refresh()
    return idx


def _graph(root: Path, focus: str, depth: int = 2, **kw) -> dict:
    return ego_graph(focus, depth, index=_index(root), **kw)


def _hops(graph: dict) -> dict[str, int]:
    return {n["path"]: n["hop"] for n in graph["nodes"]}


def test_depth_controls_how_many_hops_are_walked(tmp_path: Path):
    _write(tmp_path, A, "[[20-contexts/work/b]]")
    _write(tmp_path, B, "[[20-contexts/work/c]]")
    _write(tmp_path, C, "c")
    _write(tmp_path, "20-contexts/work/d.md", "[[20-contexts/work/a]]")  # a backlink is a neighbour too
    g1 = _graph(tmp_path, "20-contexts/work/a", depth=1)
    assert g1["focus"] == A
    assert _hops(g1) == {A: 0, B: 1, "20-contexts/work/d.md": 1}
    g2 = _graph(tmp_path, "20-contexts/work/a", depth=2)
    assert _hops(g2) == {A: 0, B: 1, "20-contexts/work/d.md": 1, C: 2}
    assert (g2["truncated"], g2["indexing"], g2["depth"]) == (False, False, 2)
    assert _graph(tmp_path, "20-contexts/work/a", depth=9)["depth"] == 3


def test_ghosts_are_grey_leaves(tmp_path: Path):
    _write(tmp_path, A, "[[20-contexts/work/missing]] and [[Someday Idea]]")
    _write(tmp_path, "20-contexts/work/e.md", "[[20-contexts/work/missing]]")
    g = _graph(tmp_path, "20-contexts/work/a", depth=2)
    nodes = {n["path"]: n for n in g["nodes"]}
    assert nodes["20-contexts/work/missing.md"] == {
        "path": "20-contexts/work/missing.md", "title": "missing", "context": "",
        "kind": "note", "degree": 2, "ghost": True, "hop": 1,
    }
    assert nodes["someday idea.md"]["title"] == "Someday Idea"
    assert nodes["someday idea.md"]["ghost"] is True
    assert "20-contexts/work/e.md" not in nodes  # a ghost is not expanded


def test_a_ghost_can_be_the_focus(tmp_path: Path):
    _write(tmp_path, A, "[[20-contexts/work/missing]] and [[Someday Idea]]")
    _write(tmp_path, "20-contexts/work/e.md", "[[20-contexts/work/missing]]")
    g = _graph(tmp_path, "Someday Idea", depth=1)
    assert g["focus"] == "someday idea.md"
    assert _hops(g) == {"someday idea.md": 0, A: 1}
    assert g["nodes"][0]["ghost"] is True
    g2 = _graph(tmp_path, "20-contexts/work/missing", depth=1)
    assert _hops(g2) == {"20-contexts/work/missing.md": 0, A: 1, "20-contexts/work/e.md": 1}


def test_a_ghost_focused_by_its_link_key_keeps_its_written_title(tmp_path: Path):
    # The UI recentres with node.path, which for a ghost is the lower-cased link key.
    _write(tmp_path, A, "[[Someday Idea]]")
    g = _graph(tmp_path, "someday idea.md", depth=1)
    assert g["focus"] == "someday idea.md"
    assert g["nodes"][0]["title"] == "Someday Idea"


def test_unknown_focus_and_bad_paths_raise(tmp_path: Path):
    _write(tmp_path, A, "a")
    with pytest.raises(FocusNotFound):
        _graph(tmp_path, "20-contexts/work/nope")
    with pytest.raises(InvalidLinkPath):
        _graph(tmp_path, "../outside")


def test_edges_are_induced_deduped_and_keep_the_strongest_link(tmp_path: Path):
    _write(tmp_path, A, "---\nrelated:\n- '[[20-contexts/work/b]]'\n---\n[[20-contexts/work/b]] [[20-contexts/work/c]]")
    _write(tmp_path, B, "[[20-contexts/work/c]]")
    _write(tmp_path, C, "c")
    g = _graph(tmp_path, "20-contexts/work/a", depth=1)
    assert g["edges"] == [
        {"source": A, "target": B, "kind": "related", "weight": 0.7},
        {"source": A, "target": C, "kind": "wikilink", "weight": 0.5},
        {"source": B, "target": C, "kind": "wikilink", "weight": 0.5},
    ]


def test_nodes_carry_title_context_kind_and_degree(tmp_path: Path):
    _write(tmp_path, "30-cross-context/people/alex.md", "---\ntitle: Alex\n---\n")
    _write(tmp_path, A, "---\ntitle: Alpha\ntype: artifact\nartifactType: decision\n---\n"
                        "ask [[30-cross-context/people/alex|@Alex]]")
    g = _graph(tmp_path, "20-contexts/work/a", depth=1)
    assert g["nodes"] == [
        {"path": A, "title": "Alpha", "context": "work", "kind": "decision",
         "degree": 1, "ghost": False, "hop": 0},
        {"path": "30-cross-context/people/alex.md", "title": "Alex", "context": "",
         "kind": "person", "degree": 1, "ghost": False, "hop": 1},
    ]


def test_cap_keeps_the_strongest_links_first(tmp_path: Path):
    _write(tmp_path, A, "---\nrelated:\n- '[[20-contexts/work/b]]'\n---\n[[20-contexts/work/c]]")
    _write(tmp_path, B, "b")
    _write(tmp_path, C, "c")
    g = _graph(tmp_path, "20-contexts/work/a", depth=1, cap=2)
    assert _hops(g) == {A: 0, B: 1}
    assert g["truncated"] is True


def test_hub_with_thousands_of_backlinks_is_capped(tmp_path: Path):
    hub = "20-contexts/work/hub.md"
    _write(tmp_path, hub, "hub")
    for i in range(2000):
        _write(tmp_path, f"20-contexts/work/n{i:04d}.md", "[[20-contexts/work/hub]]")
    g = _graph(tmp_path, "20-contexts/work/hub", depth=3)
    assert len(g["nodes"]) == EGO_NODE_CAP
    assert g["truncated"] is True
    assert g["nodes"][0]["path"] == hub
    assert {n["hop"] for n in g["nodes"][1:]} == {1}
    assert [n["path"] for n in g["nodes"][1:3]] == ["20-contexts/work/n0000.md", "20-contexts/work/n0001.md"]
    assert g["nodes"][0]["degree"] == 2000  # vault-wide link count, not the capped subgraph's
    assert len(g["edges"]) == EGO_NODE_CAP - 1


def test_unindexed_existing_target_is_a_real_leaf(tmp_path: Path):
    _write(tmp_path, A, "[[90-meta/routing]]")
    _write(tmp_path, "90-meta/routing.md", "real file outside the indexed roots")
    nodes = {n["path"]: n for n in _graph(tmp_path, "20-contexts/work/a", depth=2)["nodes"]}
    assert nodes["90-meta/routing.md"] == {
        "path": "90-meta/routing.md", "title": "routing", "context": "",
        "kind": "note", "degree": 1, "ghost": False, "hop": 1,
    }


def test_reports_indexing_while_cold(tmp_path: Path, monkeypatch):
    idx = LinkIndex(tmp_path)
    monkeypatch.setattr(idx, "ensure_fresh", lambda wait=0.25: False)
    assert ego_graph("20-contexts/work/a", 2, index=idx) == {
        "focus": A, "depth": 2, "nodes": [], "edges": [], "truncated": False, "indexing": True,
    }
