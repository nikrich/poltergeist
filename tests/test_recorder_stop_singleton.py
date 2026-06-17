"""Regression tests for the "can't stop the recording" bug.

Two independent failures combined to make the desktop Stop button a no-op:

1. ``is_running`` reported a *zombie* (terminated-but-unreaped) PID as alive,
   because a zombie still answers ``os.kill(pid, 0)``. ``stop()`` then signalled
   the corpse forever while the real ffmpeg kept recording, and ``status()``
   stayed stuck on phase ``recording``.
2. Two ``ghostbrain.api`` instances (the bundled app sidecar + a stray
   ``python -m ghostbrain.api``) both booted the scheduler/recorder against one
   shared state file, so the persisted PID belonged to the *other* instance's
   ffmpeg and the app could never stop it.

These tests pin the two fixes: a zombie-aware ``is_running`` and a
single-instance lock for the scheduler.
"""
from __future__ import annotations

import os
import subprocess
import time

import pytest

from ghostbrain.api import runtime
from ghostbrain.recorder import audio_capture


# ---------------------------------------------------------------------------
# Zombie-aware is_running
# ---------------------------------------------------------------------------


def _proc_state(pid: int) -> str:
    """Raw `ps` state column for a pid ('' if gone). Independent of the code
    under test so the zombie wait-loop doesn't beg the question."""
    out = subprocess.run(
        ["ps", "-p", str(pid), "-o", "state="],
        capture_output=True, text=True,
    )
    return out.stdout.strip()


@pytest.mark.skipif(not hasattr(os, "fork"), reason="needs POSIX fork")
def test_is_running_false_for_zombie() -> None:
    """A child that has exited but not been reaped is a zombie. It still
    satisfies kill(pid, 0), but is_running() must report it as not running —
    otherwise stop()/status() wedge on a dead PID forever."""
    pid = os.fork()
    if pid == 0:  # child
        os._exit(0)
    try:
        # Wait until the child is actually a zombie (state starts with 'Z').
        deadline = time.time() + 5.0
        while time.time() < deadline and not _proc_state(pid).startswith("Z"):
            time.sleep(0.02)
        assert _proc_state(pid).startswith("Z"), "child never became a zombie"
        assert audio_capture.is_running(pid) is False
    finally:
        os.waitpid(pid, 0)  # reap


def test_is_running_true_for_live_process() -> None:
    """Sanity: a normal live process is still reported as running."""
    assert audio_capture.is_running(os.getpid()) is True


def test_is_running_false_for_dead_pid() -> None:
    assert audio_capture.is_running(2_000_000_000) is False
    assert audio_capture.is_running(0) is False
    assert audio_capture.is_running(-1) is False


# ---------------------------------------------------------------------------
# Single-instance scheduler lock
# ---------------------------------------------------------------------------


def test_singleton_lock_blocks_second_acquire(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only one holder at a time — a second acquire of the same name fails
    while the first is held, and succeeds again once it's released."""
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path))

    first = runtime.acquire_singleton_lock("scheduler")
    assert first is not None

    second = runtime.acquire_singleton_lock("scheduler")
    assert second is None, "second acquire must fail while the first is held"

    runtime.release_singleton_lock(first)

    third = runtime.acquire_singleton_lock("scheduler")
    assert third is not None, "lock must be re-acquirable after release"
    runtime.release_singleton_lock(third)


def test_singleton_lock_distinct_names_independent(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path))
    a = runtime.acquire_singleton_lock("scheduler")
    b = runtime.acquire_singleton_lock("other")
    assert a is not None and b is not None
    runtime.release_singleton_lock(a)
    runtime.release_singleton_lock(b)
