"""Shared helpers for ~/.claude/settings.json (Claude Code's user settings).

Used by the Claude Code connector provider, the doctor's `claude-hook` check,
and `setup install-hook`. Only `hooks.SessionEnd` is ever touched.
"""
from __future__ import annotations

import json
import os
import shlex
import tempfile
from pathlib import Path


def settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def load() -> dict:
    """Return the settings document, {} if the file is missing.

    Raises ValueError when the file exists but is not valid JSON — callers
    must refuse to write over a file they cannot parse.
    """
    p = settings_path()
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("settings.json top level is not an object")  # noqa: TRY004 — ValueError is the documented contract
    return data


def write_atomic(doc: dict) -> None:
    p = settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".settings.", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2)
        os.replace(tmp, p)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def session_end_commands(doc: dict) -> list[str]:
    out: list[str] = []
    for entry in (doc.get("hooks") or {}).get("SessionEnd") or []:
        for hook in entry.get("hooks") or []:
            cmd = hook.get("command")
            if isinstance(cmd, str) and cmd.strip():
                out.append(cmd)
    return out


def hook_command_exists(command: str) -> bool:
    try:
        first = shlex.split(command)[0]
    except (ValueError, IndexError):
        return False
    return Path(first).expanduser().exists()
