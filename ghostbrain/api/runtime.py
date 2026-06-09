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
    tmp.write_text(payload)
    os.chmod(tmp, 0o600)
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
