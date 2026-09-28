"""POST/DELETE /v1/vault/contexts: add and archive contexts via the API."""
from __future__ import annotations


def test_get_includes_archived(client, auth_headers):
    body = client.get("/v1/vault/contexts", headers=auth_headers).json()
    assert body == {"contexts": ["work", "consulting", "side-project", "personal"], "archived": []}


def test_post_adds_and_delete_archives(client, auth_headers):
    r = client.post("/v1/vault/contexts", json={"name": "agencyx"}, headers=auth_headers)
    assert r.status_code == 201 and "agencyx" in r.json()["contexts"]
    r = client.delete("/v1/vault/contexts/agencyx", headers=auth_headers)
    assert r.status_code == 200
    assert "agencyx" not in r.json()["contexts"] and r.json()["archived"] == ["agencyx"]


def test_post_invalid_is_422(client, auth_headers):
    r = client.post("/v1/vault/contexts", json={"name": "Bad Name"}, headers=auth_headers)
    assert r.status_code == 422 and r.json()["detail"]


def test_delete_unknown_is_422(client, auth_headers):
    assert client.delete("/v1/vault/contexts/nope", headers=auth_headers).status_code == 422
