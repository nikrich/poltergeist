"""/v1/design/live and /v1/design/session* routes."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ghostbrain.design import scaffold
from ghostbrain.design import session as ds


def _events(text: str) -> list[dict]:
    return [json.loads(line[len("data: "):]) for line in text.splitlines() if line.startswith("data: ")]


@pytest.fixture(autouse=True)
def _clean_registry(monkeypatch):
    from ghostbrain.api.routes import design as routes

    monkeypatch.setattr(routes, "status", lambda: {"phase": "idle", "wavPath": None})
    monkeypatch.setattr(ds, "_provider_id", lambda: "claude")
    ds.stop_all()
    yield
    ds.stop_all()


@pytest.fixture()
def session(tmp_path, monkeypatch, tmp_vault):
    def create(prototype_dir, pack_id, *, title):
        Path(prototype_dir, "src").mkdir(parents=True)

    monkeypatch.setattr(scaffold, "create", create)
    monkeypatch.setattr(scaffold, "commit", lambda d, m: "sha")
    monkeypatch.setattr(scaffold, "eject", lambda d: Path(d))
    s = ds.DesignSession(tmp_path / "rec.wav", title="Claims sync", context="work", threaded=False)
    return ds._register(s)


ACTIONS = [
    ("/v1/design/session/start", {"canvas": "ui"}),
    ("/v1/design/session/pause", {"canvas": "both"}),
    ("/v1/design/session/resume", {"canvas": "ui"}),
    ("/v1/design/session/nudge", {"text": "add a filter"}),
    ("/v1/design/session/update", {}),
    ("/v1/design/session/undo", {"token": "x"}),
    ("/v1/design/session/config", {"pack_id": "poltergeist-neutral"}),
    ("/v1/design/session/build-error", {"rev": 1, "message": "boom"}),
    ("/v1/design/session/revert", {"canvas": "ui", "rev": 0}),
    ("/v1/design/session/eject", {}),
]


def test_session_404_without_a_session(client: TestClient, auth_headers):
    assert client.get("/v1/design/session", headers=auth_headers).status_code == 404


@pytest.mark.parametrize("path,body", ACTIONS)
def test_actions_409_without_a_session(client: TestClient, auth_headers, path, body):
    assert client.post(path, json=body, headers=auth_headers).status_code == 409


def test_requires_auth(client: TestClient):
    assert client.get("/v1/design/session").status_code == 401
    assert client.get("/v1/design/live").status_code == 401


def test_live_without_recording_or_session_is_idle(client: TestClient, auth_headers):
    res = client.get("/v1/design/live", headers=auth_headers)
    assert res.headers["content-type"].startswith("text/event-stream")
    assert _events(res.text) == [{"type": "idle"}, {"type": "end"}]


def test_live_streams_snapshot_first_then_end_for_an_ended_session(client: TestClient, auth_headers, session):
    session.end()
    events = _events(client.get("/v1/design/live", headers=auth_headers).text)
    assert events[0]["type"] == "snapshot"
    assert events[0]["session"]["id"] == session.id
    assert events[-1] == {"type": "end"}


def test_live_ensures_a_session_for_the_recording_in_progress(client: TestClient, auth_headers, monkeypatch, tmp_path):
    from ghostbrain.api.routes import design as routes
    from ghostbrain.design import listener

    wav = tmp_path / "now.wav"
    monkeypatch.setattr(routes, "status", lambda: {"phase": "recording", "wavPath": str(wav)})
    started = []

    def fake_start(path, **kw):
        started.append(path)
        s = ds.DesignSession(path, title="T", context="work", threaded=False)
        ds._register(s)
        s.end()  # so the stream terminates

    monkeypatch.setattr(listener, "start_for_recording", fake_start)
    events = _events(client.get("/v1/design/live", headers=auth_headers).text)
    assert started == [wav]
    assert events[0]["type"] == "snapshot"
    assert events[-1] == {"type": "end"}


def test_get_session_returns_the_snapshot(client: TestClient, auth_headers, session):
    res = client.get("/v1/design/session", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == session.id
    assert body["canvases"]["ui"]["state"] == "off"
    assert body["board"] is None


def test_start_pause_resume_undo(client: TestClient, auth_headers, session):
    res = client.post("/v1/design/session/start", json={"canvas": "board"}, headers=auth_headers)
    assert res.status_code == 200
    event = res.json()["event"]
    assert event["command"] == "start_board" and event["spoken"] is False and event["undo_token"]
    assert res.json()["session"]["canvases"]["board"]["state"] == "active"

    res = client.post("/v1/design/session/pause", json={"canvas": "board"}, headers=auth_headers)
    assert res.json()["session"]["canvases"]["board"]["state"] == "paused"
    res = client.post("/v1/design/session/resume", json={"canvas": "board"}, headers=auth_headers)
    assert res.json()["session"]["canvases"]["board"]["state"] == "active"

    res = client.post("/v1/design/session/undo", json={"token": event["undo_token"]}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["session"]["canvases"]["board"]["state"] == "off"
    res = client.post("/v1/design/session/undo", json={"token": "nope"}, headers=auth_headers)
    assert res.status_code == 409


def test_nudge_and_update(client: TestClient, auth_headers, session):
    client.post("/v1/design/session/start", json={"canvas": "ui"}, headers=auth_headers)
    res = client.post("/v1/design/session/nudge", json={"text": "add a filter"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["event"]["canvas"] == "ui"
    assert session.canvases["ui"].nudges == ["add a filter"]
    assert client.post("/v1/design/session/update", json={}, headers=auth_headers).status_code == 200
    assert client.post("/v1/design/session/nudge", json={"text": ""}, headers=auth_headers).status_code == 422


def test_unavailable_ui_is_409_with_reason(client: TestClient, auth_headers, session, monkeypatch):
    monkeypatch.setattr(ds, "_provider_id", lambda: "codex")
    res = client.post("/v1/design/session/start", json={"canvas": "ui"}, headers=auth_headers)
    assert res.status_code == 409
    assert "Claude provider" in res.json()["detail"]


def test_config_unknown_pack_is_422(client: TestClient, auth_headers, session):
    res = client.post("/v1/design/session/config", json={"pack_id": "nope"}, headers=auth_headers)
    assert res.status_code == 422


def test_build_error_and_revert_and_eject(client: TestClient, auth_headers, session):
    assert client.post("/v1/design/session/eject", json={}, headers=auth_headers).status_code == 409
    client.post("/v1/design/session/start", json={"canvas": "board"}, headers=auth_headers)
    res = client.post("/v1/design/session/build-error", json={"rev": 0, "message": "x"}, headers=auth_headers)
    assert res.status_code == 200
    res = client.post("/v1/design/session/revert", json={"canvas": "board", "rev": 3}, headers=auth_headers)
    assert res.status_code == 409
    res = client.post("/v1/design/session/eject", json={}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == {"path": session.prototype_dir}


def test_start_creates_the_session_for_a_recording_on_demand(client: TestClient, auth_headers, monkeypatch, tmp_path, tmp_vault):
    from ghostbrain.api.routes import design as routes
    from ghostbrain.design import listener

    wav = tmp_path / "now.wav"
    monkeypatch.setattr(routes, "status", lambda: {"phase": "recording", "wavPath": str(wav)})
    monkeypatch.setattr(scaffold, "create", lambda d, p, *, title: Path(d, "src").mkdir(parents=True))
    monkeypatch.setattr(listener, "start_for_recording",
                        lambda path, **kw: ds._register(ds.DesignSession(path, title="T", context="work", threaded=False)))
    res = client.post("/v1/design/session/start", json={"canvas": "board"}, headers=auth_headers)
    assert res.status_code == 200
    assert ds.get(wav).snapshot()["canvases"]["board"]["state"] == "active"


def test_config_null_project_clears_it(client: TestClient, auth_headers, session):
    session.project_id = "work/old"
    res = client.post("/v1/design/session/config", json={"project_id": None}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["session"]["project_id"] is None
    assert res.json()["session"]["prototype_rel"].startswith("20-contexts/work/prototypes/")


# -- codebases ------------------------------------------------------------------

@pytest.fixture()
def repos(monkeypatch, tmp_path):
    from ghostbrain.design import codebases

    web = codebases.Candidate(tmp_path / "code" / "acme-web", "acme/acme-web", "acme-web", True)
    bff = codebases.Candidate(tmp_path / "code" / "acme-bff", "acme/acme-bff", "acme-bff", False)
    calls = []

    def scan(roots=None, *, max_depth=5, refresh=False):
        calls.append(refresh)
        return [bff, web]

    monkeypatch.setattr(codebases, "scan", scan)
    return {"web": web, "bff": bff, "calls": calls}


def test_codebases_lists_frontends_first(client: TestClient, auth_headers, repos):
    res = client.get("/v1/design/codebases", headers=auth_headers)
    assert res.status_code == 200
    assert [c["name"] for c in res.json()] == ["acme-web", "acme-bff"]
    assert res.json()[0] == {"path": str(repos["web"].path), "rel": "acme/acme-web",
                             "name": "acme-web", "frontend": True}
    assert repos["calls"] == [False]


def test_codebases_query_and_refresh(client: TestClient, auth_headers, repos):
    res = client.get("/v1/design/codebases", params={"q": "bff", "refresh": "true"}, headers=auth_headers)
    assert res.status_code == 200
    assert [c["name"] for c in res.json()] == ["acme-bff"]
    assert repos["calls"][0] is True


def test_session_codebase_switches_and_validates(client: TestClient, auth_headers, session, repos):
    res = client.post("/v1/design/session/codebase", json={"path": str(repos["web"].path)}, headers=auth_headers)
    assert res.status_code == 200
    body = res.json()["session"]
    assert body["ui_kind"] == "worktree" and body["codebase"]["name"] == "acme-web"
    assert body["install"] == "idle" and body["artefact_rel"].startswith("20-contexts/work/artefacts/")
    assert body["codebase_confirmed"] is True
    res = client.post("/v1/design/session/codebase", json={"path": "/nowhere"}, headers=auth_headers)
    assert res.status_code == 422
    res = client.post("/v1/design/session/codebase", json={"path": None}, headers=auth_headers)
    assert res.status_code == 200 and res.json()["session"]["ui_kind"] == "scratch"


def test_session_codebase_409_after_revs(client: TestClient, auth_headers, session, repos):
    session.canvases["ui"].rev = 1
    res = client.post("/v1/design/session/codebase", json={"path": str(repos["web"].path)}, headers=auth_headers)
    assert res.status_code == 409
    assert "already has revisions" in res.json()["detail"]


def test_session_codebase_409_without_a_session(client: TestClient, auth_headers):
    assert client.post("/v1/design/session/codebase", json={"path": None}, headers=auth_headers).status_code == 409
