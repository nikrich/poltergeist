"""GET /v1/notes?source=manual — list jots for the Jot screen."""
from datetime import datetime, timezone

import pytest

from ghostbrain.api.repo.notes_manual import write_inbox_jot, move_jot


def _seed_two(vault):
    t1 = datetime(2026, 5, 14, 9, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 5, 14, 10, 0, 0, tzinfo=timezone.utc)
    (vault / "00-inbox" / "raw" / "manual").mkdir(parents=True, exist_ok=True)
    (vault / "20-contexts" / "sanlam" / "notes").mkdir(parents=True, exist_ok=True)
    a = write_inbox_jot("first jot #ui", captured_at=t1)
    b = write_inbox_jot("second jot ascp #idea", captured_at=t2)
    move_jot(b["id"], to_context="sanlam", confidence=0.9, method="llm",
             reasoning="t")
    return a, b


def test_list_returns_both_inbox_and_routed(tmp_vault, client, auth_headers):
    a, b = _seed_two(tmp_vault)
    resp = client.get("/v1/notes?source=manual", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    ids = [item["id"] for item in data["items"]]
    assert ids == [b["id"], a["id"]]


def test_list_q_filter(tmp_vault, client, auth_headers):
    _seed_two(tmp_vault)
    resp = client.get("/v1/notes?source=manual&q=ascp", headers=auth_headers)
    data = resp.json()
    assert data["total"] == 1
    assert "ascp" in data["items"][0]["title"]


def test_list_tag_filter(tmp_vault, client, auth_headers):
    _seed_two(tmp_vault)
    resp = client.get("/v1/notes?source=manual&tag=ui", headers=auth_headers)
    data = resp.json()
    assert data["total"] == 1
    assert "ui" in data["items"][0]["tags"]


def test_list_context_filter(tmp_vault, client, auth_headers):
    a, b = _seed_two(tmp_vault)
    resp = client.get("/v1/notes?source=manual&context=sanlam", headers=auth_headers)
    data = resp.json()
    assert [item["id"] for item in data["items"]] == [b["id"]]
    _ = a


def test_list_unsupported_source_rejected(tmp_vault, client, auth_headers):
    resp = client.get("/v1/notes?source=slack", headers=auth_headers)
    assert resp.status_code == 400
