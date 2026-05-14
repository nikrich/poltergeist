"""Job + daemon definitions for the in-process scheduler.

Intervals mirror the launchd plists in `orchestration/launchd/`. Touch
those when changing cadence here so the legacy path stays in sync if
the user hasn't migrated yet.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from pathlib import Path

from ghostbrain.connectors._runner import RunResult
from ghostbrain.connectors.calendar import runner as calendar_runner
from ghostbrain.connectors.confluence import runner as confluence_runner
from ghostbrain.connectors.github import runner as github_runner
from ghostbrain.connectors.gmail import runner as gmail_runner
from ghostbrain.connectors.jira import runner as jira_runner
from ghostbrain.connectors.slack import runner as slack_runner
from ghostbrain.paths import queue_dir
from ghostbrain.scheduler import (
    DailyAt,
    Interval,
    MonthlyAt,
    Scheduler,
    WeeklyAt,
)

log = logging.getLogger("ghostbrain.scheduler.jobs")


def _wrap_job(name: str, work: callable) -> RunResult:
    """Adapt a plain callable into a `RunResult`, capturing exceptions.

    `work()` returns a dict of detail fields (or empty). Anything raised is
    turned into a failed RunResult so the scheduler never sees a bare
    exception.
    """
    import time as _time
    import traceback as _tb

    started = _time.time()
    try:
        details = work() or {}
        queued = int(details.pop("queued", 0))
        return RunResult(
            connector=name,
            ok=True,
            started_at=started,
            finished_at=_time.time(),
            queued=queued,
            details=details,
        )
    except Exception as e:  # noqa: BLE001
        log.exception("%s failed", name)
        return RunResult(
            connector=name,
            ok=False,
            started_at=started,
            finished_at=_time.time(),
            error=str(e),
            error_type=type(e).__name__,
            details={"traceback": _tb.format_exc(limit=5)},
        )


def _digest_job() -> RunResult:
    """Generate today's daily digest. Mirrors `python -m ghostbrain.worker.digest`."""
    def work() -> dict:
        from ghostbrain.worker.digest import generate_digest, _local_today
        out = generate_digest(_local_today())
        return {"output_path": str(out)}
    return _wrap_job("digest", work)


def _claudemd_job() -> RunResult:
    """Regenerate per-project CLAUDE.md files. Mirrors `claude_md --all`."""
    def work() -> dict:
        from ghostbrain.profile.claude_md import regenerate_all
        written = regenerate_all() or []
        return {"queued": len(written), "files": [str(p) for p in written[:20]]}
    return _wrap_job("claudemd", work)


def _profile_weekly_job() -> RunResult:
    """Apply queued profile diffs. Mirrors `python -m ghostbrain.profile.apply`."""
    def work() -> dict:
        from datetime import date
        from ghostbrain.profile.apply import apply_weekly
        result = apply_weekly(date.today())
        return {
            "queued": len(result.applied),
            "applied": len(result.applied),
            "deferred": len(result.deferred_for_review),
            "discarded": result.discarded_count,
        }
    return _wrap_job("profile-weekly", work)


def _profile_monthly_job() -> RunResult:
    """Profile decay + promotion. Mirrors `python -m ghostbrain.profile.decay`."""
    def work() -> dict:
        from datetime import date
        from ghostbrain.profile.decay import decay_monthly
        result = decay_monthly(date.today())
        archived = int(result.get("archived", 0))
        promoted = int(result.get("promoted", 0))
        return {"queued": archived + promoted, **result}
    return _wrap_job("profile-monthly", work)


def _semantic_refresh() -> RunResult:
    """Run a semantic index refresh and translate the result into RunResult.

    Lazy-imports the semantic module so we don't drag torch into every sidecar
    start; the import is paid once per refresh.
    """
    import time as _time
    import traceback as _tb

    started = _time.time()
    try:
        from ghostbrain.semantic.refresh import refresh as _refresh

        result = _refresh()
        return RunResult(
            connector="semantic-refresh",
            ok=True,
            started_at=started,
            finished_at=_time.time(),
            queued=result.embedded,
            details={
                "embedded": result.embedded,
                "reused": result.reused,
                "linked": result.linked,
                "skipped": result.skipped,
            },
        )
    except Exception as e:  # noqa: BLE001
        log.exception("semantic refresh failed")
        return RunResult(
            connector="semantic-refresh",
            ok=False,
            started_at=started,
            finished_at=_time.time(),
            error=str(e),
            error_type=type(e).__name__,
            details={"traceback": _tb.format_exc(limit=5)},
        )


def register_connectors(scheduler: Scheduler) -> None:
    """Wire every connector with its scheduling cadence."""
    scheduler.add_job("github", Interval(seconds=7200), github_runner.run, "every 2h")
    scheduler.add_job("gmail", Interval(seconds=3600), gmail_runner.run, "every 1h")
    scheduler.add_job("calendar", Interval(seconds=3600), calendar_runner.run, "every 1h")
    scheduler.add_job("slack", Interval(seconds=3600), slack_runner.run, "every 1h")
    scheduler.add_job("jira", Interval(seconds=14400), jira_runner.run, "every 4h")
    scheduler.add_job("confluence", DailyAt(hour=6, minute=0), confluence_runner.run, "daily 06:00")
    # Semantic refresh runs frequently — embedding cost is paid only for new
    # or modified notes (mtime + hash short-circuit). Steady-state runs are
    # seconds. Keeping search/answer queries up-to-date with new transcripts
    # matters more than the small CPU spike.
    scheduler.add_job(
        "semantic-refresh",
        Interval(seconds=900),
        _semantic_refresh,
        "every 15m",
    )
    # Daily/weekly/monthly jobs that were on launchd before the cutover.
    # Match the schedules in orchestration/launchd/com.ghostbrain.*.plist.
    scheduler.add_job("digest", DailyAt(hour=6, minute=30), _digest_job, "daily 06:30")
    scheduler.add_job("claudemd", DailyAt(hour=2, minute=0), _claudemd_job, "daily 02:00")
    # launchd Weekday=0 is Sunday; datetime.weekday()=6 is Sunday.
    scheduler.add_job(
        "profile-weekly",
        WeeklyAt(weekday=6, hour=22, minute=0),
        _profile_weekly_job,
        "weekly Sun 22:00",
    )
    scheduler.add_job(
        "profile-monthly",
        MonthlyAt(day=1, hour=22, minute=0),
        _profile_monthly_job,
        "monthly day 1 22:00",
    )


