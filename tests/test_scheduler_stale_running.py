"""Scheduler stale running-flag tests.

``_save_status`` persists the transient ``running`` flag, and
``_load_status`` restored it verbatim. A sidecar killed mid-run therefore
came back with ``running: true`` on disk, and ``_invoke`` skipped that job
as "already_running" on every subsequent tick — the job never ran again
until the flag was hand-edited out of the state file. (Seen in production:
the digest job died mid-run on 2026-06-18 and daily notes silently stopped
for three weeks; semantic-refresh died the same way on 2026-06-22.)

A freshly constructed scheduler cannot have anything running: the flag is
process-transient state and must be reset on load.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from ghostbrain.connectors._runner import RunResult
from ghostbrain.scheduler import DailyAt, Scheduler


def _run(coro):
    return asyncio.run(coro)


def _write_status_running(path: Path, *, job_name: str, next_run_at: float) -> None:
    payload = {
        "jobs": {
            job_name: {
                "name": job_name,
                "schedule_label": "daily 06:30",
                "next_run_at": next_run_at,
                "running": True,
            }
        },
        "saved_at": time.time(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_persisted_running_flag_does_not_block_job(tmp_path: Path) -> None:
    """A job whose state was persisted mid-run (running=true) must still
    fire after a restart — the flag is transient, not durable."""
    status_file = tmp_path / "scheduler.json"
    _write_status_running(
        status_file, job_name="digest", next_run_at=time.time() - 3600
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
        await asyncio.sleep(0.1)
        await sched.stop(timeout=2)

    _run(scenario())
    assert calls == 1, (
        f"expected job to fire despite stale persisted running=true, got {calls}"
    )


def test_status_report_after_load_shows_not_running(tmp_path: Path) -> None:
    """Immediately after construction, no job may report running=True."""
    status_file = tmp_path / "scheduler.json"
    _write_status_running(
        status_file, job_name="digest", next_run_at=time.time() + 7200
    )
    sched = Scheduler(status_file=status_file)
    assert sched._status["digest"].running is False
