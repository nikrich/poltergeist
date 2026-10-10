"""Page-history routes + historyOk on saves (spec A3)."""
from __future__ import annotations

from datetime import datetime, timezone

from ghostbrain import vault_write
from ghostbrain.api.repo.notes_manual import write_inbox_jot
from ghostbrain.api.tests.conftest import write_note
from ghostbrain.history import store
from ghostbrain.vault_write import compute_etag, worker_actor

REL = "20-contexts/work/notes/plan.md"
V1 = "---\ntitle: Plan\n---\n\nfirst draft\n"


def _save(client, headers, body, if_match=None):
    h = dict(headers)
    if if_match:
        h["If-Match"] = f'"{if_match}"'
    return client.patch("/v1/notes/body", json={"path": REL, "body": body}, headers=h)


def _history(client, headers):
    return client.get("/v1/notes/history", params={"path": REL}, headers=headers)


def test_saving_records_a_version_and_lists_it(tmp_vault, client, auth_headers):
    write_note(tmp_vault, REL, V1)
    r = _save(client, auth_headers, "second draft")
    assert r.status_code == 200 and r.json()["historyOk"] is True
    h = _history(client, auth_headers)
    assert h.status_code == 200
    data = h.json()
    assert data["path"] == REL
    [item] = data["items"]
    assert item["actor"] == "user" and item["path"] == REL
    assert item["blob"] == store.blob_id(V1.encode())
    assert item["size"] == len(V1.encode())


def test_keep_mine_over_http_keeps_their_version(tmp_vault, client, auth_headers):
    note = write_note(tmp_vault, REL, V1)
    _save(client, auth_headers, "mine 1")
    theirs = "---\ntitle: Plan\n---\n\ntheirs\n"
    note.write_bytes(theirs.encode())
    fresh = compute_etag(note.read_bytes())
    assert _save(client, auth_headers, "mine 2", if_match=fresh).status_code == 200
    blobs = [i["blob"] for i in _history(client, auth_headers).json()["items"]]
    assert store.blob_id(theirs.encode()) in blobs