# ---------------------------------------------------------------------------
# Worker daemon — re-implements the polling loop from ghostbrain.worker.main
# without touching that module so the launchd path still works exactly as it
# does today. The pieces being called (_claim_next, process_event, _move) ARE
# imported from there to keep behavior bit-identical.
# ---------------------------------------------------------------------------


async def worker_daemon(stop: asyncio.Event) -> None:
    from ghostbrain.worker.audit import audit_log
    from ghostbrain.worker.main import (
        _claim_next,
        _ensure_queue_dirs,
        _move,
        SLEEP_INTERVAL,
        process_event,
    )

    root = queue_dir()
    _ensure_queue_dirs(root)
    log.info("in-process worker started. queue=%s", root)
    audit_log("worker_started", queue_dir=str(root), source="scheduler")

    while not stop.is_set():
        event_path = await asyncio.to_thread(_claim_next, root)
        if event_path is None:
            try:
                await asyncio.wait_for(stop.wait(), timeout=SLEEP_INTERVAL)
            except asyncio.TimeoutError:
                pass
            continue
        event_id = event_path.stem
        try:
            event = json.loads(event_path.read_text(encoding="utf-8"))
            event_id = event.get("id", event_id)
            summary = await asyncio.to_thread(process_event, event) or {}
            await asyncio.to_thread(_move, event_path, root / "done")
            audit_log(
                "event_processed",
                event_id,
                status="success",
                source=event.get("source"),
                **{k: v for k, v in summary.items() if v is not None},
            )
        except Exception as e:  # noqa: BLE001
            log.exception("worker processing failed for %s", event_id)
            # Failed-handling must itself be resilient: if the event file is
            # already gone (a previous worker, manual cleanup, or a partial
            # move during shutdown), letting that escape the loop kills the
            # daemon and the tray reports "worker failing" forever. We log
            # and continue instead.
            try:
                failed_path = await asyncio.to_thread(_move, event_path, root / "failed")
                failed_err = failed_path.with_suffix(failed_path.suffix + ".error")
                await asyncio.to_thread(
                    failed_err.write_text,
                    f"{type(e).__name__}: {e}\n",
                    "utf-8",
                )
            except FileNotFoundError:
                log.warning(
                    "event %s vanished from processing/ before fail-move; "
                    "another worker or cleanup likely handled it",
                    event_id,
                )
            audit_log("event_failed", event_id, error=f"{type(e).__name__}: {e}")

    audit_log("worker_stopped", source="scheduler")
    log.info("in-process worker stopped")


# ---------------------------------------------------------------------------
# Recorder daemon — same approach: loop here, atomic ops imported from the
# existing module. Gated on a dep check (ffmpeg + Apple Calendar config) so
# users without the prereqs see the recorder disabled rather than crash.
# ---------------------------------------------------------------------------


def recorder_prereqs_ok() -> tuple[bool, list[str]]:
    """Returns (ok, missing) — `missing` lists human-readable prereq gaps."""
    missing: list[str] = []
    if shutil.which("ffmpeg") is None:
        missing.append("ffmpeg not on PATH (install via Homebrew: brew install ffmpeg)")
    # BlackHole detection is slow + flaky; we let the daemon surface that on
    # first attempt instead of probing here.
    return (not missing, missing)


async def recorder_daemon(stop: asyncio.Event) -> None:
    ok, missing = recorder_prereqs_ok()
    if not ok:
        raise RuntimeError("recorder prereqs missing: " + "; ".join(missing))

    # Lazy import — the recorder pulls in audio/transcribe deps we don't want
    # to import on every sidecar start.
    from ghostbrain.recorder import state as state_mod
    from ghostbrain.recorder.daemon import DaemonConfig, run_once

    config = await asyncio.to_thread(DaemonConfig.load)
    state = await asyncio.to_thread(state_mod.RecorderState.load)
    log.info("in-process recorder started. poll=%ss", config.poll_interval_s)

    while not stop.is_set():
        try:
            await asyncio.to_thread(run_once, config, state)
        except Exception:  # noqa: BLE001 — never let the recorder kill the sidecar
            log.exception("recorder run_once failed; backing off")
            try:
                await asyncio.wait_for(stop.wait(), timeout=config.poll_interval_s * 2)
            except asyncio.TimeoutError:
                continue
            else:
                break
        try:
            await asyncio.wait_for(stop.wait(), timeout=config.poll_interval_s)
        except asyncio.TimeoutError:
            pass

    log.info("in-process recorder stopped")


def register_daemons(scheduler: Scheduler, *, include_recorder: bool) -> None:
    scheduler.add_daemon("worker", worker_daemon, label="always-on")
    if include_recorder:
        scheduler.add_daemon("recorder", recorder_daemon, label="always-on")


# ---------------------------------------------------------------------------
# Top-level builder used by the API startup
# ---------------------------------------------------------------------------


def build(*, include_recorder: bool = True) -> Scheduler:
    sched = Scheduler()
    register_connectors(sched)
    register_daemons(sched, include_recorder=include_recorder)
    return sched
