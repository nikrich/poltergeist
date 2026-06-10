"""PATCH /v1/notes/body — by-path body rewrite for the rich editor."""
from datetime import datetime, timezone

import frontmatter

from ghostbrain.api.repo.notes_manual import write_inbox_jot
from ghostbrain.api.tests.conftest import write_note

SYNCED = (
    "---\n"
    "source: gmail\n"
    "context: sanlam\n"
    "updated: '2026-01-01T00:00:00+00:00'\n"
    "---\n"
    "\n"
    "old body\n"
)


def test_patch_body_rewrites_and_preserves_frontmatter(tmp_vault, client, auth_headers):
    write_note(tmp_vault, "20-contexts/sanlam/notes/synced.md", SYNCED)
    resp = client.patch(
        "/v1/notes/body",
        json={"path": "20-contexts/sanlam/notes/synced.md", "body": "# edited\n\nnew body"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["path"] == "20-contexts/sanlam/notes/synced.md"
    post = frontmatter.load(tmp_vault / "20-contexts/sanlam/notes/synced.md")
    assert post.content.strip() == "# edited\n\nnew body"
    # connector file edit is allowed; source key untouched
    assert post["source"] == "gmail"
    assert post["updated"] != "2026-01-01T00:00:00+00:00"
    assert data["updated"] == post["updated"]


def test_patch_body_not_shadowed_by_jot_route(tmp_vault, client, auth_headers):
    """Regression guard for route ordering.

    PATCH /{jot_id} has min_length=8 on the path param; "body" (4 chars)
    matches its path regex, so if /body were registered after it, this request
    would return 422 string_too_short from the jot route's validator instead
    of reaching the by-path handler (verified empirically). This test pins the
    registration order.
    """
    write_note(
        tmp_vault,
        "20-contexts/personal/notes/n.md",
        "---\nupdated: '2026-01-01T00:00:00+00:00'\n---\n\nx\n",
    )
    resp = client.patch(
        "/v1/notes/body",
        json={"path": "20-contexts/personal/notes/n.md", "body": "y"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["path"] == "20-contexts/personal/notes/n.md"


def test_patch_body_jot_route_still_reachable(tmp_vault, client, auth_headers):
    (tmp_vault / "00-inbox" / "raw" / "manual").mkdir(parents=True, exist_ok=True)
    when = datetime(2026, 6, 9, 9, 0, 0, tzinfo=timezone.utc)
    rec = write_inbox_jot("still works", captured_at=when)
    resp = client.patch(
        f"/v1/notes/{rec['id']}", json={"body": "edited jot"}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == rec["id"]


def test_patch_body_unknown_path_404(tmp_vault, client, auth_headers):
    resp = client.patch(
        "/v1/notes/body",
        json={"path": "20-contexts/sanlam/notes/missing.md", "body": "x"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


def test_patch_body_traversal_400(tmp_vault, client, auth_headers):
    resp = client.patch(
        "/v1/notes/body",
        json={"path": "../../etc/passwd.md", "body": "x"},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_patch_body_empty_body_422(tmp_vault, client, auth_headers):
    write_note(
        tmp_vault,
        "20-contexts/sanlam/notes/n.md",
        "---\nsource: manual\n---\n\nbody\n",
    )
    resp = client.patch(
        "/v1/notes/body",
        json={"path": "20-contexts/sanlam/notes/n.md", "body": "   "},
        headers=auth_headers,
    )
    assert resp.status_code == 422
