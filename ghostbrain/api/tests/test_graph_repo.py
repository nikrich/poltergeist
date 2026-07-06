from pathlib import Path

from ghostbrain.api.repo.graph import build_graph


def _note(vault: Path, rel: str, body: str = "", **meta) -> None:
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    fm = "".join(f"{k}: {v}\n" for k, v in meta.items())
    p.write_text(f"---\n{fm}---\n{body}", encoding="utf-8")


def test_build_graph_nodes_edges_regions(tmp_vault: Path, monkeypatch, tmp_path):
    monkeypatch.setenv("GHOSTBRAIN_SEMANTIC_INDEX_DIR", str(tmp_path / "sem"))
    _note(tmp_vault, "20-contexts/sanlam/a.md", title="A")
    _note(tmp_vault, "20-contexts/sanlam/b.md", title="B")
    # a relates to b (semantic edge)
    (tmp_vault / "20-contexts/sanlam/a.md").write_text(
        "---\ntitle: A\nrelated:\n- '[[20-contexts/sanlam/b]]'\n---\nbody", encoding="utf-8")

    graph = build_graph()
    paths = {n["path"] for n in graph["nodes"]}
    assert paths == {"20-contexts/sanlam/a.md", "20-contexts/sanlam/b.md"}
    assert all("x" in n and "y" in n for n in graph["nodes"])
    edges = graph["edges"]
    assert any(e["kind"] == "related"
               and {e["source"], e["target"]} == {"20-contexts/sanlam/a.md", "20-contexts/sanlam/b.md"}
               for e in edges)
    regions = {r["id"]: r for r in graph["regions"]}
    assert regions["sanlam"]["count"] == 2
    assert regions["sanlam"]["color"] == "#38BDF8"


def test_build_graph_empty_vault(tmp_vault: Path, monkeypatch, tmp_path):
    monkeypatch.setenv("GHOSTBRAIN_SEMANTIC_INDEX_DIR", str(tmp_path / "sem"))
    graph = build_graph()
    assert graph == {"nodes": [], "edges": [], "regions": []}


def test_wikilink_parent_edge(tmp_vault: Path, monkeypatch, tmp_path):
    monkeypatch.setenv("GHOSTBRAIN_SEMANTIC_INDEX_DIR", str(tmp_path / "sem"))
    _note(tmp_vault, "20-contexts/sanlam/parent.md", title="P")
    (tmp_vault / "20-contexts/sanlam/child.md").write_text(
        "---\ntitle: C\nparent: '[[20-contexts/sanlam/parent]]'\n---\nbody", encoding="utf-8")
    graph = build_graph()
    assert any(e["kind"] == "wikilink" for e in graph["edges"])
