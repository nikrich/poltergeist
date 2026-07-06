from pathlib import Path

from fastapi.testclient import TestClient


def test_graph_endpoint_returns_shape(client: TestClient, auth_headers, tmp_vault: Path, monkeypatch, tmp_path):
    monkeypatch.setenv("GHOSTBRAIN_SEMANTIC_INDEX_DIR", str(tmp_path / "sem"))
    d = tmp_vault / "20-contexts" / "sanlam"
    d.mkdir(parents=True)
    (d / "a.md").write_text("---\ntitle: A\n---\nbody", encoding="utf-8")
    resp = client.get("/v1/vault/graph", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert {"nodes", "edges", "regions"} <= data.keys()
    assert data["nodes"][0]["path"] == "20-contexts/sanlam/a.md"


def test_graph_endpoint_empty(client: TestClient, auth_headers, monkeypatch, tmp_path):
    monkeypatch.setenv("GHOSTBRAIN_SEMANTIC_INDEX_DIR", str(tmp_path / "sem"))
    resp = client.get("/v1/vault/graph", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"nodes": [], "edges": [], "regions": []}
