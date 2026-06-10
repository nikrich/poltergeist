"""PATCH/DELETE/route endpoints for individual jots."""
from datetime import datetime, timezone

import pytest

from ghostbrain.api.repo.notes_manual import write_inbox_jot


def test_patch_updates_body(tmp_vault, client, auth_headers):
    (tmp_vault / "00-inbox" / "raw" / "manual").mkdir(parents=True, exist_ok=True)
    when = datetime(2026, 5, 14, 9, 0, 0, tzinfo=timezone.utc)
    rec = write_inbox_jot("original", captured_at=when)
    resp = client.patch(
        f"/v1/notes/{rec['id']}", json={"body": "new body #x"}, headers=auth_headers
    )
    assert resp.status_code == 200
    read = client.get(
        f"/v1/notes?path={resp.json()['path']}", headers=auth_headers
    ).json()
    assert read["body"].strip() == "new body #x"
    assert read["frontmatter"]["tags"] == ["x"]


def test_patch_unknown_returns_404(tmp_vault, client, auth_headers):
    resp = client.patch(
        "/v1/notes/manual-19000101T000000-nope",
        json={"body": "x"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


def test_route_moves_to_chosen_context(tmp_vault, client, auth_headers):
    (tmp_vault / "00-inbox" / "raw" / "manual").mkdir(parents=True, exist_ok=True)
    (tmp_vault / "20-contexts" / "codeship" / "notes").mkdir(parents=True, exist_ok=True)
    when = datetime(2026, 5, 14, 9, 0, 0, tzinfo=timezone.utc)
    rec = write_inbox_jot("re-route me", captured_at=when)
    resp = client.post(
        f"/v1/notes/{rec['id']}/route",
        json={"context": "codeship"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["context"] == "codeship"
    assert data["path"].startswith("20-contexts/codeship/notes/")


def test_route_rejects_unknown_context(tmp_vault, client, auth_headers):
    (tmp_vault / "00-inbox" / "raw" / "manual").mkdir(parents=True, exist_ok=True)
    when = datetime(2026, 5, 14, 9, 0, 0, tzinfo=timezone.utc)
    rec = write_inbox_jot("x", captured_at=when)
    resp = client.post(
        f"/v1/notes/{rec['id']}/route",
        json={"context": "not-a-real-ctx"},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_delete_removes_file(tmp_vault, client, auth_headers):
    (tmp_vault / "00-inbox" / "raw" / "manual").mkdir(parents=True, exist_ok=True)
    when = datetime(2026, 5, 14, 9, 0, 0, tzinfo=timezone.utc)
    rec = write_inbox_jot("ephemeral", captured_at=when)
    resp = client.delete(f"/v1/notes/{rec['id']}", headers=auth_headers)
    assert resp.status_code == 204
    resp2 = client.patch(
        f"/v1/notes/{rec['id']}", json={"body": "x"}, headers=auth_headers
    )
    assert resp2.status_code == 404
