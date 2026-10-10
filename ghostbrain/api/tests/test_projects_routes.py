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


import pytest  # noqa: E402

from ghostbrain.api.repo import projects as projects_repo  # noqa: E402
from ghostbrain.vault_write import WriteConflict  # noqa: E402


@pytest.fixture
def rename_sandbox(tmp_chats_dir):
    """Rename touches chats: keep them in a temp dir (state/vault come from `client`)."""
    return tmp_chats_dir


def test_patch_renames_slug_and_maps_errors(client, auth_headers, rename_sandbox):
    H = auth_headers
    client.post("/v1/projects", json={"context": "work", "name": "Paymnets"}, headers=H)
    client.post("/v1/projects", json={"context": "work", "name": "Claims"}, headers=H)
    r = client.patch("/v1/projects/work/paymnets", json={"name": "Payments"}, headers=H)
    assert r.status_code == 200
    assert r.json()["slug"] == "payments" and r.json()["id"] == "work/payments"
    assert client.patch("/v1/projects/work/payments", json={"name": "Claims"}, headers=H).status_code == 409
    assert client.patch("/v1/projects/work/ghost", json={"name": "X"}, headers=H).status_code == 404
    assert client.patch("/v1/projects/work/payments", json={"name": "!!!"}, headers=H).status_code == 422
    r = client.patch("/v1/projects/work/payments", json={"archived": True}, headers=H)
    assert r.json()["archived"] is True
    r = client.patch("/v1/projects/work/payments", json={"archived": False}, headers=H)
    assert r.json()["archived"] is False


def test_patch_busy_maps_to_409(client, auth_headers, rename_sandbox, monkeypatch):
    H = auth_headers
    client.post("/v1/projects", json={"context": "work", "name": "Alpha"}, headers=H)

    def busy(_old_dir):
        raise projects_repo.ProjectBusy("doc x is still being indexed or summarised")

    monkeypatch.setattr(projects_repo, "_check_not_busy", busy)
    r = client.patch("/v1/projects/work/alpha", json={"name": "Beta"}, headers=H)
    assert r.status_code == 409
    assert r.json()["detail"] == "project busy: a doc is still being indexed or summarised"


def test_patch_write_conflict_maps_to_409(client, auth_headers, rename_sandbox, monkeypatch):
    H = auth_headers
    client.post("/v1/projects", json={"context": "work", "name": "Alpha"}, headers=H)

    def conflict(*a, **k):
        raise WriteConflict("changed")

    monkeypatch.setattr(projects_repo, "rename_project", conflict)
    r = client.patch("/v1/projects/work/alpha", json={"name": "Beta"}, headers=H)
    assert r.status_code == 409
    assert r.json()["detail"] == "a note in this project changed during the rename — try again"


@pytest.mark.parametrize(
    "exc",
    [
        lambda: __import__("ghostbrain.vault_write", fromlist=["FileMissing"]).FileMissing("x.md"),
        lambda: FileNotFoundError(2, "No such file or directory", "x.md"),
    ],
    ids=["FileMissing", "FileNotFoundError"],
)
def test_patch_missing_file_mid_rename_maps_to_409(client, auth_headers, rename_sandbox, monkeypatch, exc):
    H = auth_headers
    client.post("/v1/projects", json={"context": "work", "name": "Alpha"}, headers=H)

    def vanished(*a, **k):
        raise exc()

    monkeypatch.setattr(projects_repo, "rename_project", vanished)
    r = client.patch("/v1/projects/work/alpha", json={"name": "Beta"}, headers=H)
    assert r.status_code == 409
    assert r.json()["detail"] == "a note in this project changed during the rename — try again"


def test_patch_file_deleted_mid_rename_rolls_back_and_409s(client, auth_headers, rename_sandbox, monkeypatch):
    """A file deleted between the folder scan and its move (FileNotFoundError
    from the plain move): real rollback, then 409."""
    from ghostbrain import vault_write
    from ghostbrain.paths import vault_path

    H = auth_headers
    client.post("/v1/projects", json={"context": "work", "name": "Alpha"}, headers=H)
    old = vault_path() / "20-contexts/work/projects/alpha"
    a_bytes = b"---\nproject: alpha\n---\n\na\n"
    (old / "a.md").write_bytes(a_bytes)
    (old / "z.pdf").write_bytes(b"%PDF")
    real_write = vault_write.write

    def delete_pdf_meanwhile(rel, **kw):
        if rel.endswith("alpha/a.md") and kw.get("op") == "move":
            (old / "z.pdf").unlink()
        return real_write(rel, **kw)

    monkeypatch.setattr(vault_write, "write", delete_pdf_meanwhile)
    r = client.patch("/v1/projects/work/alpha", json={"name": "Beta"}, headers=H)
    assert r.status_code == 409
    assert r.json()["detail"] == "a note in this project changed during the rename — try again"
    assert (old / "a.md").read_bytes() == a_bytes
    assert not (vault_path() / "20-contexts/work/projects/beta").exists()
    assert projects_repo.get_project("work", "alpha") is not None


def test_patch_malformed_note_maps_to_409_naming_it(client, auth_headers, rename_sandbox, monkeypatch):
    H = auth_headers
    client.post("/v1/projects", json={"context": "work", "name": "Alpha"}, headers=H)

    def malformed(*a, **k):
        raise projects_repo.MalformedProjectNote("20-contexts/work/projects/alpha/bad.md")

    monkeypatch.setattr(projects_repo, "rename_project", malformed)
    r = client.patch("/v1/projects/work/alpha", json={"name": "Beta"}, headers=H)
    assert r.status_code == 409
    assert r.json()["detail"] == (
        "can't rename: 20-contexts/work/projects/alpha/bad.md has malformed frontmatter"
    )
