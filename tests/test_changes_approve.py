"""B3: approve and reject held changes (spec B §3, §5)."""
from __future__ import annotations

from pathlib import Path

import pytest

from ghostbrain import vault_write
from ghostbrain.changes import approve as ap
from ghostbrain.changes import log as changes
from ghostbrain.changes import revert as rv
from ghostbrain.history import store
from ghostbrain.vault_write import (
    ASSISTANT,
    USER,
    compute_etag,
    plugin_actor,
    set_hold_policy,
    worker_actor,
    write,
)

REL = "20-contexts/work/plan.md"
NEW = "20-contexts/work/new.md"
V1 = b"---\ntitle: Plan\n---\n\nfirst draft\n"
FAMILIAR = plugin_actor("familiar")


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    note = root / REL
    note.parent.mkdir(parents=True)
    note.write_bytes(V1)
    return root


@pytest.fixture(autouse=True)
def _hold_everything():
    """Every recorded write is held, whatever it contains, so these tests
    exercise approval itself rather than the risk rules."""
    set_hold_policy(lambda _p: ["held for test"])
    yield
    set_hold_policy(None)


def _held_edit(text: str = "proposed draft") -> int:
    res = write(REL, body=text, actor=ASSISTANT, base_etag=compute_etag(V1), reason="polish")
    assert res.status == "pending"
    return int(res.change_id)


def test_approve_writes_the_proposal_as_the_original_actor(vault):
    cid = _held_edit()
    proposed = store.get_blob(changes.get(cid).pending_bytes_blob)
    res = ap.approve(cid)
    assert (vault / REL).read_bytes() == proposed
    assert res.path == REL and res.etag == compute_etag(proposed)
    row = res.change
    assert (row.id, row.status, row.actor, row.reason) == (cid, "applied", "assistant", "polish")
    assert store.get_blob(row.before_blob) == V1
    assert store.get_blob(row.after_blob) == proposed
    assert [c.id for c in changes.list_changes()] == [cid]  # no second row
    newest = store.list_snapshots(REL)[0]
    assert newest.actor == "assistant" and store.get_blob(newest.blob) == V1


def test_approval_never_re_holds(vault):
    cid = _held_edit()  # the policy still says "hold"
    assert ap.approve(cid).change.status == "applied"


def test_an_approved_change_can_be_reverted(vault):
    cid = _held_edit()
    ap.approve(cid)
    rv.revert(cid)
    assert (vault / REL).read_bytes() == V1


def test_approving_a_stale_proposal_refuses_and_writes_nothing(vault):
    cid = _held_edit()
    write(REL, body="my own edit", actor=USER)
    mine = (vault / REL).read_bytes()
    assert rv.changed_since(changes.get(cid)) is True
    with pytest.raises(ap.StaleProposal) as exc:
        ap.approve(cid)
    assert (exc.value.path, exc.value.expected, exc.value.current) == (REL, V1, mine)
    assert (vault / REL).read_bytes() == mine
    assert changes.get(cid).status == "pending"


def test_forced_approval_keeps_the_overwritten_version_in_history(vault):
    cid = _held_edit()
    write(REL, body="my own edit", actor=USER)
    mine = (vault / REL).read_bytes()
    ap.approve(cid, force=True)
    assert b"proposed draft" in (vault / REL).read_bytes()
    assert store.get_blob(store.list_snapshots(REL)[0].blob) == mine
    row = changes.get(cid)
    assert row.status == "applied" and store.get_blob(row.before_blob) == mine


def test_approve_a_created_note(vault):
    res = vault_write.write_new(NEW, "# New\n", actor=FAMILIAR)
    assert not (vault / NEW).exists()
    ap.approve(int(res.change_id))
    assert (vault / NEW).read_bytes() == b"# New\n"
    assert changes.created_by(NEW, "plugin:familiar") is True


def test_a_create_whose_path_was_taken_meanwhile_is_stale(vault):
    res = write(NEW, content="# New\n", op="create", actor=FAMILIAR)
    (vault / NEW).write_bytes(b"the user made it\n")
    with pytest.raises(ap.StaleProposal):
        ap.approve(int(res.change_id))
    assert (vault / NEW).read_bytes() == b"the user made it\n"


def test_approve_a_delete_and_a_move(vault):
    gone = write(REL, op="delete", actor=FAMILIAR, base_etag=compute_etag(V1))
    ap.approve(int(gone.change_id))
    assert not (vault / REL).exists()
    (vault / REL).write_bytes(V1)
    dest = "20-contexts/work/archive/plan.md"
    moved = write(REL, op="move", dest=dest, actor=FAMILIAR, base_etag=compute_etag(V1))
    res = ap.approve(int(moved.change_id))
    assert res.path == dest
    assert not (vault / REL).exists() and (vault / dest).read_bytes() == V1


def test_a_forced_delete_of_a_note_already_gone_just_closes_it(vault):
    gone = write(REL, op="delete", actor=FAMILIAR, base_etag=compute_etag(V1))
    (vault / REL).unlink()
    with pytest.raises(ap.StaleProposal):
        ap.approve(int(gone.change_id))
    assert ap.approve(int(gone.change_id), force=True).change.status == "applied"


