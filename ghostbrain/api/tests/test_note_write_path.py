"""note.py writers on the vault write path: byte preservation, golden parity
with the legacy writer for canonical files, If-Match on the routes."""
from __future__ import annotations

import frontmatter
import pytest

from ghostbrain.api.repo.note import save_note_at_path, save_note_body
from ghostbrain.api.tests.conftest import write_note
from ghostbrain.vault_write import compute_etag, writer

NOW = "2026-10-09T10:00:00+00:00"
REL = "20-contexts/work/notes/n.md"
HAND_EDITED = (
    "---\n"
    "# synced from mail — do not edit by hand\n"
    "source: gmail\n"
    "title: \"Re: Q3 plan\"\n"
    "context:   work\n"
    "updated: '2026-01-01T00:00:00+00:00'\n"
    "---\n"
    "\n"
    "old body\n"
)


@pytest.fixture(autouse=True)
def _frozen_now(monkeypatch):
    monkeypatch.setattr(writer, "_now_iso", lambda: NOW)


def _legacy_save_body(text: str, body: str, now: str) -> str:
    """The pre-B1 save_note_body algorithm, kept here as the golden oracle."""
    post = frontmatter.loads(text)
    post.content = body
    if "updated" in post.metadata:
        post["updated"] = now
    if post.metadata:
        return frontmatter.dumps(post) + "\n"
    return body if body.endswith("\n") else body + "\n"


def test_hand_edited_frontmatter_survives_byte_for_byte(tmp_vault):
    p = write_note(tmp_vault, REL, HAND_EDITED)
    res = save_note_body(REL, "# edited\n\nnew body")
    assert p.read_text() == HAND_EDITED.replace(
        "2026-01-01T00:00:00+00:00", NOW
    ).replace("old body\n", "# edited\n\nnew body\n")
    assert res == {"path": REL, "updated": NOW, "etag": compute_etag(p.read_bytes())}


def test_golden_canonical_file_matches_legacy_bytes(tmp_vault):
    canonical = frontmatter.dumps(frontmatter.Post(
        "old body", source="gmail", context="work", updated="2026-01-01T00:00:00+00:00",
    )) + "\n"
    p = write_note(tmp_vault, REL, canonical)
    save_note_body(REL, "new body")
    assert p.read_text() == _legacy_save_body(canonical, "new body", NOW)


def test_golden_plain_file_matches_legacy_bytes(tmp_vault):
    p = write_note(tmp_vault, "10-daily/2026-06-09.md", "plain\n")
    save_note_body("10-daily/2026-06-09.md", "rewritten")
    assert p.read_text() == _legacy_save_body("plain\n", "rewritten", NOW)


def test_bom_note_round_trip_does_not_duplicate_frontmatter(client, tmp_vault, auth_headers):
    p = tmp_vault / REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes("\ufeff---\ntitle: Bom\n---\n\nbody\n".encode("utf-8"))
    got = client.get("/v1/notes", params={"path": REL}, headers=auth_headers).json()
    r = client.patch(
        "/v1/notes/body",
        json={"path": REL, "body": got["body"] + "\n\nmore"},
        headers={**auth_headers, "If-Match": f'"{got["etag"]}"'},
    )
    assert r.status_code == 200
    assert p.read_bytes().decode("utf-8") == "\ufeff---\ntitle: Bom\n---\n\nbody\n\nmore\n"


def test_patch_body_with_current_if_match_applies(client, tmp_vault, auth_headers):
    p = write_note(tmp_vault, REL, HAND_EDITED)
    etag = compute_etag(p.read_bytes())
    r = client.patch(
        "/v1/notes/body", json={"path": REL, "body": "x"},
        headers={**auth_headers, "If-Match": f'"{etag}"'},
    )
    assert r.status_code == 200
    assert r.json()["etag"] == compute_etag(p.read_bytes())


def test_patch_body_with_stale_if_match_is_409_and_untouched(client, tmp_vault, auth_headers):
    p = write_note(tmp_vault, REL, HAND_EDITED)
    r = client.patch(
        "/v1/notes/body", json={"path": REL, "body": "x"},
        headers={**auth_headers, "If-Match": '"0000000000000000"'},
    )
    assert r.status_code == 409
    assert r.json()["currentEtag"] == compute_etag(p.read_bytes())
    assert p.read_text() == HAND_EDITED


def test_patch_body_without_if_match_still_saves(client, tmp_vault, auth_headers):
    write_note(tmp_vault, REL, HAND_EDITED)
    r = client.patch("/v1/notes/body", json={"path": REL, "body": "x"}, headers=auth_headers)
    assert r.status_code == 200


def test_upsert_returns_etag_and_honours_if_match(client, tmp_vault, auth_headers):
    r = client.put("/v1/notes", json={"path": "Familiar/m.md", "content": "v1"}, headers=auth_headers)
    assert r.status_code == 200
    first = r.json()
    assert first["created"] is True
    assert first["etag"] == compute_etag(b"v1\n")
    stale = client.put(
        "/v1/notes", json={"path": "Familiar/m.md", "content": "v2"},
        headers={**auth_headers, "If-Match": '"0000000000000000"'},
    )
    assert stale.status_code == 409
    ok = client.put(
        "/v1/notes", json={"path": "Familiar/m.md", "content": "v2"},
        headers={**auth_headers, "If-Match": f'"{first["etag"]}"'},
    )
    assert ok.status_code == 200 and ok.json()["created"] is False
    assert (tmp_vault / "Familiar/m.md").read_text() == "v2\n"


def test_save_note_at_path_repo_contract(tmp_vault):
    res = save_note_at_path("Familiar/x.md", "body")
    assert res == {"path": "Familiar/x.md", "created": True, "etag": compute_etag(b"body\n")}
