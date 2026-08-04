"""Scheduler missed-firing tests.

When the app is off at the moment a DailyAt/WeeklyAt/MonthlyAt job would
fire and starts up after the scheduled time, the persisted
``next_run_at`` is in the past. The pre-fix behavior was to overwrite
that value on startup with ``next_fire_at(schedule, now)``, which for a
daily job whose hour has already passed jumps to *tomorrow* — silently
losing today's firing. These tests pin the catch-up behavior.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from ghostbrain.connectors._runner import RunResult
from ghostbrain.scheduler import DailyAt, Interval, Scheduler


def _run(coro):
    return asyncio.run(coro)


def _write_status(
    path: Path,
    *,
    job_name: str,
    schedule_label: str,
    next_run_at: float,
) -> None:
    payload = {
        "jobs": {
            job_name: {
                "name": job_name,
                "schedule_label": schedule_label,
                "next_run_at": next_run_at,
            }
        },
        "saved_at": time.time(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_past_due_daily_fires_on_startup(tmp_path: Path) -> None:
    """The scheduler must fire a daily job whose persisted next_run_at is
    in the past — not silently push it to the next-day occurrence."""
    status_file = tmp_path / "scheduler.json"
    # Persisted next_run_at is one hour ago — "we missed today's firing".
    past_due = time.time() - 3600
    _write_status(
        status_file,
        job_name="digest",
        schedule_label="daily 06:30",
        next_run_at=past_due,
    )

    calls = 0

    def job() -> RunResult:
        nonlocal calls
        calls += 1
        return RunResult(
            connector="digest",
            ok=True,
            started_at=time.time(),
            finished_at=time.time(),
        )

    async def scenario() -> None:
        sched = Scheduler(status_file=status_file)
        sched.add_job("digest", DailyAt(hour=6, minute=30), job, "daily 06:30")
        await sched.start()
        # One loop iteration is enough — the past-due job should be in
        # `due` on the very first pass.
        await asyncio.sleep(0.1)
        await sched.stop(timeout=2)

    _run(scenario())
    assert calls == 1, f"expected past-due daily to fire once, got {calls}"


def test_future_next_run_at_is_preserved(tmp_path: Path) -> None:
    """When the persisted next_run_at is in the future, startup must not
    move it earlier (which would fire the job sooner than scheduled)."""
    status_file = tmp_path / "scheduler.json"
    future = time.time() + 7200  # two hours out
    _write_status(
        status_file,
        job_name="digest",
        schedule_label="daily 06:30",
        next_run_at=future,
    )

    def job() -> RunResult:
        return RunResult(
            connector="digest",
            ok=True,
            started_at=time.time(),
            finished_at=time.time(),
        )

    async def scenario() -> float:
        sched = Scheduler(status_file=status_file)
        sched.add_job("digest", DailyAt(hour=6, minute=30), job, "daily 06:30")
        await sched.start()
        await asyncio.sleep(0.05)
        snapshot = sched._status["digest"].next_run_at
        await sched.stop(timeout=2)
        assert snapshot is not None
        return snapshot

    observed = _run(scenario())
    assert abs(observed - future) < 1.0, (
        f"expected next_run_at preserved at ~{future}, got {observed}"
    )


def test_fresh_job_with_no_persisted_state_gets_scheduled(tmp_path: Path) -> None:
    """A newly-added job (no persisted next_run_at) still gets a
    next-fire computed at startup. Without this, the loop would treat
    None as 'fire forever' or skip it entirely."""
    status_file = tmp_path / "scheduler.json"  # does not exist

    def job() -> RunResult:
        return RunResult(
            connector="other",
            ok=True,
            started_at=time.time(),
            finished_at=time.time(),
        )

    async def scenario() -> float | None:
        sched = Scheduler(status_file=status_file)
        # Far-future schedule so it won't fire during the test.
        sched.add_job("other", Interval(seconds=3600), job, "every 1h")
        await sched.start()
        await asyncio.sleep(0.05)
        snapshot = sched._status["other"].next_run_at
        await sched.stop(timeout=2)
        return snapshot

    observed = _run(scenario())
    assert observed is not None
    assert observed > time.time(), "next_run_at should be in the future"
