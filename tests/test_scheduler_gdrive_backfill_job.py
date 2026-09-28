"""Scheduler registration + wrapping for the gdrive-backfill tick."""
from __future__ import annotations

from ghostbrain.connectors.gdrive import backfill
from ghostbrain.scheduler import Interval, Scheduler
from ghostbrain.scheduler_jobs import _gdrive_backfill_job, register_connectors


def test_gdrive_backfill_registered_every_2_minutes():
    sched = Scheduler()
    register_connectors(sched)
    job = sched._jobs["gdrive-backfill"]
    assert job.schedule == Interval(seconds=120)
    assert job.schedule_label == "every 2m"


def test_gdrive_backfill_job_wraps_run_tick_result(monkeypatch):
    monkeypatch.setattr(backfill, "run_tick", lambda: {"skipped": "idle"})
    result = _gdrive_backfill_job()
    assert result.connector == "gdrive-backfill"
    assert result.ok is True
    assert result.details == {"skipped": "idle"}


def test_gdrive_backfill_job_never_raises_on_failure(monkeypatch):
    def _boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(backfill, "run_tick", _boom)
    result = _gdrive_backfill_job()
    assert result.ok is False
    assert result.error_type == "RuntimeError"
