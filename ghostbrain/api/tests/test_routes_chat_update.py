"""PATCH /v1/chat/{id} — title and project filing (chat project folders)."""
import pytest

from ghostbrain.api.repo import chat_store, projects


@pytest.fixture
def conv(client, auth_headers, tmp_chats_dir):
    return client.post("/v1/chat", headers=auth_headers).json()


@pytest.fixture
def project(tmp_vault):
    return projects.create_project("personal", "Site Rebuild")


def _key(p: dict) -> str:
    return f"{p['context']}/{p['slug']}"


def test_patch_project_files_conversation(client, auth_headers, conv, project):
    r = client.patch(
        f"/v1/chat/{conv['id']}", headers=auth_headers, json={"project": _key(project)}
    )
    assert r.status_code == 200
    assert r.json()["project"] == _key(project)
    assert chat_store.get(conv["id"])["project"] == _key(project)


def test_patch_unknown_project_422(client, auth_headers, conv):
    r = client.patch(
        f"/v1/chat/{conv['id']}", headers=auth_headers, json={"project": "nope/missing"}
    )
    assert r.status_code == 422
    assert "nope/missing" in r.text


def test_patch_malformed_project_422(client, auth_headers, conv):
    r = client.patch(
        f"/v1/chat/{conv['id']}", headers=auth_headers, json={"project": "no-slash"}
    )
    assert r.status_code == 422


def test_patch_null_project_unfiles(client, auth_headers, conv, project):
    client.patch(f"/v1/chat/{conv['id']}", headers=auth_headers, json={"project": _key(project)})
    r = client.patch(f"/v1/chat/{conv['id']}", headers=auth_headers, json={"project": None})
    assert r.status_code == 200
    assert r.json()["project"] is None


def test_patch_title_and_project_together(client, auth_headers, conv, project):
    r = client.patch(
        f"/v1/chat/{conv['id']}",
        headers=auth_headers,
        json={"title": "site chat", "project": _key(project)},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "site chat"
    assert body["project"] == _key(project)


def test_patch_title_only_leaves_project(client, auth_headers, conv, project):
    client.patch(f"/v1/chat/{conv['id']}", headers=auth_headers, json={"project": _key(project)})
    r = client.patch(f"/v1/chat/{conv['id']}", headers=auth_headers, json={"title": "renamed"})
    assert r.json()["project"] == _key(project)


def test_list_summary_carries_project(client, auth_headers, conv, project):
    client.patch(f"/v1/chat/{conv['id']}", headers=auth_headers, json={"project": _key(project)})
    items = client.get("/v1/chat", headers=auth_headers).json()
    assert items[0]["project"] == _key(project)


def test_patch_empty_body_400s(client, auth_headers, conv):
    r = client.patch(f"/v1/chat/{conv['id']}", headers=auth_headers, json={})
    assert r.status_code == 422
