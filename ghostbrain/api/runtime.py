# ghostbrain/api/runtime.py
"""On-disk descriptor advertising the running sidecar to local MCP clients.

The sidecar picks a random port + bearer token on every boot and prints them
to stdout for the Electron parent. The MCP shim is spawned independently by
Claude Code, so it can't see that banner. This module persists {port, token,
pid, ...} to ~/ghostbrain/run/sidecar.json on boot (chmod 600 — it holds the
token) and removes it on exit. Readers liveness-check the pid so a crash-
leftover file reads as "not running".
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import IO


def _try_lock_exclusive(fh: IO) -> bool:
    """Non-blocking exclusive lock on an open file. True if acquired."""
    if sys.platform == "win32":
        import msvcrt

        try:
            # Lock the first byte of the file. Region locks may extend past
            # EOF on Windows, so this works on the just-truncated empty file.
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    else:
        import fcntl

        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False


def _unlock(fh: IO) -> None:
    if sys.platform == "win32":
        import msvcrt

        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def acquire_singleton_lock(name: str) -> IO | None:
    """Best-effort single-instance guard via an OS file lock.

    Two ``ghostbrain.api`` instances (the bundled app sidecar + a stray
    ``python -m ghostbrain.api``) both booting the scheduler/recorder race on
    the shared state file and double-record meetings — the desktop then can't
    stop a recording it doesn't own. Callers acquire this before starting the
    scheduler and skip it if the lock is already held.

    Uses flock on POSIX and msvcrt region locking on Windows (fcntl does not
    exist there — importing it unconditionally killed the packaged sidecar on
    boot).

    Returns the open, locked file object (keep a reference for the process
    lifetime — the OS releases the lock when it closes or the process dies) or
    ``None`` if another live process already holds it.
    """
    from ghostbrain.recorder.state import state_dir

    lock_path = state_dir() / f"{name}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        # "a" not "w": on Windows the holder's region lock makes the truncate
        # implied by "w" fail with PermissionError before we ever get to the
        # lock attempt.
        fh = open(lock_path, "a+")
    except OSError:
        return None
    if not _try_lock_exclusive(fh):
        fh.close()
        return None
    try:
        fh.truncate(0)
        fh.write(str(os.getpid()))
        fh.flush()
    except OSError:
        pass
    return fh


def release_singleton_lock(fh: IO | None) -> None:
    """Release a lock from acquire_singleton_lock(). Never raises."""
    if fh is None:
        return
    try:
        _unlock(fh)
    except (OSError, ValueError):
        pass
    try:
        fh.close()
    except OSError:
        pass


def run_dir() -> Path:
    """Directory for runtime state. Override with GHOSTBRAIN_RUN_DIR (tests)."""
    raw = os.environ.get("GHOSTBRAIN_RUN_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / "ghostbrain" / "run").resolve()


def descriptor_path() -> Path:
    return run_dir() / "sidecar.json"


def setup_file_logging() -> logging.handlers.RotatingFileHandler:
    """Attach a rotating file handler at <run_dir>/logs/sidecar.log.

    Before this, the sidecar's only record was a 4KB in-memory stderr tail
    held by the Electron parent — any incident that survived a restart was
    undiagnosable. Bounded at 5MB × 3 backups so it can't eat the disk.
    Idempotent: repeated calls return the already-installed handler.
    """
    root = logging.getLogger()
    for h in root.handlers:
        if getattr(h, "_ghostbrain_file_log", False):
            return h  # type: ignore[return-value]
    log_path = run_dir() / "logs" / "sidecar.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    handler.setLevel(logging.INFO)
    handler._ghostbrain_file_log = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    if root.level > logging.INFO or root.level == logging.NOTSET:
        root.setLevel(logging.INFO)
    return handler


def write_descriptor(
    *, port: int, token: str, pid: int, version: str, started_at: str
) -> Path:
    """Atomically write the descriptor with 0600 perms. Returns its path."""
    d = run_dir()
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    target = descriptor_path()
    tmp = target.with_name(target.name + ".tmp")
    payload = json.dumps(
        {
            "port": port,
            "token": token,
            "pid": pid,
            "version": version,
            "started_at": started_at,
        }
    )
    fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        os.write(fd, payload.encode())
    finally:
        os.close(fd)
    os.replace(tmp, target)
    return target


def load_descriptor() -> dict | None:
    """Return the descriptor dict, or None if absent/unparseable/process-dead."""
    path = descriptor_path()
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    pid = data.get("pid")
    if not isinstance(pid, int):
        return None
    # NOTE: liveness only — if the sidecar crashed and the OS recycled its PID
    # to an unrelated process, this still reads as "running". Acceptable for a
    # local single-user tool; revisit with a start-time fingerprint if needed.
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None  # process is gone
    except PermissionError:
        pass  # alive but owned by another user — still "running"
    except OSError:
        return None
    return data


def remove_descriptor() -> None:
    """Best-effort delete of OUR OWN descriptor. Never raises.

    Pid-guarded: only unlink when the file was written by this process.
    Unguarded, any transient ghostbrain-api exit (health probe, second
    instance losing the singleton race) deleted the live sidecar's
    descriptor — every MCP client then failed with "Poltergeist isn't
    running" while the sidecar was healthy (seen 2026-08-05).
    """
    try:
        body = json.loads(descriptor_path().read_text(encoding="utf-8"))
        if int(body.get("pid", -1)) != os.getpid():
            return
        descriptor_path().unlink(missing_ok=True)
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        # Unreadable/corrupt descriptor: it isn't provably ours — leave it.
        pass
