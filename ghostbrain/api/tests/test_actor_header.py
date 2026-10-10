"""B2: X-Poltergeist-Actor attribution on the write routes (spec B §2)."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from ghostbrain.api.repo.notes_manual import write_inbox_jot
from ghostbrain.api.tests.conftest import write_note
from ghostbrain.api.vault_http import ACTOR_HEADER, request_actor
from ghostbrain.changes import log as changes
from ghostbrain.vault_write import compute_etag
from ghostbrain.worker.router import RoutingDecision

REL = "20-contexts/work/notes/plan.md"
V1 = "---\ntitle: Plan\n---\n\nfirst draft\n"


def _h(auth: dict, actor: str | None = None, etag: str | None = None) -> dict:
    h = dict(auth)
    if actor is not None:
        h[ACTOR_HEADER] = actor
    if etag is not None:
        h["If-Match"] = f'"{etag}"'
    return h


def test_request_actor_parsing():
    assert request_actor(None) == "user"
    assert request_actor("   ") == "user"
    assert request_actor("assistant") == "assistant"
    assert request_actor(" plugin:familiar ") == "plugin:familiar"
    for bad in ("admin", "worker:reversal", "restore", "plugin:../x"):
        with pytest.raises(HTTPException) as exc:
            request_actor(bad)
        assert exc.value.status_code == 400


def test_a_missing_header_is_the_user_and_gets_no_row(tmp_vault, client, auth_headers):
    write_note(tmp_vault, REL, V1)
    r = client.patch("/v1/notes/body", json={"path": REL, "body": "mine"}, headers=auth_headers)
    assert r.status_code == 200
    assert changes.list_changes() == []


def test_assistant_header_records_an_assistant_change(tmp_vault, client, auth_headers):
    write_note(tmp_vault, REL, V1)
    r = client.patch("/v1/notes/body", json={"path": REL, "body": "polished"},
                     headers=_h(auth_headers, "assistant", compute_etag(V1.encode())))
    assert r.status_code == 200
    [row] = changes.list_changes()
    assert (row.actor, row.op, row.rel_path, row.reason) == (
        "assistant", "modify", REL, "accepted an assistant edit")


def test_assistant_edit_without_if_match_is_428(tmp_vault, client, auth_headers):
    note = write_note(tmp_vault, REL, V1)
    r = client.patch("/v1/notes/body", json={"path": REL, "body": "polished"},
                     headers=_h(auth_headers, "assistant"))
    assert r.status_code == 428
    assert r.json()["currentEtag"] == compute_etag(V1.encode())
    assert note.read_text() == V1


def test_reserved_or_malformed_actor_headers_are_400(tmp_vault, client, auth_headers):
    note = write_note(tmp_vault, REL, V1)
    for bad in ("worker:reversal", "restore", "admin"):
        r = client.patch("/v1/notes/body", json={"path": REL, "body": "x"},
                         headers=_h(auth_headers, bad))
        assert r.status_code == 400
    assert note.read_text() == V1


def test_upsert_without_a_header_stays_attributed_to_a_plugin(tmp_vault, client, auth_headers):
    r = client.put("/v1/notes", json={"path": "Familiar/m.md", "content": "v1"},
                   headers=auth_headers)
    assert r.status_code == 200
    [row] = changes.list_changes()
    assert (row.actor, row.op) == ("plugin:unattributed", "create")


def test_plugin_header_attributes_and_allows_rewriting_its_own_note(
    tmp_vault, client, auth_headers
):
    h = _h(auth_headers, "plugin:familiar")
    assert client.put("/v1/notes", json={"path": "Familiar/m.md", "content": "v1"},
                      headers=h).status_code == 200
    assert client.put("/v1/notes", json={"path": "Familiar/m.md", "content": "v2"},
                      headers=h).status_code == 200
    (tmp_vault / "Familiar/m.md").write_text("user edit\n")
    r = client.put("/v1/notes", json={"path": "Familiar/m.md", "content": "v3"}, headers=h)
    assert r.status_code == 428
    assert (tmp_vault / "Familiar/m.md").read_text() == "user edit\n"
    assert [c.actor for c in changes.list_changes()] == ["plugin:familiar", "plugin:familiar"]


def test_generated_docs_are_mcp_changes(tmp_vault, client, auth_headers):
    r = client.post("/v1/docs/write", json={"title": "Plan", "html": "<p>x</p>"},
                    headers=auth_headers)
    assert r.status_code == 200
    [row] = changes.list_changes()
    assert (row.actor, row.op, row.rel_path) == ("mcp", "create", r.json()["path"])


def test_a_plugin_creating_a_jot_is_recorded(tmp_vault, client, auth_headers):
    r = client.post("/v1/notes", json={"body": "from a plugin", "route": False},
                    headers=_h(auth_headers, "plugin:familiar"))
    assert r.status_code == 200
    [row] = changes.list_changes()
    assert (row.actor, row.op, row.rel_path) == ("plugin:familiar", "create", r.json()["path"])


def test_a_plugin_deleting_a_users_jot_needs_its_etag(tmp_vault, client, auth_headers):
    rec = write_inbox_jot("my jot")
    path = tmp_vault / rec["path"]
    h = _h(auth_headers, "plugin:familiar")
    assert client.delete(f"/v1/notes/{rec['id']}", headers=h).status_code == 428
    assert path.exists()
    etag = compute_etag(path.read_bytes())
    r = client.delete(f"/v1/notes/{rec['id']}", headers={**h, "If-Match": f'"{etag}"'})
    assert r.status_code == 204
    [row] = changes.list_changes()
    assert (row.actor, row.op) == ("plugin:familiar", "delete")


def test_a_plugin_creating_and_routing_a_jot_files_it_as_the_router(
    tmp_vault, client, auth_headers, monkeypatch
):
    # The follow-up move runs as worker:jot-router, not the plugin, so it
    # needs no etag and never 428s.
    monkeypatch.setattr(
        "ghostbrain.api.repo.notes_manual.route_event",
        lambda event, **kw: RoutingDecision(
            context="work", confidence=0.9, reasoning="work", method="llm",
            secondary_contexts=[],
        ),
    )
    r = client.post("/v1/notes", json={"body": "from a plugin", "route": True},
                    headers=_h(auth_headers, "plugin:familiar"))
    assert r.status_code == 200
    assert r.json()["routingStatus"] == "routed"
    assert r.json()["path"].startswith("20-contexts/work/notes/")
    rows = sorted(changes.list_changes(), key=lambda c: c.op)
    assert [(c.actor, c.op) for c in rows] == [
        ("plugin:familiar", "create"), ("worker:jot-router", "move")]


def test_a_plugin_rewriting_a_pre_b2_note_needs_the_etag_from_its_read(
        tmp_vault, client, auth_headers):
    # Written before B2: on disk, but no change row names it.
    note = write_note(tmp_vault, "Familiar/memory.md", "# Memory\nold\n")
    body = {"path": "Familiar/memory.md", "content": "# Memory\nnew\n"}
    r = client.put("/v1/notes", json=body, headers=_h(auth_headers, "plugin:familiar"))
    assert r.status_code == 428
    assert note.read_text() == "# Memory\nold\n"

    g = client.get("/v1/notes", params={"path": "Familiar/memory.md"}, headers=auth_headers)
    assert g.status_code == 200
    etag = g.json()["etag"]
    r = client.put("/v1/notes", json=body, headers=_h(auth_headers, "plugin:familiar", etag))
    assert r.status_code == 200
    assert note.read_text() == "# Memory\nnew\n"
    [row] = changes.list_changes()
    assert (row.actor, row.op, row.rel_path) == ("plugin:familiar", "modify", "Familiar/memory.md")
