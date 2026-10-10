"""Notice when the process that spawned the sidecar (the Electron app) is gone.

However the app dies — clean quit, crash, SIGKILL, a dev reload that skips
``stop()`` — the sidecar used to keep running, reparented to pid 1. Opt-in
via ``GHOSTBRAIN_PARENT_WATCH=1`` (the desktop sets it and keeps stdin a
pipe): the sidecar then treats

- EOF on stdin (the OS closes the pipe's write end when the parent exits), and
- on POSIX, ``os.getppid()`` changing from its startup value (reparenting)

as "parent gone" and calls ``on_parent_gone`` exactly once. Without the env
var nothing is watched, so ``python -m ghostbrain.api`` from a terminal (stdin
a TTY or /dev/null) never self-terminates.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from collections.abc import Callable

log = logging.getLogger("ghostbrain.api.parent_watch")

ENV_VAR = "GHOSTBRAIN_PARENT_WATCH"


def _enabled() -> bool:
    return os.environ.get(ENV_VAR, "").strip().lower() in ("1", "true", "yes", "on")


def _watch_stdin(gone: threading.Event) -> None:
    try:
        fd = sys.stdin.fileno()
    except (AttributeError, OSError, ValueError):
        log.warning("parent watch: no usable stdin; relying on ppid only")
        return
    try:
        while os.read(fd, 4096):
            pass  # nothing is sent on stdin; anything that is, is ignored
        reason = "stdin EOF"
    except OSError as e:
        reason = f"stdin read failed: {e}"
    log.warning("parent watch: %s", reason)
    gone.set()


def start(
    on_parent_gone: Callable[[], None], *, poll_s: float = 1.0,
) -> threading.Thread | None:
    """Watch for the parent going away; returns the daemon watcher thread,
    or None when ``GHOSTBRAIN_PARENT_WATCH`` is unset."""
    if not _enabled():
        return None

    gone = threading.Event()
    start_ppid = os.getppid() if sys.platform != "win32" else None
    threading.Thread(
        target=_watch_stdin, args=(gone,), daemon=True, name="parent-watch-stdin",
    ).start()

    def _watch() -> None:
        while not gone.wait(poll_s):
            # Windows never reparents (getppid keeps the dead parent's pid),
            # so only stdin EOF applies there.
            if start_ppid is not None and os.getppid() != start_ppid:
                log.warning(
                    "parent watch: ppid changed %d -> %d", start_ppid, os.getppid(),
                )
                break
        on_parent_gone()

    thread = threading.Thread(target=_watch, daemon=True, name="parent-watch")
    thread.start()
    log.info("parent watch armed (ppid=%s)", start_ppid)
    return thread
