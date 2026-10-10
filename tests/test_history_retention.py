"""History retention, blob GC, ref sources, log moves (spec A3)."""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from ghostbrain import history
from ghostbrain.history import store
from ghostbrain.history.store import Snapshot

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _no_ref_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store, "_ref_sources", {})


def _s(when: datetime, n: int = 0) -> Snapshot:
    return Snapshot(ts=when.isoformat(), rel_path="a.md", blob=f"{n:064x}", actor="user",
                    reason="", size=1)


def _snap_at(monkeypatch, when: datetime, rel: str, data: bytes, actor: str = "assistant"):
    monkeypatch.setattr(store, "_now", lambda: when)
    return store.snapshot(rel, data, actor=actor)


def _age_file(path, days: float) -> None:
    old = time.time() - days * 86400
    os.utime(path, (old, old))


def test_retained_keeps_everything_for_30_days():
    entries = [_s(NOW - timedelta(days=d, hours=h), i)
               for i, (d, h) in enumerate([(30, 0), (29, 0), (1, 3), (1, 1), (0, 0)])]
    assert store.retained(entries, NOW) == sorted(entries, key=lambda s: s.when)


def test_retained_keeps_newest_per_day_between_30_days_and_a_year():
    morning = _s(datetime(2026, 8, 30, 9, tzinfo=timezone.utc), 1)
    noon = _s(datetime(2026, 8, 30, 13, tzinfo=timezone.utc), 2)
    evening = _s(datetime(2026, 8, 30, 18, tzinfo=timezone.utc), 3)
    day_before = _s(datetime(2026, 8, 29, 9, tzinfo=timezone.utc), 4)
    got = store.retained([morning, noon, evening, day_before], NOW)
    assert got == [day_before, evening]


def test_retained_keeps_newest_per_month_after_a_year():
    early_aug = _s(datetime(2025, 8, 3, 10, tzinfo=timezone.utc), 1)
    late_aug = _s(datetime(2025, 8, 20, 10, tzinfo=timezone.utc), 2)
    july = _s(datetime(2025, 7, 1, 10, tzinfo=timezone.utc), 3)
    got = store.retained([early_aug, late_aug, july], NOW)
    assert got == [july, late_aug]


def test_prune_rewrites_logs_and_reports_counts(monkeypatch):
    for i, hour in enumerate((9, 13, 18)):
        _snap_at(monkeypatch, datetime(2026, 8, 30, hour, tzinfo=timezone.utc), "a.md",
                 f"v{i}\n".encode())
    _snap_at(monkeypatch, NOW - timedelta(days=1), "a.md", b"recent\n")
    res = store.prune(now=NOW)
    assert (res.notes, res.kept, res.dropped) == (1, 2, 2)
    got = store.list_snapshots("a.md")
    assert [store.get_blob(s.blob) for s in got] == [b"recent\n", b"v2\n"]
    assert res.to_details() == {"notes": 1, "kept": 2, "dropped": 2, "blobsDeleted": 0,
                                "gcSkipped": False}


def test_prune_gcs_unreferenced_blobs_older_than_the_grace(monkeypatch):
    for i, hour in enumerate((9, 18)):
        _snap_at(monkeypatch, datetime(2026, 8, 30, hour, tzinfo=timezone.utc), "a.md",
                 f"v{i}\n".encode())
    dropped_blob = store.blob_id(b"v0\n")
    kept_blob = store.blob_id(b"v1\n")
    for b in (dropped_blob, kept_blob):
        _age_file(store._blob_path(b), days=2)
    res = store.prune(now=NOW)
    assert res.blobs_deleted == 1
    assert not store.has_blob(dropped_blob) and store.has_blob(kept_blob)


def test_gc_spares_fresh_unreferenced_blobs():
    """A blob put by a snapshot racing the prune has a fresh mtime."""
    fresh = store.put_blob(b"just written\n")
    assert store.prune(now=NOW).blobs_deleted == 0
    assert store.has_blob(fresh)


