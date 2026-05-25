"""Integration tests for /v1/meetings/prep/{event_id}."""
from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from ghostbrain.api.main import create_app

_TOKEN = "test-token"
_HEADERS = {"Authorization": f"Bearer {_TOKEN}"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path / "state"))
    cal = tmp_path / "20-contexts" / "sanlam" / "calendar"
    cal.mkdir(parents=True)
    (cal / "20260525T090000-eng-standup.md").write_text(textwrap.dedent("""\
        ---
        title: Eng standup
        start: 2026-05-25T09:00:00+02:00
        end: 2026-05-25T09:30:00+02:00
        with:
          - alice@example.com
        location: Zoom
        description: sprint planning
        ---
        """))

    # Patch the expensive deps. Default: succeed.
    from ghostbrain.worker import meeting_prep as mp
    monkeypatch.setattr(mp, "_semantic_search", MagicMock(return_value={"items": []}))
    monkeypatch.setattr(mp, "_llm_run", MagicMock(return_value=MagicMock(text="brief")))

    return TestClient(create_app(_TOKEN))


def test_get_prep_generates_when_missing(client):
    r = client.get("/v1/meetings/prep/20260525T090000-eng-standup", headers=_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["eventId"] == "20260525T090000-eng-standup"
    assert body["brief"] == "brief"
    assert body["eventSnapshot"]["title"] == "Eng standup"


def test_get_prep_uses_cache_on_repeat(client, monkeypatch):
    from ghostbrain.worker import meeting_prep as mp

    r1 = client.get("/v1/meetings/prep/20260525T090000-eng-standup", headers=_HEADERS)
    assert r1.status_code == 200
    # Swap the LLM to one that would raise if called.
    monkeypatch.setattr(mp, "_llm_run", MagicMock(side_effect=AssertionError("should not be called")))
    r2 = client.get("/v1/meetings/prep/20260525T090000-eng-standup", headers=_HEADERS)
    assert r2.status_code == 200
    assert r2.json()["brief"] == "brief"  # same response, no new LLM call


def test_get_prep_unknown_event_returns_404(client):
    r = client.get("/v1/meetings/prep/nope", headers=_HEADERS)
    assert r.status_code == 404
