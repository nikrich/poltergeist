from datetime import datetime, timezone

import pytest

from ghostbrain.api.repo import projects
from ghostbrain.api.repo.notes_manual import write_inbox_jot


@pytest.fixture
def jot(tmp_vault):
    (tmp_vault / "00-inbox" / "raw" / "manual").mkdir(parents=True, exist_ok=True)
    return write_inbox_jot("folder me", captured_at=datetime(2026, 5, 14, 9, tzinfo=timezone.utc))


@pytest.fixture
def proj(tmp_vault):
    return projects.create_project("work", "Atlas")


def test_tree_route(client, auth_headers, jot):
    r = client.get("/v1/notes/tree", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"inbox", "unrouted", "scopes"}
    assert body["inbox"][0]["id"] == jot["id"]
    assert body["inbox"][0]["unknownLocation"] is False


def test_folder_crud(client, auth_headers, proj):
    ref = {"context": "work", "project": proj["slug"], "path": "plans"}
    assert client.post("/v1/notes/folders", headers=auth_headers, json=ref).status_code == 200
    assert client.post("/v1/notes/folders", headers=auth_headers, json=ref).status_code == 409
    r = client.patch("/v1/notes/folders", headers=auth_headers, json={"from": ref, "to": {**ref, "path": "renamed"}})
    assert r.status_code == 200 and r.json()["path"] == "renamed"
    r = client.delete("/v1/notes/folders", headers=auth_headers,
                      params={"context": "work", "project": proj["slug"], "path": "renamed"})
    assert r.status_code == 200 and r.json() == {"deleted": True}


def test_folder_errors(client, auth_headers, tmp_vault):
    assert client.post("/v1/notes/folders", headers=auth_headers,
                       json={"context": "nope", "project": None, "path": "x"}).status_code == 422
    assert client.post("/v1/notes/folders", headers=auth_headers,
                       json={"context": "work", "project": None, "path": "../x"}).status_code == 422
    assert client.delete("/v1/notes/folders", headers=auth_headers,
                         params={"context": "work", "path": "never"}).status_code == 404


def test_move_jot_location(client, auth_headers, jot, proj):
    r = client.patch(f"/v1/notes/{jot['id']}/location", headers=auth_headers,
                     json={"context": "work", "project": proj["slug"], "folder": "plans"})
    assert r.status_code == 200
    tree = client.get("/v1/notes/tree", headers=auth_headers).json()
    scope = next(s for s in tree["scopes"] if s["project"] == proj["slug"])
    assert scope["folders"][0]["jots"][0]["id"] == jot["id"]
    assert scope["folders"][0]["jots"][0]["folder"] == "plans"


def test_move_jot_location_errors(client, auth_headers, jot):
    assert client.patch("/v1/notes/manual-19000101T000000-nope/location", headers=auth_headers,
                        json={"context": "work"}).status_code == 404
    assert client.patch(f"/v1/notes/{jot['id']}/location", headers=auth_headers,
                        json={"context": "nope"}).status_code == 422
