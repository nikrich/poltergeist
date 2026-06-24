"""POST /v1/notes/{jot_id}/extract-photo — route tests.

Uses the shared `client` / `auth_headers` fixtures from conftest.
"""
from unittest.mock import patch

from ghostbrain.api.repo import notes_manual


def test_extract_route_appends(client, auth_headers, tmp_vault):
    """Happy path: patched helper returns extracted=True → 200 + extracted."""
    rec = notes_manual.write_inbox_jot("shot\n\n")

    with patch.object(
        notes_manual,
        "extract_photo_into_jot",
        return_value={
            "id": rec["id"],
            "path": rec["path"],
            "body": "shot\n\n> **Extracted from photo**\n> hi\n",
            "extracted": True,
        },
    ):
        r = client.post(
            f"/v1/notes/{rec['id']}/extract-photo",
            json={"assetPath": "90-meta/assets/jots/2026/06/x-1.jpg"},
            headers=auth_headers,
        )

    assert r.status_code == 200
    assert r.json()["extracted"] is True


def test_extract_route_404(client, auth_headers, tmp_vault):
    """Unknown jot id → 404 (real helper raises JotNotFound before any LLM call)."""
    r = client.post(
        "/v1/notes/doesnotexist-8char/extract-photo",
        json={"assetPath": "90-meta/assets/jots/2026/06/x-1.jpg"},
        headers=auth_headers,
    )
    assert r.status_code == 404
