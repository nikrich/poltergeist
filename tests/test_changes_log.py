"""Change-log store (spec B §4, slice B2)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ghostbrain.changes import log as changes
from ghostbrain.history import store

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
B = "a" * 64
C = "b" * 64
D = "c" * 64


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch):
    now = {"t": NOW}
    monkeypatch.setattr(changes, "_now", lambda: now["t"])

    def set_time(t: datetime) -> None:
        now["t"] = t

    return set_time


def test_db_lives_in_the_state_dir(tmp_path):
    # Root conftest: GHOSTBRAIN_STATE_DIR = tmp_path/state.
    assert changes.db_path() == (tmp_path / "state").resolve() / "changes.db"


def test_record_and_get_round_trip(clock):
    cid = changes.record(
        actor="assistant", rel_path="a.md", op="modify", reason="polish",
        before_blob=B, after_blob=C,
    )
    c = changes.get(cid)
    assert c == changes.Change(
        id=cid, ts=NOW.isoformat(), actor="assistant", rel_path="a.md", dest_path=None,
        op="modify", reason="polish", before_blob=B, after_blob=C, pending_bytes_blob=None,
        status="applied", risk_reasons=(), resolved_ts=None,
    )
    assert c.current_path == "a.md"
    assert c.to_api() == {
        "id": cid, "ts": NOW.isoformat(), "actor": "assistant", "path": "a.md",
        "destPath": None, "op": "modify", "reason": "polish", "status": "applied",
        "riskReasons": [], "resolvedTs": None,
    }
    assert changes.get(cid + 1) is None


def test_record_rejects_unknown_ops_and_final_statuses():
    with pytest.raises(ValueError):
        changes.record(actor="mcp", rel_path="a.md", op="rename")
    with pytest.raises(ValueError):
        changes.record(actor="mcp", rel_path="a.md", op="create", status="reverted")


def test_list_is_newest_first_and_filters(clock):
    a = changes.record(actor="assistant", rel_path="20-contexts/work/plan.md", op="modify")
    clock(NOW + timedelta(hours=1))
    p = changes.record(actor="plugin:familiar", rel_path="Familiar/100%_done.md", op="create")
    clock(NOW + timedelta(hours=2))
    m = changes.record(
        actor="mcp", rel_path="inbox/j.md", dest_path="20-contexts/work/j.md", op="move",
    )
    assert changes.get(m).current_path == "20-contexts/work/j.md"
    assert [c.id for c in changes.list_changes()] == [m, p, a]
    assert [c.id for c in changes.list_changes(limit=1)] == [m]
    assert [c.id for c in changes.list_changes(actor="plugin")] == [p]
    assert [c.id for c in changes.list_changes(actor="plugin:familiar")] == [p]
    assert [c.id for c in changes.list_changes(actor="assistant")] == [a]
    assert [c.id for c in changes.list_changes(path_query="100%")] == [p]
    assert changes.list_changes(path_query="100%x") == []
    assert [c.id for c in changes.list_changes(path_query="WORK")] == [m, a]
    assert [c.id for c in changes.list_changes(since=NOW + timedelta(minutes=30))] == [m, p]
    assert [c.id for c in changes.list_changes(status="applied")] == [m, p, a]


def test_status_changes_are_compare_and_set(clock):
    cid = changes.record(actor="assistant", rel_path="a.md", op="modify")
    clock(NOW + timedelta(minutes=5))
    assert changes.set_status(cid, "reverted", expect=("applied",)) is True
    assert changes.set_status(cid, "reverted", expect=("applied",)) is False
    c = changes.get(cid)
    assert c.status == "reverted"
    assert c.resolved_ts == (NOW + timedelta(minutes=5)).isoformat()
    assert changes.set_status(cid, "applied", expect=("reverted",)) is True
    assert changes.get(cid).resolved_ts is None
    with pytest.raises(ValueError):
        changes.set_status(cid, "gone", expect=("applied",))


def test_counts_and_risk_reasons():
    changes.record(actor="assistant", rel_path="a.md", op="modify")
    changes.record(
        actor="assistant", rel_path="b.md", op="modify", status="pending",
        risk_reasons=["touches 90-meta"],
    )
    assert changes.counts() == {"applied": 1, "pending": 1}
    [pending] = changes.list_changes(status="pending")
    assert pending.risk_reasons == ("touches 90-meta",)


def test_last_after_blob_is_the_actors_latest_applied_write_at_that_path():
    changes.record(actor="plugin:familiar", rel_path="F/m.md", op="create", after_blob=B)
    changes.record(
        actor="plugin:familiar", rel_path="F/m.md", op="modify", before_blob=B, after_blob=C,
    )
    changes.record(
        actor="plugin:other", rel_path="F/m.md", op="modify", before_blob=C, after_blob=D,
    )
    assert changes.last_after_blob("F/m.md", "plugin:familiar") == C
    assert changes.last_after_blob("F/m.md", "plugin:other") == D
    assert changes.last_after_blob("F/x.md", "plugin:familiar") is None
    mv = changes.record(
        actor="mcp", rel_path="in/j.md", dest_path="w/j.md", op="move",
        before_blob=B, after_blob=C,
    )
    assert changes.last_after_blob("w/j.md", "mcp") == C
    changes.set_status(mv, "reverted", expect=("applied",))
    assert changes.last_after_blob("w/j.md", "mcp") is None


def test_referenced_blobs_cover_every_blob_column():
    changes.record(actor="assistant", rel_path="a.md", op="modify", before_blob=B, after_blob=C)
    changes.record(
        actor="assistant", rel_path="b.md", op="modify", status="pending",
        before_blob=B, pending_bytes_blob=D,
    )
    assert changes.referenced_blobs() == sorted([B, C, D])


def test_referenced_blobs_without_a_db_is_empty_and_creates_nothing():
    assert not changes.db_path().exists()
    assert changes.referenced_blobs() == []
    assert not changes.db_path().exists()


def test_prune_drops_rows_older_than_a_year_but_never_pending(clock):
    clock(NOW - timedelta(days=400))
    old = changes.record(actor="assistant", rel_path="a.md", op="modify")
    held = changes.record(actor="assistant", rel_path="b.md", op="modify", status="pending")
    clock(NOW - timedelta(days=10))
    recent = changes.record(actor="assistant", rel_path="c.md", op="modify")
    assert changes.prune(NOW) == 1
    assert {c.id for c in changes.list_changes()} == {held, recent}
    assert changes.get(old) is None


def test_ids_are_never_reused_after_a_prune(clock):
    clock(NOW - timedelta(days=400))
    first = changes.record(actor="assistant", rel_path="a.md", op="modify")
    changes.prune(NOW)
    clock(NOW)
    assert changes.record(actor="assistant", rel_path="a.md", op="modify") > first


def test_degraded_marker_round_trip(clock):
    assert changes.degraded() is None
    changes.mark_degraded("insert failed")
    assert changes.degraded() == NOW.isoformat()
    changes.clear_degraded()
    assert changes.degraded() is None


def test_an_unusable_state_dir_raises_change_log_error(tmp_path, monkeypatch):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(blocker / "state"))
    with pytest.raises(changes.ChangeLogError):
        changes.list_changes()


def test_registered_as_a_history_ref_source():
    changes.register_with_history()
    changes.record(actor="assistant", rel_path="a.md", op="modify", after_blob=B)
    assert list(store._ref_sources["changes"]()) == [B]


def test_created_by_follows_the_actors_own_moves():
    changes.record(actor="plugin:familiar", rel_path="F/a.md", op="create", after_blob=B)
    assert changes.created_by("F/a.md", "plugin:familiar") is True
    assert changes.created_by("F/a.md", "plugin:other") is False
    changes.record(actor="plugin:familiar", rel_path="F/a.md", dest_path="F/b.md", op="move",
                   before_blob=B, after_blob=B)
    changes.record(actor="plugin:familiar", rel_path="F/b.md", dest_path="F/c.md", op="move",
                   before_blob=B, after_blob=B)
    assert changes.created_by("F/c.md", "plugin:familiar") is True


def test_moving_someone_elses_note_does_not_make_it_yours():
    changes.record(actor="plugin:familiar", rel_path="notes/user.md", dest_path="F/user.md",
                   op="move", before_blob=B, after_blob=B)
    assert changes.created_by("F/user.md", "plugin:familiar") is False


def test_a_reverted_or_pending_create_is_not_ownership():
    cid = changes.record(actor="assistant", rel_path="a.md", op="create", after_blob=B)
    changes.set_status(cid, "reverted", expect=("applied",))
    changes.record(actor="assistant", rel_path="b.md", op="create", status="pending",
                   pending_bytes_blob=B)
    assert changes.created_by("a.md", "assistant") is False
    assert changes.created_by("b.md", "assistant") is False


def test_a_move_cycle_terminates():
    changes.record(actor="mcp", rel_path="x.md", dest_path="y.md", op="move")
    changes.record(actor="mcp", rel_path="y.md", dest_path="x.md", op="move")
    assert changes.created_by("x.md", "mcp") is False


def test_apply_pending_fills_the_blobs_once():
    cid = changes.record(
        actor="assistant", rel_path="a.md", op="modify", status="pending",
        before_blob=B, pending_bytes_blob=C, risk_reasons=["edits a template"],
    )
    assert changes.apply_pending(cid, before_blob=D, after_blob=C) is True
    row = changes.get(cid)
    assert (row.status, row.before_blob, row.after_blob, row.pending_bytes_blob,
            row.resolved_ts) == ("applied", D, C, C, None)
    assert row.risk_reasons == ("edits a template",)
    assert changes.apply_pending(cid, before_blob=D, after_blob=C) is False


def test_a_path_vacated_by_the_actors_own_move_is_not_owned():
    changes.record(actor="plugin:p", rel_path="F/a.md", op="create", after_blob=B)
    changes.record(actor="plugin:p", rel_path="F/a.md", dest_path="F/b.md", op="move",
                   before_blob=B, after_blob=B)
    assert changes.created_by("F/a.md", "plugin:p") is False
    assert changes.created_by("F/b.md", "plugin:p") is True


def test_an_own_delete_ends_ownership_even_if_someone_else_recreates():
    changes.record(actor="plugin:p", rel_path="G/x.md", op="create", after_blob=B)
    changes.record(actor="plugin:p", rel_path="G/x.md", op="delete", before_blob=B)
    assert changes.created_by("G/x.md", "plugin:p") is False
    changes.record(actor="user", rel_path="G/x.md", op="create", after_blob=C)
    assert changes.created_by("G/x.md", "plugin:p") is False


def test_a_move_recorded_before_the_create_does_not_chain():
    changes.record(actor="plugin:p", rel_path="notes/u.md", dest_path="F/u.md", op="move",
                   before_blob=B, after_blob=B)
    changes.record(actor="plugin:p", rel_path="notes/u.md", op="create", after_blob=C)
    assert changes.created_by("F/u.md", "plugin:p") is False


def test_another_actors_later_move_into_the_path_breaks_ownership():
    changes.record(actor="plugin:p", rel_path="F/a.md", op="create", after_blob=B)
    changes.record(actor="user", rel_path="notes/z.md", dest_path="F/a.md", op="move",
                   before_blob=C, after_blob=C)
    assert changes.created_by("F/a.md", "plugin:p") is False
