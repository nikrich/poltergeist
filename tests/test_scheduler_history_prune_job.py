"""Scheduler registration + wrapping for the daily history prune."""
from __future__ import annotations

from ghostbrain.history import store
from ghostbrain.scheduler import DailyAt, Scheduler
from ghostbrain.scheduler_jobs import _history_prune_job, register_connectors


def test_history_prune_registered_daily():
    sched = Scheduler()
    register_connectors(sched)
    job = sched._jobs["history-prune"]
    assert job.schedule == DailyAt(hour=3, minute=15)
    assert job.schedule_label == "daily 03:15"


def test_history_prune_job_reports_counts():
    result = _history_prune_job()
    assert result.connector == "history-prune"
    assert result.ok is True
    assert result.details == {"notes": 0, "kept": 0, "dropped": 0, "blobsDeleted": 0,
                              "gcSkipped": False, "changesPruned": 0}


def test_history_prune_job_never_raises(monkeypatch):
    def boom(now=None):
        raise store.HistoryUnavailable("disk")

    monkeypatch.setattr(store, "prune", boom)
    result = _history_prune_job()
    assert result.ok is False and result.error_type == "HistoryUnavailable"
