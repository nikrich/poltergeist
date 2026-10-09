"""GET /v1/recorder/live — SSE stream of the live transcript."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from ghostbrain.recorder import live


def _events(text: str) -> list[dict]:
    return [json.loads(line[len("data: "):]) for line in text.splitlines() if line.startswith("data: ")]


def test_live_with_no_recording_ends_immediately(client: TestClient, auth_headers: dict[str, str]):
    res = client.get("/v1/recorder/live", headers=auth_headers)
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    assert _events(res.text) == [{"type": "end"}]


def test_live_streams_the_follow_generator(client: TestClient, auth_headers: dict[str, str], monkeypatch):
    def fake_follow(wav=None, *, keepalive_s: float = 15.0, enabled: bool = True):
        yield {"type": "segment", "seq": 1, "t0": 0.0, "t1": 2.0, "text": "hallo", "lang": "af"}
        yield None  # keepalive
        yield {"type": "status", "state": "live", "reason": None, "lag_s": 0.0}
        yield {"type": "end"}

    monkeypatch.setattr(live, "follow", fake_follow)
    res = client.get("/v1/recorder/live", headers=auth_headers)
    assert _events(res.text) == [
        {"type": "segment", "seq": 1, "t0": 0.0, "t1": 2.0, "text": "hallo", "lang": "af"},
        {"type": "status", "state": "live", "reason": None, "lag_s": 0.0},
        {"type": "end"},
    ]
    assert ": keepalive" in res.text


def test_live_requires_auth(client: TestClient):
    assert client.get("/v1/recorder/live").status_code == 401


def test_levels_with_no_recording_ends_immediately(client: TestClient, auth_headers: dict[str, str], monkeypatch):
    from ghostbrain.api.routes import recorder as routes

    monkeypatch.setattr(routes, "status", lambda: {"phase": "idle", "wavPath": None})
    res = client.get("/v1/recorder/levels", headers=auth_headers)
    assert res.headers["content-type"].startswith("text/event-stream")
    assert _events(res.text) == [{"type": "end"}]


def test_levels_streams_for_the_active_recording(
    client: TestClient, auth_headers: dict[str, str], monkeypatch, tmp_path,
):
    from ghostbrain.api.routes import recorder as routes
    from ghostbrain.recorder import levels

    wav = tmp_path / "rec.wav"
    monkeypatch.setattr(routes, "status", lambda: {"phase": "recording", "wavPath": str(wav)})
    seen = {}

    def fake_follow(path, **_kw):
        seen["path"] = path
        yield [0.1, 0.5]
        yield None
        yield [0.9]

    monkeypatch.setattr(levels, "follow_levels", fake_follow)
    res = client.get("/v1/recorder/levels", headers=auth_headers)
    assert seen["path"] == wav
    assert _events(res.text) == [
        {"type": "levels", "levels": [0.1, 0.5]},
        {"type": "levels", "levels": [0.9]},
        {"type": "end"},
    ]


def test_live_resumes_a_session_for_an_active_recording(
    client: TestClient, auth_headers: dict[str, str], monkeypatch, tmp_path,
):
    """After an app restart mid-meeting there is no session: start one."""
    from ghostbrain.api.routes import recorder as routes

    wav = tmp_path / "rec.wav"
    monkeypatch.setattr(routes, "status", lambda: {"phase": "recording", "wavPath": str(wav)})
    begun = {}
    monkeypatch.setattr(live, "current", lambda: None)
    monkeypatch.setattr(live, "begin_from_config", lambda p: begun.setdefault("wav", p))

    def fake_follow(w=None, *, keepalive_s: float = 15.0, enabled: bool = True):
        begun["follow"] = (w, enabled)
        yield {"type": "end"}

    monkeypatch.setattr(live, "follow", fake_follow)
    client.get("/v1/recorder/live", headers=auth_headers)
    assert begun["wav"] == wav
    assert begun["follow"] == (wav, True)


def test_live_says_off_when_disabled(
    client: TestClient, auth_headers: dict[str, str], monkeypatch, tmp_path,
):
    from ghostbrain.api.routes import recorder as routes
    from ghostbrain.recorder import config as rcfg

    wav = tmp_path / "rec.wav"
    monkeypatch.setattr(routes, "status", lambda: {"phase": "recording", "wavPath": str(wav)})
    monkeypatch.setattr(rcfg, "load_recorder_block", lambda: {"live_transcription": False})
    monkeypatch.setattr(live, "begin_from_config", lambda p: (_ for _ in ()).throw(AssertionError("must not start")))
    res = client.get("/v1/recorder/live", headers=auth_headers)
    assert _events(res.text) == [
        {"type": "status", "state": "off", "reason": None, "lag_s": 0.0},
        {"type": "end"},
    ]