def test_a_forced_worker_edit_of_a_note_now_gone_is_not_approvable(vault):
    res = write(REL, body="worker draft", actor=worker_actor("reversal"))
    cid = int(res.change_id)
    (vault / REL).unlink()
    with pytest.raises(ap.NotApprovable, match="no longer exists"):
        ap.approve(cid, force=True)
    assert not (vault / REL).exists()
    assert changes.get(cid).status == "pending"


def test_a_proposal_already_on_disk_is_marked_applied(vault):
    cid = _held_edit()
    proposed = store.get_blob(changes.get(cid).pending_bytes_blob)
    (vault / REL).write_bytes(proposed)
    res = ap.approve(cid, force=True)
    assert res.change.status == "applied"
    assert store.get_blob(res.change.after_blob) == proposed


def test_reject_writes_nothing_and_closes_the_row(vault):
    cid = _held_edit()
    row = ap.reject(cid)
    assert row.status == "rejected" and row.resolved_ts is not None
    assert (vault / REL).read_bytes() == V1
    with pytest.raises(ap.NotApprovable):
        ap.reject(cid)
    with pytest.raises(ap.NotApprovable):
        ap.approve(cid)


def test_unknown_and_applied_changes_cannot_be_approved(vault):
    with pytest.raises(rv.ChangeNotFound):
        ap.approve(999)
    with pytest.raises(rv.ChangeNotFound):
        ap.reject(999)
    set_hold_policy(lambda _p: [])
    res = write(REL, body="applied now", actor=ASSISTANT, base_etag=compute_etag(V1))
    with pytest.raises(ap.NotApprovable):
        ap.approve(int(res.change_id))


def test_a_collected_proposal_is_reported_gone(vault):
    cid = _held_edit()
    store._blob_path(changes.get(cid).pending_bytes_blob).unlink()
    with pytest.raises(rv.VersionGone):
        ap.approve(cid)
    assert changes.get(cid).status == "pending"


def test_user_writes_cannot_claim_an_approval(vault):
    with pytest.raises(ValueError):
        write(REL, body="x", actor=USER, approved_change=1)


def test_an_approval_naming_another_change_is_refused(vault):
    mine = _held_edit()  # the assistant's edit of REL
    other = int(write(NEW, content="# New\n", op="create", actor=FAMILIAR).change_id)
    with pytest.raises(ValueError):  # the row is the assistant's, not the plugin's
        write(REL, body="sneaky", actor=FAMILIAR, base_etag=compute_etag(V1), approved_change=mine)
    with pytest.raises(ValueError):  # the row is for another path
        write(REL, body="sneaky", actor=FAMILIAR, base_etag=compute_etag(V1), approved_change=other)
    with pytest.raises(ValueError):  # the row is an edit in place, not a move
        write(REL, op="move", dest=NEW, actor=ASSISTANT, base_etag=compute_etag(V1),
              approved_change=mine)
    assert (vault / REL).read_bytes() == V1 and not (vault / NEW).exists()
    assert (changes.get(mine).status, changes.get(other).status) == ("pending", "pending")
    assert {c.id for c in changes.list_changes()} == {mine, other}
    assert store.list_snapshots(REL) == []


def test_an_approval_naming_no_pending_change_is_refused(vault, monkeypatch):
    with pytest.raises(ValueError):
        write(REL, body="x", actor=ASSISTANT, base_etag=compute_etag(V1), approved_change=999)
    set_hold_policy(lambda _p: [])
    done = write(REL, body="applied now", actor=ASSISTANT, base_etag=compute_etag(V1))
    now = (vault / REL).read_bytes()
    with pytest.raises(ValueError):
        write(REL, body="again", actor=ASSISTANT, base_etag=compute_etag(now),
              approved_change=int(done.change_id))
    assert (vault / REL).read_bytes() == now
    assert changes.get(int(done.change_id)).status == "applied"
    assert len(changes.list_changes()) == 1

    def broken(_cid):
        raise OSError("change log unreadable")

    set_hold_policy(lambda _p: ["held for test"])
    cid = int(write(REL, body="held", actor=ASSISTANT, base_etag=compute_etag(now)).change_id)
    monkeypatch.setattr(changes, "get", broken)
    with pytest.raises(ValueError):  # fails closed
        write(REL, body="held", actor=ASSISTANT, base_etag=compute_etag(now), approved_change=cid)
    assert (vault / REL).read_bytes() == now


def test_a_move_whose_destination_was_taken_meanwhile_is_not_approvable(vault):
    dest = "20-contexts/work/archive/plan.md"
    cid = int(write(REL, op="move", dest=dest, actor=FAMILIAR, base_etag=compute_etag(V1)).change_id)
    (vault / dest).parent.mkdir(parents=True)
    (vault / dest).write_bytes(b"the user filed this here\n")
    for force in (False, True):
        with pytest.raises(ap.NotApprovable, match="now exists; reject this change"):
            ap.approve(cid, force=force)
    assert (vault / REL).read_bytes() == V1
    assert (vault / dest).read_bytes() == b"the user filed this here\n"
    assert changes.get(cid).status == "pending"


def test_a_forced_move_of_a_vanished_note_creates_it_at_the_destination(vault):
    dest = "20-contexts/work/archive/plan.md"
    cid = int(write(REL, op="move", dest=dest, actor=FAMILIAR, base_etag=compute_etag(V1)).change_id)
    (vault / REL).unlink()
    res = ap.approve(cid, force=True)  # the approval names this row from the destination
    assert res.path == dest and (vault / dest).read_bytes() == V1
    assert changes.get(cid).status == "applied"
