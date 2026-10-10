"""B2: change-log retention inside the daily history prune."""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

from ghostbrain.changes import log as changes
from ghostbrain.changes.maintenance import run_prune
from ghostbrain.history import store


def _age(blob: str, days: int = 3) -> None:
    old = time.time() - days * 86400
    os.utime(store._blob_path(blob), (old, old))


def test_rows_older_than_a_year_are_pruned_with_the_history(monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(changes, "_now", lambda: now - timedelta(days=400))
    changes.record(actor="assistant", rel_path="a.md", op="modify")
    monkeypatch.setattr(changes, "_now", lambda: now)
    keep = changes.record(actor="assistant", rel_path="b.md", op="modify")
    details = run_prune(now)
    assert details["changesPruned"] == 1
    assert details["gcSkipped"] is False
    assert [c.id for c in changes.list_changes()] == [keep]


def test_blobs_named_only_by_change_rows_survive_gc():
    blob = store.put_blob(b"assistant version\n")
    _age(blob)
    changes.record(actor="assistant", rel_path="a.md", op="create", after_blob=blob)
    assert run_prune()["gcSkipped"] is False
    assert store.has_blob(blob)
    run_prune(datetime.now(timezone.utc) + timedelta(days=800))  # the row expires
    assert not store.has_blob(blob)


def test_a_broken_change_log_skips_blob_gc(monkeypatch):
    orphan = store.put_blob(b"orphan\n")
    _age(orphan)

    def boom():
        raise changes.ChangeLogError("database is locked")

    monkeypatch.setattr(changes, "referenced_blobs", boom)
    details = run_prune()
    assert details["gcSkipped"] is True
    assert store.has_blob(orphan)


def test_a_failing_change_prune_still_runs_the_history_prune(monkeypatch):
    def boom(*_a, **_k):
        raise changes.ChangeLogError("database is locked")

    monkeypatch.setattr(changes, "prune", boom)
    details = run_prune()
    assert details["changesPruned"] is None
    assert "notes" in details
