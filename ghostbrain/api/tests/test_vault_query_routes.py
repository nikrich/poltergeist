"""POST /v1/vault/query and PATCH /v1/vault/status (smart templates C2)."""
from __future__ import annotations

from pathlib import Path

import pytest

import ghostbrain.api.repo.vault_query as repo
from ghostbrain.vault_index.links import LinkIndex, get_link_index
from ghostbrain.vault_write import compute_etag

AI = "20-contexts/work/calendar/artifacts/action_items"
REL = f"{AI}/send-budget-1a2b3c4d.md"
ITEM = (
    "---\n"
    "id: 1a2b3c4d\n"
    "context: work\n"
    "type: artifact\n"
    "artifactType: action_item\n"
    "source: calendar\n"
    "created: '2026-10-01T09:00:00+00:00'\n"
    "parent: '[[20-contexts/work/calendar/planning]]'\n"
    "tags: []  # from the extractor\n"
    "---\n"
    "\n"
    "# Send Alex the budget\n"
    "\n"
    "Alex to review the numbers.\n"
)


def _write(vault: Path, rel: str, text: str) -> Path:
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode("utf-8"))
    return p


def _query(client, auth_headers, source: str, *, refresh: bool = True):
    if refresh:
        get_link_index().refresh()
    return client.post("/v1/vault/query", json={"query": source}, headers=auth_headers)


def _tick(client, auth_headers, path: str, status: str, etag: str | None = None):
    headers = dict(auth_headers)
    if etag:
        headers["If-Match"] = f'"{etag}"'
    return client.patch("/v1/vault/status", json={"path": path, "status": status}, headers=headers)


def test_query_returns_rows(client, auth_headers, tmp_vault):
    p = _write(tmp_vault, REL, ITEM)
    r = _query(client, auth_headers, 'type: action_item\nmentions: "[[Alex]]"\nstatus: open\n')
    assert r.status_code == 200, r.text
    assert r.json() == {
        "results": [{
            "path": REL, "title": "Send Alex the budget", "context": "work", "status": None,
            "created": "2026-10-01T09:00:00+00:00", "snippet": "Alex to review the numbers.",
            "etag": compute_etag(p.read_bytes()),
        }],
        "diagnostics": [],
        "indexing": False,
        "partial": False,
    }


def test_bad_query_returns_diagnostics_with_200(client, auth_headers, tmp_vault):
    r = _query(client, auth_headers, "type: action_item\nowner: alex")
    assert r.status_code == 200
    body = r.json()
    assert body["results"] == [] and body["indexing"] is False and body["partial"] is False
    assert body["diagnostics"] == [{
        "line": 2, "col": 1, "severity": "error", "code": "unknown-key",
        "message": "unknown key `owner`; use one of: type, context, tag, mentions, status, since, sort, limit",
    }]


def test_warning_is_returned_alongside_results(client, auth_headers, tmp_vault):
    _write(tmp_vault, REL, ITEM)
    body = _query(client, auth_headers, "type: action_item\nlimit: 500").json()
    assert len(body["results"]) == 1
    assert [d["code"] for d in body["diagnostics"]] == ["limit-capped"]


def test_cold_index_reports_indexing(client, auth_headers, tmp_vault, monkeypatch):
    monkeypatch.setattr(LinkIndex, "ensure_fresh", lambda self, wait=0.25: False)
    r = _query(client, auth_headers, "type: action_item", refresh=False)
    assert r.json() == {"results": [], "diagnostics": [], "indexing": True, "partial": False}


def test_oversized_query_body_is_rejected(client, auth_headers, tmp_vault):
    r = _query(client, auth_headers, "x" * 8_001, refresh=False)
    assert r.status_code == 422


def test_tick_adds_one_status_line_and_preserves_every_other_byte(client, auth_headers, tmp_vault):
    p = _write(tmp_vault, REL, ITEM)
    r = _tick(client, auth_headers, REL, "done", compute_etag(p.read_bytes()))
    assert r.status_code == 200, r.text
    assert p.read_bytes().decode("utf-8") == ITEM.replace(
        "tags: []  # from the extractor\n", "tags: []  # from the extractor\nstatus: done\n"
    )
    assert r.json() == {"path": REL, "status": "done", "etag": compute_etag(p.read_bytes())}


