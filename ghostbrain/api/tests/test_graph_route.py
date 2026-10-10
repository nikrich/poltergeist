from pathlib import Path

from fastapi.testclient import TestClient

from ghostbrain.vault_index.links import get_link_index


def test_graph_endpoint_returns_shape(client: TestClient, auth_headers, tmp_vault: Path, monkeypatch, tmp_path):
    monkeypatch.setenv("GHOSTBRAIN_SEMANTIC_INDEX_DIR", str(tmp_path / "sem"))
    d = tmp_vault / "20-contexts" / "work"
    d.mkdir(parents=True)
    (d / "a.md").write_text("---\ntitle: A\n---\nbody", encoding="utf-8")
    resp = client.get("/v1/vault/graph", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert {"nodes", "edges", "regions"} <= data.keys()
    assert data["nodes"][0]["path"] == "20-contexts/work/a.md"


def test_graph_endpoint_empty(client: TestClient, auth_headers, monkeypatch, tmp_path):
    monkeypatch.setenv("GHOSTBRAIN_SEMANTIC_INDEX_DIR", str(tmp_path / "sem"))
    resp = client.get("/v1/vault/graph", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"nodes": [], "edges": [], "regions": []}


def _ego(client: TestClient, auth_headers, **params):
    get_link_index().refresh()
    return client.get("/v1/vault/graph", params=params, headers=auth_headers)


def test_graph_with_focus_returns_the_ego_graph(client: TestClient, auth_headers, tmp_vault: Path):
    d = tmp_vault / "20-contexts" / "work"
    d.mkdir(parents=True)
    (d / "a.md").write_text("[[20-contexts/work/b]] [[Later]]", encoding="utf-8")
    (d / "b.md").write_text("b", encoding="utf-8")
    resp = _ego(client, auth_headers, focus="20-contexts/work/a", depth=1)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert (data["focus"], data["depth"], data["truncated"], data["indexing"]) == (
        "20-contexts/work/a.md", 1, False, False,
    )
    assert {n["path"]: n["ghost"] for n in data["nodes"]} == {
        "20-contexts/work/a.md": False, "20-contexts/work/b.md": False, "later.md": True,
    }
    assert "regions" not in data


def test_graph_focus_errors(client: TestClient, auth_headers, tmp_vault: Path):
    (tmp_vault / "20-contexts" / "work").mkdir(parents=True)
    (tmp_vault / "20-contexts" / "work" / "a.md").write_text("a", encoding="utf-8")
    assert _ego(client, auth_headers, focus="20-contexts/work/nope").status_code == 404
    assert _ego(client, auth_headers, focus="../outside").status_code == 400
    assert _ego(client, auth_headers, focus="20-contexts/work/a", depth=0).status_code == 422
    assert _ego(client, auth_headers, focus="20-contexts/work/a", depth=4).status_code == 422


def test_graph_without_focus_nodes_carry_kind(client: TestClient, auth_headers, tmp_vault: Path, monkeypatch, tmp_path):
    monkeypatch.setenv("GHOSTBRAIN_SEMANTIC_INDEX_DIR", str(tmp_path / "sem"))
    d = tmp_vault / "20-contexts" / "work"
    d.mkdir(parents=True)
    (d / "j.md").write_text("---\nsource: manual\n---\njot", encoding="utf-8")
    data = client.get("/v1/vault/graph", headers=auth_headers).json()
    assert [(n["path"], n["kind"]) for n in data["nodes"]] == [("20-contexts/work/j.md", "jot")]
    assert "regions" in data
