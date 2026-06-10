"""Docs assist + export routes (SSE shape, stop, error mapping)."""
import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from ghostbrain.api.main import create_app

_TOKEN = "test-token"
_HEADERS = {"Authorization": f"Bearer {_TOKEN}"}


def _client():
    app = create_app(_TOKEN)
    return TestClient(app)


def test_assist_streams_sse():
    def fake(jot_id, **kw):
        yield {"type": "delta", "text": "hi"}
        yield {"type": "done", "text": "hi", "session_id": ""}

    with patch("ghostbrain.api.routes.docs.docs_assist.run_assist", fake):
        res = _client().post("/v1/docs/assist", json={"jot_id": "j1", "mode": "polish"}, headers=_HEADERS)
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    payloads = [json.loads(l[6:]) for l in res.text.splitlines() if l.startswith("data: ")]
    assert [p["type"] for p in payloads] == ["delta", "done"]


def test_assist_stop():
    with patch("ghostbrain.api.routes.docs.docs_assist.cancel", return_value=True):
        res = _client().post("/v1/docs/assist/stop", json={"jot_id": "j1"}, headers=_HEADERS)
    assert res.json() == {"stopped": True}
