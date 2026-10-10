"""History store: content-addressed blobs, per-note log, coalescing (spec A3)."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone

import pytest

from ghostbrain import history
from ghostbrain.history import store

T0 = datetime(2026, 10, 9, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch):
    now = {"t": T0}
    monkeypatch.setattr(store, "_now", lambda: now["t"])

    def advance(**kw: float) -> None:
        now["t"] = now["t"] + timedelta(**kw)

    return advance


def test_history_dir_lives_in_app_state_not_the_vault(tmp_path):
    # Root conftest: GHOSTBRAIN_STATE_DIR=tmp_path/state, VAULT_PATH=tmp_path/vault.
    assert store.history_dir() == (tmp_path / "state").resolve() / "history"
    assert history.history_dir() == store.history_dir()


def test_put_blob_dedupes_identical_content():
    a = store.put_blob(b"same\n")
    b = store.put_blob(b"same\n")
    assert a == b == store.blob_id(b"same\n")
    assert len(list((store.history_dir() / "blobs").glob("*.md"))) == 1
    assert store.get_blob(a) == b"same\n"
    assert store.has_blob(a)


def test_get_blob_rejects_bad_ids_and_reports_missing():
    with pytest.raises(ValueError):
        store.get_blob("../../secrets")
    with pytest.raises(ValueError):
        store.get_blob("A" * 64)
    with pytest.raises(store.BlobNotFound):
        store.get_blob("0" * 64)
    assert not store.has_blob("0" * 64)


def test_snapshot_appends_and_lists_newest_first(clock):
    s1 = store.snapshot("a.md", b"v1\n", actor="assistant", reason="r1", after=b"v2\n")
    clock(seconds=1)
    s2 = store.snapshot("a.md", b"v2\n", actor="mcp", reason="r2", after=b"v3\n")
    got = store.list_snapshots("a.md")
    assert [s.blob for s in got] == [s2.blob, s1.blob]
    assert got[0].actor == "mcp" and got[0].reason == "r2" and got[0].size == 3
    assert got[1].ts == T0.isoformat()
    assert store.list_snapshots("a.md", limit=1) == [got[0]]
    assert store.list_snapshots("other.md") == []


def test_snapshot_to_dict_is_the_log_line_shape(clock):
    s = store.snapshot("a.md", b"v1\n", actor="assistant", reason="x")
    assert s.to_dict() == {
        "ts": T0.isoformat(), "rel_path": "a.md", "blob": store.blob_id(b"v1\n"),
        "actor": "assistant", "reason": "x", "size": 3,
    }
    line = store._log_path("a.md").read_text(encoding="utf-8").strip()
    assert json.loads(line) == s.to_dict()


def test_user_snapshots_coalesce_within_five_minutes(clock):
    assert store.snapshot("a.md", b"v1\n", actor="user", after=b"v2\n") is not None
    clock(minutes=1)
    assert store.snapshot("a.md", b"v2\n", actor="user", after=b"v3\n") is None
    clock(minutes=3, seconds=59)  # 4:59 since the kept snapshot
    assert store.snapshot("a.md", b"v3\n", actor="user", after=b"v4\n") is None
    clock(seconds=2)  # 5:01
    s = store.snapshot("a.md", b"v4\n", actor="user", after=b"v5\n")
    assert s is not None and store.get_blob(s.blob) == b"v4\n"
    assert len(store.list_snapshots("a.md")) == 2


def test_user_save_after_a_foreign_change_is_never_coalesced(clock):
    """Keep mine / an Obsidian edit: disk no longer holds what our last write
    left there, so the foreign version must be kept."""
    store.snapshot("a.md", b"v1\n", actor="user", after=b"mine\n")
    clock(seconds=30)
    s = store.snapshot("a.md", b"theirs\n", actor="user", after=b"mine again\n")
    assert s is not None and store.get_blob(s.blob) == b"theirs\n"


def test_non_user_actors_never_coalesce(clock):
    for i in range(3):
        snap = store.snapshot(
            "a.md", f"v{i}\n".encode(), actor="assistant", after=f"v{i + 1}\n".encode()
        )
        assert snap is not None
    assert len(store.list_snapshots("a.md")) == 3


def test_user_save_after_a_non_user_write_is_kept(clock):
    store.snapshot("a.md", b"v1\n", actor="assistant", after=b"ai\n")
    clock(seconds=10)
    assert store.snapshot("a.md", b"ai\n", actor="user", after=b"me\n") is not None


def test_user_delete_is_never_coalesced(clock):
    store.snapshot("a.md", b"v1\n", actor="user", after=b"v2\n")
    clock(seconds=5)
    s = store.snapshot("a.md", b"v2\n", actor="user", after=None)
    assert s is not None and store.get_blob(s.blob) == b"v2\n"


def test_clock_going_backwards_does_not_coalesce(clock):
    store.snapshot("a.md", b"v1\n", actor="user", after=b"v2\n")
    clock(minutes=-1)
    assert store.snapshot("a.md", b"v2\n", actor="user", after=b"v3\n") is not None


def test_corrupt_log_lines_are_skipped_and_appends_start_on_a_new_line(clock):
    store.snapshot("a.md", b"v1\n", actor="assistant")
    with store._log_path("a.md").open("a", encoding="utf-8") as fh:
        fh.write('{"ts": "broken')  # crash mid-append: no trailing newline
    clock(seconds=1)
    store.snapshot("a.md", b"v2\n", actor="assistant")
    got = store.list_snapshots("a.md")
    assert [store.get_blob(s.blob) for s in got] == [b"v2\n", b"v1\n"]


def test_unicode_paths_and_reasons_round_trip(clock):
    rel = "20-contexts/wörk/ñote.md"
    store.snapshot(rel, "é\n".encode(), actor="assistant", reason="polished “intro”")
    [s] = store.list_snapshots(rel)
    assert s.rel_path == rel and s.reason == "polished “intro”"


def test_io_failures_raise_history_unavailable(monkeypatch):
    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(store, "_atomic_write", boom)
    with pytest.raises(store.HistoryUnavailable):
        store.snapshot("a.md", b"v1\n", actor="assistant")


def test_concurrent_snapshots_of_one_note_lose_no_lines(clock):
    def snap(i: int) -> None:
        store.snapshot("a.md", f"v{i}\n".encode(), actor="assistant")

    threads = [threading.Thread(target=snap, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(store.list_snapshots("a.md")) == 20


def test_package_reexports_the_interface():
    for name in ("history_dir", "blob_id", "put_blob", "get_blob", "has_blob", "snapshot",
                 "list_snapshots", "Snapshot", "HistoryError", "HistoryUnavailable",
                 "BlobNotFound", "USER_COALESCE"):
        assert hasattr(history, name), name
