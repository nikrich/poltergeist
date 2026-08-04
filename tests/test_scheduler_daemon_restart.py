"""Scheduler daemon auto-restart tests.

The worker daemon historically died on the first unhandled exception
and stayed dead — 900+ events stranded in pending/. The wrapper now
loops with capped exponential backoff. These tests pin that behavior.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from ghostbrain.scheduler import Scheduler


def _run(coro):
    """Sync wrapper — this project doesn't use pytest-asyncio."""
    return asyncio.run(coro)


def test_crashing_daemon_restarts_until_stopped(tmp_path: Path) -> None:
    """A daemon that always raises gets re-entered until the scheduler
    is asked to stop. The backoff schedule is squashed so the test
    finishes in milliseconds."""
    calls = 0

    async def scenario() -> int:
        nonlocal calls
        sched = Scheduler(status_file=tmp_path / "scheduler.json")
        sched._DAEMON_BACKOFF_S = (0, 0, 0)  # type: ignore[assignment]

        async def always_crashes(stop: asyncio.Event) -> None:
            nonlocal calls
            calls += 1
            raise RuntimeError("synthetic")

        sched.add_daemon("flaky", always_crashes)
        await sched.start()
        await asyncio.sleep(0.05)  # let it crash + restart a few times
        await sched.stop(timeout=2)

        status = sched._status["flaky"]
        assert status.last_run_ok is False
        assert "synthetic" in (status.last_error or "")
        assert status.consecutive_failures >= calls
        return calls

    n = _run(scenario())
    assert n >= 3, f"expected multiple restarts, got {n}"


def test_clean_exit_does_not_restart(tmp_path: Path) -> None:
    """When a daemon returns voluntarily, the wrapper exits. Only
    crashes trigger restart."""
    calls = 0

    async def scenario() -> int:
        nonlocal calls
        sched = Scheduler(status_file=tmp_path / "scheduler.json")

        async def runs_once(stop: asyncio.Event) -> None:
            nonlocal calls
            calls += 1
            return  # clean voluntary exit

        sched.add_daemon("oneshot", runs_once)
        await sched.start()
        await asyncio.sleep(0.05)
        await sched.stop(timeout=2)
        return calls

    assert _run(scenario()) == 1


def test_stop_during_backoff_breaks_out(tmp_path: Path) -> None:
    """If the scheduler is stopped while a daemon is sleeping between
    restarts, we exit without waiting out the backoff. Otherwise quit
    would block for the full backoff window after a recent crash."""

    async def scenario() -> None:
        sched = Scheduler(status_file=tmp_path / "scheduler.json")
        sched._DAEMON_BACKOFF_S = (60,)  # type: ignore[assignment]

        async def crash_then_sleep_in_backoff(stop: asyncio.Event) -> None:
            raise RuntimeError("crash to enter backoff")

        sched.add_daemon("backoff_target", crash_then_sleep_in_backoff)
        await sched.start()
        await asyncio.sleep(0.05)  # let it crash + enter the 60s backoff
        # If stop doesn't short-circuit the backoff sleep this times out.
        await asyncio.wait_for(sched.stop(timeout=2), timeout=3)

    _run(scenario())
