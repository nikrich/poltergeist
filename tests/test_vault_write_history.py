"""vault_write takes a page-history snapshot before every changing write (A3)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ghostbrain import vault_write
from ghostbrain.history import store
from ghostbrain.vault_write import (
    ASSISTANT,
    RESTORE,
    USER,
    HistoryUnavailable,
    compute_etag,
    parse_actor,
    set_hold_policy,
    write,
)

T0 = datetime(2026, 10, 9, 10, 0, tzinfo=timezone.utc)
REL = "20-contexts/work/plan.md"
V1 = b"---\ntitle: Plan\n---\n\nfirst draft\n"


@pytest.fixture
def hv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("VAULT_PATH", str(vault))
    now = {"t": T0}
    monkeypatch.setattr(store, "_now", lambda: now["t"])
    note = vault / REL
    note.parent.mkdir(parents=True)
    note.write_bytes(V1)

    def advance(**kw: float) -> None:
        now["t"] = now["t"] + timedelta(**kw)

    return note, advance


def _versions(rel: str = REL) -> list[bytes]:
    return [store.get_blob(s.blob) for s in store.list_snapshots(rel)]


def test_user_body_save_snapshots_the_previous_file_bytes(hv):
    res = write(REL, body="second draft", actor=USER, reason="edited in the editor")
    assert res.history_ok is True
    [snap] = store.list_snapshots(REL)
    assert store.get_blob(snap.blob) == V1
    assert (snap.actor, snap.reason, snap.rel_path) == ("user", "edited in the editor", REL)


def test_identical_save_takes_no_snapshot(hv):
    write(REL, content=V1.decode(), actor=USER)
    assert store.list_snapshots(REL) == []


def test_create_takes_no_snapshot(hv):
    write("20-contexts/work/new.md", content="hello\n", op="create", actor=ASSISTANT)
    assert store.list_snapshots("20-contexts/work/new.md") == []


def test_autosaves_coalesce_but_an_outside_edit_is_kept(hv):
    note, advance = hv
    write(REL, body="v2", actor=USER)
    advance(seconds=20)
    write(REL, body="v3", actor=USER)
    assert _versions() == [V1]
    theirs = b"---\ntitle: Plan\n---\n\ntheirs\n"
    note.write_bytes(theirs)  # an Obsidian edit
    advance(seconds=20)
    # Keep mine: overwrite on the fresh etag (B1 deferred this snapshot to A3).
    write(REL, body="mine", actor=USER, base_etag=compute_etag(theirs))
    assert _versions() == [theirs, V1]


def test_assistant_writes_snapshot_every_time(hv):
    _, advance = hv
    for i in range(3):
        write(REL, body=f"ai {i}", actor=ASSISTANT, base_etag=vault_write.current_etag(REL))
        advance(seconds=1)
    assert len(store.list_snapshots(REL)) == 3


def test_non_user_write_is_refused_when_history_fails(hv, monkeypatch):
    note, _ = hv

    def boom(*_a, **_k):
        raise store.HistoryUnavailable("disk full")

    monkeypatch.setattr(store, "snapshot", boom)
    with pytest.raises(HistoryUnavailable):
        write(REL, body="ai edit", actor=ASSISTANT, base_etag=compute_etag(V1))
    assert note.read_bytes() == V1


def test_user_write_proceeds_when_history_fails(hv, monkeypatch):
    note, _ = hv

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(store, "snapshot", boom)
    res = write(REL, body="my edit", actor=USER)
    assert res.history_ok is False
    assert b"my edit" in note.read_bytes()


def test_restore_is_an_actor_that_is_never_coalesced(hv):
    _, advance = hv
    assert parse_actor("restore") == RESTORE == "restore"
    write(REL, body="v2", actor=USER)
    advance(seconds=5)
    write(REL, content=V1.decode(), actor=RESTORE, reason="restored")
    assert [s.actor for s in store.list_snapshots(REL)] == ["restore", "user"]


def test_delete_keeps_the_deleted_version(hv):
    write(REL, op="delete", actor=USER)
    assert _versions() == [V1]


def test_move_carries_history_to_the_new_path(hv):
    _, advance = hv
    write(REL, body="edited", actor=USER)
    advance(minutes=6)
    dest = "20-contexts/work/projects/plan.md"
    res = write(REL, op="move", dest=dest, fields={"context": "work"}, actor=USER)
    assert res.path == dest and res.history_ok is True
    assert store.list_snapshots(REL) == []
    versions = _versions(dest)
    assert versions[-1] == V1 and len(versions) == 2


def test_html_writes_are_snapshotted_too(hv):
    rel = "90-meta/generated/doc.html"
    set_hold_policy(lambda _p: [])  # snapshot mechanics only; B3 holds mcp edits to 90-meta
    try:
        write(rel, content="<p>one</p>", op="create", actor="mcp")
        write(rel, content="<p>two</p>", actor="mcp")
    finally:
        set_hold_policy(None)
    assert _versions(rel) == [b"<p>one</p>"]


def test_package_exports_restore_and_history_unavailable():
    assert vault_write.RESTORE == "restore"
    assert vault_write.HistoryUnavailable is store.HistoryUnavailable
