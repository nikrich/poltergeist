"""In-process scheduler for the desktop sidecar.

Runs connectors on the same intervals the launchd plists use today, plus
the worker + recorder daemons as long-running asyncio tasks. Off by
default — gated by the desktop's `schedulerEnabled` setting and the
GHOSTBRAIN_SCHEDULER_ENABLED env var the sidecar passes through.

Why not APScheduler: 10 jobs, four schedule shapes (interval, daily-at,
weekly-at-day-time, always-on). Rolling our own is ~200 lines and avoids
a heavy dep in the PyInstaller bundle.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Awaitable, Callable

from ghostbrain.connectors._runner import RunResult
from ghostbrain.paths import state_dir as _state_dir

log = logging.getLogger("ghostbrain.scheduler")

# Suppress repeat notifications for a connector that's been failing for a while.
NOTIFY_COOLDOWN_S = 6 * 60 * 60


# ---------------------------------------------------------------------------
# Schedule definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Interval:
    seconds: int


@dataclass(frozen=True)
class DailyAt:
    hour: int
    minute: int


@dataclass(frozen=True)
class WeeklyAt:
    weekday: int  # 0 = Monday (matches datetime.weekday())
    hour: int
    minute: int


@dataclass(frozen=True)
class MonthlyAt:
    day: int   # day-of-month (1..31). Clamped to month length when shorter.
    hour: int
    minute: int


Schedule = Interval | DailyAt | WeeklyAt | MonthlyAt


def _clamp_day(year: int, month: int, day: int) -> int:
    """Return `day` clamped to the last day of (year, month)."""
    if month == 12:
        first_of_next = datetime(year + 1, 1, 1)
    else:
        first_of_next = datetime(year, month + 1, 1)
    last_day = (first_of_next - timedelta(days=1)).day
    return min(day, last_day)


def next_fire_at(schedule: Schedule, now: datetime) -> datetime:
    """When should the job next fire, given `now` (naive local time)?"""
    if isinstance(schedule, Interval):
        return now + timedelta(seconds=schedule.seconds)
    if isinstance(schedule, DailyAt):
        candidate = now.replace(
            hour=schedule.hour, minute=schedule.minute, second=0, microsecond=0,
        )
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate
    if isinstance(schedule, WeeklyAt):
        candidate = now.replace(
            hour=schedule.hour, minute=schedule.minute, second=0, microsecond=0,
        )
        days_ahead = (schedule.weekday - now.weekday()) % 7
        candidate += timedelta(days=days_ahead)
        if candidate <= now:
            candidate += timedelta(days=7)
        return candidate
    if isinstance(schedule, MonthlyAt):
        target_day = _clamp_day(now.year, now.month, schedule.day)
        candidate = now.replace(
            day=target_day, hour=schedule.hour, minute=schedule.minute,
            second=0, microsecond=0,
        )
        if candidate <= now:
            year = now.year + (1 if now.month == 12 else 0)
            month = 1 if now.month == 12 else now.month + 1
            candidate = candidate.replace(
                year=year, month=month, day=_clamp_day(year, month, schedule.day),
            )
        return candidate
    raise TypeError(f"unknown schedule type {type(schedule)}")


# ---------------------------------------------------------------------------
# Status tracking
# ---------------------------------------------------------------------------


@dataclass
class JobStatus:
    name: str
    schedule_label: str
    last_run_at: float | None = None
    last_run_ok: bool | None = None
    last_queued: int = 0
    last_error: str | None = None
    last_error_type: str | None = None
    last_skipped_reason: str | None = None
    next_run_at: float | None = None
    consecutive_failures: int = 0
    failed_since: float | None = None  # epoch when transitioned ok->failed
    last_notified_at: float | None = None  # for notification cooldown
    running: bool = False

    def apply(self, result: RunResult) -> bool:
        """Returns True if a notification should be fired (transition or cooldown elapsed)."""
        was_failed = self.last_run_ok is False
        self.last_run_at = result.finished_at
        self.last_run_ok = result.ok
        self.last_queued = result.queued
        self.last_error = result.error
        self.last_error_type = result.error_type
        self.last_skipped_reason = result.skipped_reason
        if result.ok:
            self.consecutive_failures = 0
            self.failed_since = None
            return False
        self.consecutive_failures += 1
        if not was_failed:
            self.failed_since = result.finished_at
        # Notify on transition, or every NOTIFY_COOLDOWN_S while still failed.
        now = time.time()
        if (
            not was_failed
            or self.last_notified_at is None
            or (now - self.last_notified_at) > NOTIFY_COOLDOWN_S
        ):
            self.last_notified_at = now
            return True
        return False


# ---------------------------------------------------------------------------
# Diagnostics — detect double-scheduling
# ---------------------------------------------------------------------------


def _launchd_plists() -> list[str]:
    """Currently *loaded* ghostbrain launchd jobs.

    The earlier version listed plist files on disk, which is wrong: unloaded
    plists are harmless (they don't fire). What actually causes
    double-scheduling is jobs that are loaded into launchd. `launchctl list`
    reports loaded jobs by their Label key. Disk-resident-but-unloaded plists
    are correctly treated as not-a-conflict.
    """
    import subprocess
    try:
        result = subprocess.run(
            ["launchctl", "list"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    labels: list[str] = []
    for line in (result.stdout or "").splitlines()[1:]:  # skip header
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        label = parts[2].strip()
        if label.startswith("com.ghostbrain."):
            labels.append(label)
    return sorted(labels)


def diagnostics() -> dict:
    """Best-effort detection of conflicts. Used by the UI banner."""
    plists = _launchd_plists()
    ffmpeg = shutil.which("ffmpeg") is not None
    return {
        "active_launchd_plists": plists,
        "double_scheduling": bool(plists),
        "ffmpeg_available": ffmpeg,
        # BlackHole detection: a virtual device shows up in `system_profiler
        # SPAudioDataType`, which is slow. Defer to recorder dep-check on demand.
    }


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


JobFn = Callable[[], RunResult]


@dataclass
class Job:
    name: str
    schedule: Schedule
    fn: JobFn
    schedule_label: str


class Scheduler:
    """Runs scheduled connectors + long-running daemons inside the sidecar.

    Designed for cooperative shutdown: stop() returns once all in-flight
    jobs are finished or the timeout expires.
    """

    def __init__(self, status_file: Path | None = None) -> None:
        self._status_file = status_file or (_state_dir() / "scheduler.json")
        self._jobs: dict[str, Job] = {}
        self._daemons: dict[str, Callable[[asyncio.Event], Awaitable[None]]] = {}
        self._status: dict[str, JobStatus] = {}
        self._stop_event: asyncio.Event | None = None
        self._loop_task: asyncio.Task | None = None
        self._daemon_tasks: list[asyncio.Task] = []
        self._lock = threading.Lock()
        self._notify_cb: Callable[[str, str], None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._load_status()

    # -- registration ----------------------------------------------------

    def add_job(self, name: str, schedule: Schedule, fn: JobFn, label: str) -> None:
        self._jobs[name] = Job(name=name, schedule=schedule, fn=fn, schedule_label=label)
        self._status.setdefault(name, JobStatus(name=name, schedule_label=label))

    def add_daemon(
        self,
        name: str,
        coro_factory: Callable[[asyncio.Event], Awaitable[None]],
        label: str = "always-on",
    ) -> None:
        self._daemons[name] = coro_factory
        self._status.setdefault(name, JobStatus(name=name, schedule_label=label))

    def on_failure_notification(self, cb: Callable[[str, str], None]) -> None:
        """Register a callback(name, error_message) for fire-once transitions
        to a failed state (and periodic reminders per NOTIFY_COOLDOWN_S)."""
        self._notify_cb = cb

    # -- lifecycle -------------------------------------------------------

    async def start(self) -> None:
        if self._loop_task is not None:
            return
        self._loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        self._loop_task = asyncio.create_task(self._run(), name="scheduler-main")
        for name, factory in self._daemons.items():
            self._daemon_tasks.append(
                asyncio.create_task(self._daemon_wrapper(name, factory), name=f"daemon-{name}")
            )
        log.info("scheduler started; %d jobs, %d daemons", len(self._jobs), len(self._daemons))

    async def stop(self, timeout: float = 10.0) -> None:
        if self._stop_event is None:
            return
        self._stop_event.set()
        tasks = [t for t in [self._loop_task, *self._daemon_tasks] if t is not None]
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=timeout)
            for t in pending:
                t.cancel()
        self._save_status()
        self._loop_task = None
        self._daemon_tasks = []
        self._stop_event = None
        log.info("scheduler stopped")

    # -- manual triggers -------------------------------------------------

    async def run_now(self, name: str) -> RunResult:
        """Fire a job immediately, off-schedule. Errors are captured."""
        job = self._jobs.get(name)
        if job is None:
            raise KeyError(f"unknown job: {name}")
        return await self._invoke(job)

    async def run_all(self) -> dict[str, RunResult]:
        """Fire every scheduled job in parallel."""
        results = await asyncio.gather(
            *[self._invoke(j) for j in self._jobs.values()],
            return_exceptions=False,
        )
        return {j.name: r for j, r in zip(self._jobs.values(), results)}

    # -- status ----------------------------------------------------------

    def status_snapshot(self) -> dict:
        with self._lock:
            return {
                "jobs": {name: asdict(s) for name, s in self._status.items()},
                "running": self._loop_task is not None,
            }

    # -- internals -------------------------------------------------------

    async def _run(self) -> None:
        assert self._stop_event is not None
        now = datetime.now()
        for name, job in self._jobs.items():
            self._status[name].next_run_at = next_fire_at(job.schedule, now).timestamp()
        self._save_status()
        while not self._stop_event.is_set():
            now = datetime.now()
            next_at: datetime | None = None
            due: list[Job] = []
            for name, job in self._jobs.items():
                fire_at = datetime.fromtimestamp(self._status[name].next_run_at or 0)
                if fire_at <= now:
                    due.append(job)
                else:
                    next_at = fire_at if next_at is None or fire_at < next_at else next_at
            if due:
                # Fire in parallel — each job is independent.
                await asyncio.gather(*[self._invoke(j) for j in due])
                continue
            # Sleep until either the next job fires or stop is signalled.
            sleep_for = 30.0 if next_at is None else max(1.0, (next_at - now).total_seconds())
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=sleep_for)
            except asyncio.TimeoutError:
                pass

    async def _invoke(self, job: Job) -> RunResult:
        with self._lock:
            self._status[job.name].running = True
        try:
            result = await asyncio.to_thread(job.fn)
        except Exception as e:  # noqa: BLE001 — connectors should never reach here
            log.exception("job %s raised past its runner", job.name)
            result = RunResult(
                connector=job.name,
                ok=False,
                started_at=time.time(),
                finished_at=time.time(),
                error=str(e),
                error_type=type(e).__name__,
            )
        with self._lock:
            status = self._status[job.name]
            status.running = False
            notify = status.apply(result)
            status.next_run_at = next_fire_at(job.schedule, datetime.now()).timestamp()
        self._save_status()
        if notify and self._notify_cb and result.error:
            try:
                self._notify_cb(job.name, result.error)
            except Exception:  # noqa: BLE001
                log.exception("failure notification callback raised")
        return result

    async def _daemon_wrapper(
        self,
        name: str,
        factory: Callable[[asyncio.Event], Awaitable[None]],
    ) -> None:
        assert self._stop_event is not None
        with self._lock:
            self._status[name].running = True
            self._status[name].last_run_ok = True
        try:
            await factory(self._stop_event)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("daemon %s crashed", name)
            with self._lock:
                status = self._status[name]
                status.last_run_ok = False
                status.last_error = str(e)
                status.last_error_type = type(e).__name__
                status.consecutive_failures += 1
                if status.failed_since is None:
                    status.failed_since = time.time()
                if self._notify_cb:
                    try:
                        self._notify_cb(name, str(e))
                    except Exception:  # noqa: BLE001
                        log.exception("failure notification callback raised")
        finally:
            with self._lock:
                self._status[name].running = False
            self._save_status()

    # -- persistence -----------------------------------------------------

    def _load_status(self) -> None:
        if not self._status_file.exists():
            return
        try:
            raw = json.loads(self._status_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            log.exception("scheduler state corrupt; ignoring")
            return
        for name, blob in (raw.get("jobs") or {}).items():
            if not isinstance(blob, dict):
                continue
            # Drop any unknown keys defensively (forward-compat).
            allowed = {f for f in JobStatus.__dataclass_fields__}
            clean = {k: v for k, v in blob.items() if k in allowed}
            clean.setdefault("name", name)
            clean.setdefault("schedule_label", "unknown")
            self._status[name] = JobStatus(**clean)

    def _save_status(self) -> None:
        self._status_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._status_file.with_suffix(self._status_file.suffix + ".tmp")
        payload = {
            "jobs": {name: asdict(s) for name, s in self._status.items()},
            "saved_at": time.time(),
        }
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self._status_file)
