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
    def fake_follow(wav=None, *, keepalive_s: float = 15.0):
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
