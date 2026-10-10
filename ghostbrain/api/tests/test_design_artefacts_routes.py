"""/v1/design/artefacts* routes."""
from __future__ import annotations

from pathlib import Path

from ghostbrain.design import artefacts

DATA = {
    "version": 1, "title": "Login screen review", "kind": "prototype", "board": False,
    "date": "2026-10-10", "context": "personal", "project": None,
    "design_system": "poltergeist-neutral", "meeting": "Login review",
    "meeting_path": "20-contexts/personal/calendar/transcripts/x.md",
    "ui_rev": 1, "board_rev": 0,
    "revs": [{"rev": 1, "at": "2026-10-10T10:00:00+00:00", "summary": "Login form"}],
    "codebase": None, "wav": "/rec/meeting.wav",
}
PROTO = "20-contexts/personal/prototypes/2026-10-10-login"
WT = "20-contexts/personal/artefacts/2026-10-10-web"


def _artefact(vault: Path, rel: str, **extra) -> Path:
    folder = vault / rel
    folder.mkdir(parents=True)
    artefacts.write(folder, DATA | extra)
    return folder


def _worktree_artefact(vault: Path, tmp_path: Path) -> Path:
    gone = tmp_path / "code" / "web-poltergeist-2026-10-10-web"
    return _artefact(vault, WT, kind="worktree", title="Web", codebase={
        "repo": str(tmp_path / "code" / "web"), "name": "web", "app_dir": str(gone),
        "worktree": str(gone), "branch": "poltergeist/2026-10-10-web", "base": "origin/main",
    })


def test_list_artefacts(client, auth_headers, tmp_vault, tmp_path):
    _artefact(tmp_vault, PROTO)
    _worktree_artefact(tmp_vault, tmp_path)
    r = client.get("/v1/design/artefacts", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert {a["id"] for a in body} == {PROTO, WT}
    proto = next(a for a in body if a["id"] == PROTO)
    assert proto == {
        "id": PROTO, "title": "Login screen review", "kind": "prototype", "board": False,
        "date": "2026-10-10", "context": "personal", "project": None, "meeting": "Login review",
        "meeting_path": "20-contexts/personal/calendar/transcripts/x.md", "ui_rev": 1,
        "board_rev": 0, "codebase": None,
    }
    wt = next(a for a in body if a["id"] == WT)
    assert wt["codebase"]["missing"] is True and wt["codebase"]["branch"] == "poltergeist/2026-10-10-web"


def test_list_empty(client, auth_headers, tmp_vault):
    r = client.get("/v1/design/artefacts", headers=auth_headers)
    assert r.status_code == 200 and r.json() == []


def test_detail(client, auth_headers, tmp_vault):
    folder = _artefact(tmp_vault, PROTO)
    r = client.get("/v1/design/artefact", params={"id": PROTO}, headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["folder"] == str(folder) and body["design_system"] == "poltergeist-neutral"
    assert body["revs"][0]["summary"] == "Login form" and body["board_model"] is None


def test_detail_404_unknown_and_escape(client, auth_headers, tmp_vault):
    for bad in (PROTO, "../../etc", "20-contexts/personal/notes/x"):
        r = client.get("/v1/design/artefact", params={"id": bad}, headers=auth_headers)
        assert r.status_code == 404, bad


def test_remove_worktree(client, auth_headers, tmp_vault, tmp_path, monkeypatch):
    _worktree_artefact(tmp_vault, tmp_path)
    monkeypatch.setattr(artefacts, "remove_worktree", lambda aid: (
        {"removed": True, "branch_kept": True, "reason": "unmerged commits"} if aid == WT else None))
    r = client.post("/v1/design/artefacts/remove-worktree", json={"id": WT}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == {"removed": True, "branch_kept": True, "reason": "unmerged commits"}


def test_remove_worktree_missing_worktree_is_ok(client, auth_headers, tmp_vault, tmp_path, monkeypatch):
    _worktree_artefact(tmp_vault, tmp_path)
    import sys
    import types

    fake = types.ModuleType("ghostbrain.design.worktree")

    class Worktree:
        @classmethod
        def from_dict(cls, d):
            return cls()

    def remove(wt):
        raise RuntimeError("not a git repository")

    fake.Worktree, fake.remove = Worktree, remove
    monkeypatch.setitem(sys.modules, "ghostbrain.design.worktree", fake)
    r = client.post("/v1/design/artefacts/remove-worktree", json={"id": WT}, headers=auth_headers)
    assert r.status_code == 200 and r.json()["removed"] is True


def test_remove_worktree_errors(client, auth_headers, tmp_vault):
    _artefact(tmp_vault, PROTO)
    r = client.post("/v1/design/artefacts/remove-worktree", json={"id": PROTO}, headers=auth_headers)
    assert r.status_code == 409
    r = client.post("/v1/design/artefacts/remove-worktree", json={"id": "../../etc"}, headers=auth_headers)
    assert r.status_code == 404


def test_eject(client, auth_headers, tmp_vault, tmp_path, monkeypatch):
    from ghostbrain.design import scaffold

    folder = _artefact(tmp_vault, PROTO)
    monkeypatch.setattr(scaffold, "eject", lambda d: d)
    r = client.post("/v1/design/artefacts/eject", json={"id": PROTO}, headers=auth_headers)
    assert r.status_code == 200 and r.json() == {"path": str(folder)}

    _worktree_artefact(tmp_vault, tmp_path)
    r = client.post("/v1/design/artefacts/eject", json={"id": WT}, headers=auth_headers)
    assert r.status_code == 409
    r = client.post("/v1/design/artefacts/eject", json={"id": "../../etc"}, headers=auth_headers)
    assert r.status_code == 404


def test_artefacts_hook_registered_when_app_built(client):
    from ghostbrain.recorder import hooks

    assert artefacts.link_meeting in hooks._on_transcribed