def test_blob_returns_the_version_and_the_current_file(tmp_vault, client, auth_headers):
    write_note(tmp_vault, REL, V1)
    _save(client, auth_headers, "second draft")
    blob = store.blob_id(V1.encode())
    r = client.get("/v1/notes/history/blob", params={"path": REL, "blob": blob},
                   headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["content"] == V1
    assert "second draft" in data["current"]


def test_blob_of_another_note_is_404(tmp_vault, client, auth_headers):
    write_note(tmp_vault, REL, V1)
    _save(client, auth_headers, "second draft")
    write_note(tmp_vault, "20-contexts/work/notes/other.md", "x\n")
    r = client.get("/v1/notes/history/blob",
                   params={"path": "20-contexts/work/notes/other.md",
                           "blob": store.blob_id(V1.encode())},
                   headers=auth_headers)
    assert r.status_code == 404


def test_malformed_blob_id_is_422(tmp_vault, client, auth_headers):
    r = client.get("/v1/notes/history/blob", params={"path": REL, "blob": "../x"},
                   headers=auth_headers)
    assert r.status_code == 422


def test_history_path_outside_the_vault_is_400(tmp_vault, client, auth_headers):
    r = client.get("/v1/notes/history", params={"path": "../secrets.md"}, headers=auth_headers)
    assert r.status_code == 400


def test_restore_snapshots_current_then_writes_the_version(tmp_vault, client, auth_headers):
    note = write_note(tmp_vault, REL, V1)
    _save(client, auth_headers, "second draft")
    before_restore = note.read_bytes()
    blob = store.blob_id(V1.encode())
    r = client.post("/v1/notes/history/restore", json={"path": REL, "blob": blob},
                    headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert note.read_bytes() == V1.encode()
    assert data["body"] == "first draft"
    assert data["etag"] == compute_etag(V1.encode())
    assert data["restored"] == blob and data["historyOk"] is True
    newest = _history(client, auth_headers).json()["items"][0]
    assert newest["actor"] == "restore"
    assert newest["blob"] == store.blob_id(before_restore)


def test_restore_with_stale_if_match_is_409_and_leaves_the_file(tmp_vault, client, auth_headers):
    note = write_note(tmp_vault, REL, V1)
    _save(client, auth_headers, "second draft")
    current = note.read_bytes()
    r = client.post("/v1/notes/history/restore",
                    json={"path": REL, "blob": store.blob_id(V1.encode())},
                    headers={**auth_headers, "If-Match": '"0000000000000000"'})
    assert r.status_code == 409
    assert note.read_bytes() == current


def test_restore_of_an_unknown_version_is_404(tmp_vault, client, auth_headers):
    write_note(tmp_vault, REL, V1)
    r = client.post("/v1/notes/history/restore", json={"path": REL, "blob": "a" * 64},
                    headers=auth_headers)
    assert r.status_code == 404


def test_restore_of_a_collected_version_is_404(tmp_vault, client, auth_headers):
    write_note(tmp_vault, REL, V1)
    _save(client, auth_headers, "second draft")
    blob = store.blob_id(V1.encode())
    store._blob_path(blob).unlink()
    r = client.post("/v1/notes/history/restore", json={"path": REL, "blob": blob},
                    headers=auth_headers)
    assert r.status_code == 404
    assert r.json()["detail"] == "this version is no longer available"


def test_jot_save_reports_history_ok(tmp_vault, client, auth_headers):
    rec = write_inbox_jot("hello jot", captured_at=datetime.now(timezone.utc))
    r = client.patch(f"/v1/notes/{rec['id']}", json={"body": "hello again"},
                     headers=auth_headers)
    assert r.status_code == 200 and r.json()["historyOk"] is True
    items = client.get("/v1/notes/history", params={"path": rec["path"]},
                       headers=auth_headers).json()["items"]
    assert len(items) == 1


def test_user_save_survives_a_history_failure(tmp_vault, client, auth_headers, monkeypatch):
    note = write_note(tmp_vault, REL, V1)

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(store, "snapshot", boom)
    r = _save(client, auth_headers, "kept anyway")
    assert r.status_code == 200 and r.json()["historyOk"] is False
    assert b"kept anyway" in note.read_bytes()


def test_plugin_write_is_refused_when_history_fails(tmp_vault, client, auth_headers, monkeypatch):
    note = write_note(tmp_vault, REL, V1)

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(store, "snapshot", boom)
    r = client.put("/v1/notes", json={"path": REL, "content": "plugin text"},
                   headers={**auth_headers, "If-Match": f'"{compute_etag(V1.encode())}"'})
    assert r.status_code == 500
    assert r.json()["detail"] == "history unavailable"
    assert note.read_bytes() == V1.encode()


INBOX = "20-contexts/inbox/notes/jot.md"
ROUTED = "20-contexts/work/notes/jot.md"
PRE_ROUTE = "---\ncontext: inbox\nroutingStatus: pending\n---\n\nold body\n"


def test_restoring_a_version_carried_by_a_move_restores_only_the_body(
    tmp_vault, client, auth_headers,
):
    write_note(tmp_vault, INBOX, PRE_ROUTE)
    vault_write.write(INBOX, op="move", dest=ROUTED, actor=worker_actor("router"),
                      fields={"context": "work", "routingStatus": "routed"},
                      body="new body")
    items = client.get("/v1/notes/history", params={"path": ROUTED},
                       headers=auth_headers).json()["items"]
    [carried] = [i for i in items if i["path"] == INBOX]
    r = client.post("/v1/notes/history/restore",
                    json={"path": ROUTED, "blob": carried["blob"]}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["body"] == "old body"
    meta = vault_write.read(ROUTED).metadata()
    assert meta["context"] == "work" and meta["routingStatus"] == "routed"
    assert not (tmp_vault / INBOX).exists()


def test_restore_is_500_and_leaves_the_file_when_history_is_unavailable(
    tmp_vault, client, auth_headers, monkeypatch,
):
    note = write_note(tmp_vault, REL, V1)
    _save(client, auth_headers, "second draft")
    current = note.read_bytes()
    blob = store.blob_id(V1.encode())

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(store, "snapshot", boom)
    r = client.post("/v1/notes/history/restore", json={"path": REL, "blob": blob},
                    headers=auth_headers)
    assert r.status_code == 500
    assert r.json()["detail"] == "history unavailable"
    assert note.read_bytes() == current