def test_untick_rewrites_only_the_status_line(client, auth_headers, tmp_vault):
    done = ITEM.replace("tags: []", "status: done  # ticked\ntags: []")
    p = _write(tmp_vault, REL, done)
    r = _tick(client, auth_headers, REL, "open", compute_etag(p.read_bytes()))
    assert r.status_code == 200, r.text
    assert p.read_bytes().decode("utf-8") == done.replace("status: done  # ticked", "status: open  # ticked")


def test_tick_with_a_stale_etag_is_409_and_writes_nothing(client, auth_headers, tmp_vault):
    p = _write(tmp_vault, REL, ITEM)
    before = p.read_bytes()
    r = _tick(client, auth_headers, REL, "done", "0123456789abcdef")
    assert r.status_code == 409
    assert r.json()["currentEtag"] == compute_etag(before)
    assert p.read_bytes() == before


def test_tick_note_without_frontmatter_gets_one(client, auth_headers, tmp_vault):
    p = _write(tmp_vault, "20-contexts/work/todo.md", "call the vendor\n")
    assert _tick(client, auth_headers, "20-contexts/work/todo.md", "done").status_code == 200
    assert p.read_text(encoding="utf-8") == "---\nstatus: done\n---\n\ncall the vendor\n"


def test_tick_then_query_drops_the_done_item(client, auth_headers, tmp_vault):
    _write(tmp_vault, REL, ITEM)
    rows = _query(client, auth_headers, "type: action_item\nstatus: open").json()["results"]
    assert [r["path"] for r in rows] == [REL]
    assert _tick(client, auth_headers, REL, "done", rows[0]["etag"]).status_code == 200
    # No explicit refresh: the write path re-indexes the note (A2 note_written).
    again = _query(client, auth_headers, "type: action_item\nstatus: open", refresh=False).json()
    assert again["results"] == []


def test_tick_writes_as_user_with_the_if_match_etag(client, auth_headers, tmp_vault, monkeypatch):
    p = _write(tmp_vault, REL, ITEM)
    seen = {}
    real = repo.write

    def spy(path, **kw):
        seen.update(kw, path=path)
        return real(path, **kw)

    monkeypatch.setattr(repo, "write", spy)
    etag = compute_etag(p.read_bytes())
    assert _tick(client, auth_headers, REL, "done", etag).status_code == 200
    assert seen["path"] == REL and seen["actor"] == "user"
    assert seen["fields"] == {"status": "done"} and seen["base_etag"] == etag


@pytest.mark.parametrize("path, code", [
    ("20-contexts/work/missing.md", 404),
    ("../outside.md", 400),
    ("/etc/passwd.md", 400),
    ("20-contexts/work/page.html", 400),
])
def test_tick_rejects_bad_targets(client, auth_headers, tmp_vault, path, code):
    assert _tick(client, auth_headers, path, "done").status_code == code


def test_tick_rejects_other_status_values(client, auth_headers, tmp_vault):
    _write(tmp_vault, REL, ITEM)
    assert _tick(client, auth_headers, REL, "blocked").status_code == 422


def test_tick_as_mcp_without_if_match_writes_nothing(client, auth_headers, tmp_vault):
    p = _write(tmp_vault, REL, ITEM)
    before = p.read_bytes()
    headers = {**auth_headers, "X-Poltergeist-Actor": "mcp"}
    r = client.patch("/v1/vault/status", json={"path": REL, "status": "done"}, headers=headers)
    assert r.status_code == 428, r.text
    assert r.json()["currentEtag"] == compute_etag(before)
    assert p.read_bytes() == before


def test_a_held_tick_is_202_pending_and_writes_nothing(client, auth_headers, tmp_vault):
    rel = "80-profile/preferences.md"  # stable profile: a non-user edit is held (B3)
    p = _write(tmp_vault, rel, "---\nstatus: open\n---\n\n# Preferences\n")
    before = p.read_bytes()
    headers = {
        **auth_headers, "X-Poltergeist-Actor": "assistant", "If-Match": f'"{compute_etag(before)}"',
    }
    r = client.patch("/v1/vault/status", json={"path": rel, "status": "done"}, headers=headers)
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "pending" and r.json()["changeId"]
    assert p.read_bytes() == before
