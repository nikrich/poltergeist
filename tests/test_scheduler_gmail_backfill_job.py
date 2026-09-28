"""Scheduler registration + wrapping for the gmail-backfill tick."""
from __future__ import annotations

from ghostbrain.connectors.gmail import backfill
from ghostbrain.scheduler import Interval, Scheduler
from ghostbrain.scheduler_jobs import _gmail_backfill_job, register_connectors


def test_gmail_backfill_registered_every_2_minutes():
    sched = Scheduler()
    register_connectors(sched)
    job = sched._jobs["gmail-backfill"]
    assert job.schedule == Interval(seconds=120)
    assert job.schedule_label == "every 2m"


def test_gmail_backfill_job_wraps_run_tick_result(monkeypatch):
    monkeypatch.setattr(backfill, "run_tick", lambda: {"skipped": "idle"})
    result = _gmail_backfill_job()
    assert result.connector == "gmail-backfill"
    assert result.ok is True
    assert result.details == {"skipped": "idle"}


def test_gmail_backfill_job_never_raises_on_gmail_failure(monkeypatch):
    def _boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(backfill, "run_tick", _boom)
    result = _gmail_backfill_job()
    assert result.ok is False
    assert result.error_type == "RuntimeError"
