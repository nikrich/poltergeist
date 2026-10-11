import pytest

from ghostbrain.api.repo import chat_store, projects


@pytest.fixture
def proj(tmp_vault):
    return projects.create_project("personal", "Site Rebuild")


@pytest.fixture
def conv(client, auth_headers, tmp_chats_dir):
    c = client.post("/v1/chat", headers=auth_headers).json()
    chat_store.append_user_message(chat_store.get(c["id"]), "hello")
    return c


def test_tree_route_not_shadowed(client, auth_headers, tmp_chats_dir, tmp_vault):
    r = client.get("/v1/chat/tree", headers=auth_headers)
    assert r.status_code == 200
    assert set(r.json()) == {"unfiled", "scopes"}


def test_folder_crud(client, auth_headers, tmp_chats_dir, proj):
    ref = {"context": "personal", "project": proj["slug"], "path": "plans"}
    assert client.post("/v1/chat/folders", headers=auth_headers, json=ref).status_code == 200
    assert client.post("/v1/chat/folders", headers=auth_headers, json=ref).status_code == 409
    r = client.patch("/v1/chat/folders", headers=auth_headers,
                     json={"from": ref, "to": {**ref, "path": "renamed"}})
    assert r.status_code == 200 and r.json()["path"] == "renamed"
    r = client.delete("/v1/chat/folders", headers=auth_headers,
                      params={"context": "personal", "project": proj["slug"], "path": "renamed"})
    assert r.status_code == 200 and r.json() == {"deleted": True}


def test_folder_errors(client, auth_headers, tmp_chats_dir, tmp_vault):
    bad = {"context": "nope", "project": None, "path": "x"}
    assert client.post("/v1/chat/folders", headers=auth_headers, json=bad).status_code == 422
    trav = {"context": "personal", "project": None, "path": "../x"}
    assert client.post("/v1/chat/folders", headers=auth_headers, json=trav).status_code == 422
    r = client.delete("/v1/chat/folders", headers=auth_headers, params={"context": "personal", "path": "never"})
    assert r.status_code == 404


def test_patch_moves_into_folder(client, auth_headers, conv, proj):
    r = client.patch(f"/v1/chat/{conv['id']}", headers=auth_headers,
                     json={"context": "personal", "project": proj["slug"], "folder": "plans"})
    assert r.status_code == 200
    body = r.json()
    assert (body["context"], body["project"], body["folder"]) == ("personal", proj["slug"], "plans")
    assert body["auto_filed"] == "done"
    tree = client.get("/v1/chat/tree", headers=auth_headers).json()
    scope = next(s for s in tree["scopes"] if s["project"] == proj["slug"])
    assert scope["folders"][0]["chats"][0]["id"] == conv["id"]


def test_patch_context_null_unfiles(client, auth_headers, conv, proj):
    client.patch(f"/v1/chat/{conv['id']}", headers=auth_headers, json={"context": "personal"})
    r = client.patch(f"/v1/chat/{conv['id']}", headers=auth_headers, json={"context": None})
    assert r.status_code == 200 and r.json()["context"] is None


def test_patch_folder_without_context_422(client, auth_headers, conv):
    r = client.patch(f"/v1/chat/{conv['id']}", headers=auth_headers, json={"folder": "x"})
    assert r.status_code == 422


def test_patch_unknown_context_422(client, auth_headers, conv):
    r = client.patch(f"/v1/chat/{conv['id']}", headers=auth_headers, json={"context": "nope"})
    assert r.status_code == 422


def test_patch_missing_chat_404(client, auth_headers, tmp_chats_dir, tmp_vault):
    r = client.patch("/v1/chat/deadbeef", headers=auth_headers, json={"context": None})
    assert r.status_code == 404
