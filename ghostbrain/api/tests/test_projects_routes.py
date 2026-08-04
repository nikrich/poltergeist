"""/v1/projects CRUD routes."""
from __future__ import annotations


def test_create_list_roundtrip(client, auth_headers):
    created = client.post(
        "/v1/projects",
        json={"context": "consulting", "name": "Poltergeist", "description": "brain"},
        headers=auth_headers,
    )
    assert created.status_code == 200
    body = created.json()
    assert body["id"] == "consulting/poltergeist"
    listed = client.get("/v1/projects", headers=auth_headers).json()
    assert [p["id"] for p in listed] == ["consulting/poltergeist"]


def test_create_validation(client, auth_headers):
    r = client.post("/v1/projects", json={"context": "nope", "name": "X"}, headers=auth_headers)
    assert r.status_code == 422
    client.post("/v1/projects", json={"context": "personal", "name": "Lab"}, headers=auth_headers)
    dup = client.post("/v1/projects", json={"context": "personal", "name": "lab"}, headers=auth_headers)
    assert dup.status_code == 409


def test_patch_edit_and_archive(client, auth_headers):
    client.post("/v1/projects", json={"context": "work", "name": "Rockets"}, headers=auth_headers)
    r = client.patch(
        "/v1/projects/work/rockets",
        json={"description": "the big one", "archived": True},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["archived"] is True
    assert client.get("/v1/projects", headers=auth_headers).json() == []
    full = client.get("/v1/projects?includeArchived=true", headers=auth_headers).json()
    assert full[0]["description"] == "the big one"
    missing = client.patch("/v1/projects/work/none", json={"name": "x"}, headers=auth_headers)
    assert missing.status_code == 404