def test_put_blob_refreshes_mtime_of_an_existing_blob():
    blob = store.put_blob(b"x\n")
    _age_file(store._blob_path(blob), days=2)
    store.put_blob(b"x\n")
    assert store.prune(now=NOW).blobs_deleted == 0


def test_gc_removes_stale_temp_files_but_never_foreign_files():
    blobs = store.history_dir() / "blobs"
    blobs.mkdir(parents=True)
    tmp = blobs / ".abc.md.123.tmp"
    tmp.write_bytes(b"partial")
    foreign = blobs / "README.txt"
    foreign.write_bytes(b"not ours")
    for p in (tmp, foreign):
        _age_file(p, days=2)
    store.prune(now=NOW)
    assert not tmp.exists() and foreign.exists()


def test_prune_keeps_blobs_named_by_ref_sources():
    orphan = store.put_blob(b"changes-db only\n")
    _age_file(store._blob_path(orphan), days=2)
    history.register_ref_source("changes", lambda: [orphan])
    assert store.prune(now=NOW).blobs_deleted == 0
    assert store.has_blob(orphan)


def test_prune_skips_gc_when_a_ref_source_fails():
    orphan = store.put_blob(b"maybe referenced\n")
    _age_file(store._blob_path(orphan), days=2)

    def broken():
        raise RuntimeError("changes.db locked")

    history.register_ref_source("changes", broken)
    res = store.prune(now=NOW)
    assert res.gc_skipped is True and res.blobs_deleted == 0
    assert store.has_blob(orphan)


def test_prune_skips_gc_when_a_ref_source_returns_a_bare_string():
    """A bare str would be iterated as characters, leaving the real id
    unreferenced; it counts as a failing source."""
    orphan = store.put_blob(b"named by a str\n")
    _age_file(store._blob_path(orphan), days=2)
    history.register_ref_source("changes", lambda: orphan)
    res = store.prune(now=NOW)
    assert res.gc_skipped is True and res.blobs_deleted == 0
    assert store.has_blob(orphan)


def test_prune_drops_logs_with_no_readable_entries():
    log_file = store._log_path("a.md")
    log_file.parent.mkdir(parents=True)
    log_file.write_text("garbage\n", encoding="utf-8")
    store._head_path("a.md").write_text("{}", encoding="utf-8")
    res = store.prune(now=NOW)
    assert res.dropped == 1
    assert not log_file.exists() and not store._head_path("a.md").exists()


def test_move_log_carries_entries_and_head(monkeypatch):
    monkeypatch.setattr(store, "_now", lambda: NOW)
    store.snapshot("inbox/j.md", b"v1\n", actor="user", after=b"v2\n")
    store.move_log("inbox/j.md", "20-contexts/work/j.md")
    assert store.list_snapshots("inbox/j.md") == []
    [moved] = store.list_snapshots("20-contexts/work/j.md")
    assert store.get_blob(moved.blob) == b"v1\n"
    # The head moved too: the next user save at the new path coalesces.
    assert store.snapshot("20-contexts/work/j.md", b"v2\n", actor="user", after=b"v3\n") is None


def test_move_log_merges_into_an_existing_destination_log_in_time_order(monkeypatch):
    _snap_at(monkeypatch, NOW - timedelta(hours=3), "b.md", b"old b\n")
    _snap_at(monkeypatch, NOW - timedelta(hours=2), "a.md", b"a\n")
    _snap_at(monkeypatch, NOW - timedelta(hours=1), "b.md", b"new b\n")
    store.move_log("a.md", "b.md")
    got = [store.get_blob(s.blob) for s in store.list_snapshots("b.md")]
    assert got == [b"new b\n", b"a\n", b"old b\n"]


def test_move_log_without_history_is_a_no_op():
    store.move_log("none.md", "elsewhere.md")
    assert store.list_snapshots("elsewhere.md") == []
