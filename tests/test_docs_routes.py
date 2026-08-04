"""Docs assist + export routes (SSE shape, stop, error mapping)."""
import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from ghostbrain.api.main import create_app
from ghostbrain.api.repo.notes_manual import JotNotFound

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
    payloads = [json.loads(line[6:]) for line in res.text.splitlines() if line.startswith("data: ")]
    assert [p["type"] for p in payloads] == ["delta", "done"]


def test_assist_stop():
    with patch("ghostbrain.api.routes.docs.docs_assist.cancel", return_value=True):
        res = _client().post("/v1/docs/assist/stop", json={"jot_id": "j1"}, headers=_HEADERS)
    assert res.json() == {"stopped": True}


def test_export_confluence_200():
    with patch(
        "ghostbrain.api.routes.docs.export_confluence.export_jot",
        return_value={"action": "created", "page_id": "42", "url": "https://x/wiki/42"},
    ):
        res = _client().post(
            "/v1/docs/export/confluence",
            json={"jot_id": "j1", "space_key": "K"},
            headers=_HEADERS,
        )
    assert res.status_code == 200
    assert res.json()["action"] == "created"
    assert res.json()["page_id"] == "42"


def test_export_confluence_404_on_jot_not_found():
    with patch(
        "ghostbrain.api.routes.docs.export_confluence.export_jot",
        side_effect=JotNotFound("j1"),
    ):
        res = _client().post(
            "/v1/docs/export/confluence",
            json={"jot_id": "j1", "space_key": "K"},
            headers=_HEADERS,
        )
    assert res.status_code == 404
    assert "jot not found" in res.json()["detail"]


def test_export_confluence_409_on_tracked_page_gone():
    from ghostbrain.api.repo.export_confluence import TrackedPageGone
    with patch(
        "ghostbrain.api.routes.docs.export_confluence.export_jot",
        side_effect=TrackedPageGone("42"),
    ):
        res = _client().post(
            "/v1/docs/export/confluence",
            json={"jot_id": "j1", "space_key": "K"},
            headers=_HEADERS,
        )
    assert res.status_code == 409
    assert "no longer exists" in res.json()["detail"]
