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
import os
from pathlib import Path
from typing import IO


def acquire_singleton_lock(name: str) -> IO | None:
    """Best-effort single-instance guard via flock.

    Two ``ghostbrain.api`` instances (the bundled app sidecar + a stray
    ``python -m ghostbrain.api``) both booting the scheduler/recorder race on
    the shared state file and double-record meetings — the desktop then can't
    stop a recording it doesn't own. Callers acquire this before starting the
    scheduler and skip it if the lock is already held.

    Returns the open, locked file object (keep a reference for the process
    lifetime — the OS releases the lock when it closes or the process dies) or
    ``None`` if another live process already holds it.
    """
    import fcntl

    from ghostbrain.recorder.state import state_dir

    lock_path = state_dir() / f"{name}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "w")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
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
        import fcntl

        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
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
    """Best-effort delete. Never raises."""
    try:
        descriptor_path().unlink(missing_ok=True)
    except OSError:
        pass
