"""/v1/library routes: status-code mapping + shapes."""
import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ghostbrain.api.main import create_app
from ghostbrain.api.repo.doc_library import ops
from tests.doc_library_helpers import lib_vault  # noqa: F401

H = {"Authorization": "Bearer t"}


@pytest.fixture
def client(lib_vault: Path, monkeypatch):
    monkeypatch.setattr(ops.attachment_extract, "extract_text", lambda *a: "body text")
    return TestClient(create_app("t"))


def _up(client, name="a.pdf", content=b"%PDF", **kw):
    body = {"context": "work", "project": "payments", "folder": "specs", "name": name,
            "mime": "", "content_b64": base64.b64encode(content).decode(), **kw}
    return client.post("/v1/library/docs", json=body, headers=H)


def test_upload_tree_detail_search(client):
    r = _up(client)
    assert r.status_code == 200
    doc = r.json()
    assert doc["duplicate"] is False and doc["kind"] == "pdf"
    tree = client.get("/v1/library/tree", headers=H).json()
    payments = next(s for s in tree["scopes"] if s["project"] == "payments")
    assert payments["folders"][0]["docs"][0]["doc_id"] == doc["doc_id"]
    detail = client.get(f"/v1/library/docs/{doc['doc_id']}", headers=H).json()
    assert detail["body"].strip() == "body text"
    hits = client.get("/v1/library/search", params={"q": "a"}, headers=H).json()
    assert [h["doc_id"] for h in hits] == [doc["doc_id"]]


def test_patch_move_and_rename(client):
    doc = _up(client).json()
    r = client.patch(f"/v1/library/docs/{doc['doc_id']}", json={"title": "Spec"}, headers=H)
    assert r.json()["original"] == "Spec.pdf"
    r = client.patch(f"/v1/library/docs/{doc['doc_id']}",
                     json={"context": "work", "project": "claims", "folder": "in"}, headers=H)
    assert r.json()["project"] == "claims"
    assert client.patch(f"/v1/library/docs/{doc['doc_id']}", json={}, headers=H).status_code == 422


def test_folder_routes(client):
    assert client.post("/v1/library/folders", json={"context": "work", "path": "a"}, headers=H).status_code == 200
    r = client.patch("/v1/library/folders",
                     json={"from": {"context": "work", "path": "a"}, "to": {"context": "work", "path": "b"}},
                     headers=H)
    assert r.json() == {"context": "work", "project": None, "path": "b"}
    assert client.delete("/v1/library/folders", params={"context": "work", "path": "b"}, headers=H).json() == {"deleted": True}


def test_error_mapping(client):
    assert _up(client, content=b"x" * 20_000_001).status_code == 413
    assert _up(client, folder="../x").status_code == 400
    assert client.post("/v1/library/docs", json={"context": "work", "folder": "", "name": "a",
                       "content_b64": "!!!"}, headers=H).status_code == 400
    assert client.get("/v1/library/docs/ffffffffffff", headers=H).status_code == 404
    _up(client, name="b.pdf", content=b"b", folder="full")
    assert client.delete("/v1/library/folders",
                         params={"context": "work", "project": "payments", "path": "full"},
                         headers=H).status_code == 409
    assert _up(client, project="ghost").status_code == 404
