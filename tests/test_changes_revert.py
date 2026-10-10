"""B2: revert and undo of change-log rows."""
from __future__ import annotations

from pathlib import Path

import pytest

from ghostbrain import vault_write
from ghostbrain.changes import log as changes
from ghostbrain.changes import revert as rv
from ghostbrain.history import store
from ghostbrain.vault_write import (
    ASSISTANT,
    USER,
    WriteConflict,
    compute_etag,
    plugin_actor,
    set_hold_policy,
    write,
    write_new,
)

REL = "20-contexts/work/plan.md"
DEST = "20-contexts/work/projects/plan.md"
V1 = b"---\ntitle: Plan\n---\n\nfirst draft\n"


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    note = root / REL
    note.parent.mkdir(parents=True)
    note.write_bytes(V1)
    return root


@pytest.fixture(autouse=True)
def _revert_mechanics_only():
    """These tests move and delete notes the actor didn't create, which B3's
    risk rules hold. Revert mechanics are what is under test here."""
    set_hold_policy(lambda _p: [])
    yield
    set_hold_policy(None)


def _ai_edit(text: str = "polished draft") -> int:
    res = write(REL, body=text, actor=ASSISTANT, base_etag=vault_write.current_etag(REL),
                reason="polish")
    assert res.change_id is not None
    return int(res.change_id)


def _move() -> int:
    res = write(REL, op="move", dest=DEST, fields={"context": "work"},
                actor=plugin_actor("familiar"), base_etag=compute_etag(V1))
    return int(res.change_id)


def test_revert_restores_the_before_bytes_and_marks_the_row(vault):
    cid = _ai_edit()
    after = (vault / REL).read_bytes()
    res = rv.revert(cid)
    assert (vault / REL).read_bytes() == V1
    assert res.change.status == "reverted" and res.change.resolved_ts is not None
    assert res.path == REL and res.etag == compute_etag(V1)
    newest = store.list_snapshots(REL)[0]
    assert newest.actor == "restore" and store.get_blob(newest.blob) == after
    assert [c.id for c in changes.list_changes()] == [cid]  # a revert adds no row


def test_revert_is_refused_when_the_note_changed_since(vault):
    cid = _ai_edit()
    after = (vault / REL).read_bytes()
    write(REL, body="my later edit", actor=USER)
    mine = (vault / REL).read_bytes()
    assert rv.changed_since(changes.get(cid)) is True
    with pytest.raises(rv.ChangedSince) as exc:
        rv.revert(cid)
    assert (exc.value.path, exc.value.expected, exc.value.current) == (REL, after, mine)
    assert (vault / REL).read_bytes() == mine
    assert changes.get(cid).status == "applied"


def test_forced_revert_keeps_the_overwritten_version_in_history(vault):
    cid = _ai_edit()
    write(REL, body="my later edit", actor=USER)
    mine = (vault / REL).read_bytes()
    rv.revert(cid, force=True)
    assert (vault / REL).read_bytes() == V1
    assert store.get_blob(store.list_snapshots(REL)[0].blob) == mine


def test_undo_reapplies_and_round_trips(vault):
    cid = _ai_edit()
    after = (vault / REL).read_bytes()
    assert rv.changed_since(changes.get(cid)) is False
    rv.revert(cid)
    res = rv.undo_revert(cid)
    assert (vault / REL).read_bytes() == after
    assert res.change.status == "applied" and res.change.resolved_ts is None
    rv.revert(cid)
    assert (vault / REL).read_bytes() == V1


def test_round_trip_is_byte_exact_without_a_trailing_newline_and_with_crlf(vault):
    raw = b"---\r\ntitle: Plan\r\n---\r\n\r\nno newline at the end"
    (vault / REL).write_bytes(raw)
    cid = _ai_edit("ai text")
    after = (vault / REL).read_bytes()
    rv.revert(cid)
    assert (vault / REL).read_bytes() == raw
    rv.undo_revert(cid)
    assert (vault / REL).read_bytes() == after


def test_revert_of_a_created_note_deletes_it_and_undo_brings_it_back(vault):
    res = write_new("20-contexts/work/new.md", "# New\n", actor=ASSISTANT)
    cid = int(res.change_id)
    rv.revert(cid)
    assert not (vault / "20-contexts/work/new.md").exists()
    rv.undo_revert(cid)
    assert (vault / "20-contexts/work/new.md").read_bytes() == b"# New\n"


def test_revert_of_a_delete_recreates_the_note(vault):
    res = write(REL, op="delete", actor=ASSISTANT, base_etag=compute_etag(V1))
    rv.revert(int(res.change_id))
    assert (vault / REL).read_bytes() == V1


def test_revert_of_a_move_moves_it_back(vault):
    cid = _move()
    rv.revert(cid)
    assert (vault / REL).read_bytes() == V1
    assert not (vault / DEST).exists()
    rv.undo_revert(cid)
    assert not (vault / REL).exists() and (vault / DEST).exists()


def test_revert_of_a_move_never_overwrites_a_note_now_at_the_old_path(vault):
    cid = _move()
    (vault / REL).write_bytes(b"someone else\n")
    with pytest.raises(WriteConflict):
        rv.revert(cid)
    assert (vault / REL).read_bytes() == b"someone else\n"
    assert (vault / DEST).exists()
    assert changes.get(cid).status == "applied"


def test_states_that_cannot_be_reverted(vault):
    with pytest.raises(rv.ChangeNotFound):
        rv.revert(999)
    cid = _ai_edit()
    with pytest.raises(rv.NotRevertable):
        rv.undo_revert(cid)
    pid = changes.record(actor="assistant", rel_path=REL, op="modify", status="pending",
                         pending_bytes_blob=store.put_blob(b"x\n"))
    with pytest.raises(rv.NotRevertable):
        rv.revert(pid)
    assert rv.expected_state(changes.get(pid)) == rv.held_flip(changes.get(pid))


def test_a_collected_version_is_reported_gone(vault):
    cid = _ai_edit()
    store._blob_path(changes.get(cid).before_blob).unlink()
    with pytest.raises(rv.VersionGone):
        rv.revert(cid)
    assert changes.get(cid).status == "applied"
