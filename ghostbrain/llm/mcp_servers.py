"""User MCP servers opted into chat.

Stored at ~/ghostbrain/mcp-servers.json, owned by the sidecar. Entries here are
merged into the chat command's pinned --mcp-config (see llm/agent.py) — this
file is the single source of truth the settings UI edits over the API.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

log = logging.getLogger("ghostbrain.llm.mcp_servers")

NAME_RE = re.compile(r"^[a-z0-9_-]{1,64}$")
RESERVED_NAMES = {"poltergeist"}

_DEFAULTS: dict[str, Any] = {"args": [], "env": {}, "enabled": False, "tools": ""}


def config_path() -> Path:
    return Path.home() / "ghostbrain" / "mcp-servers.json"


def validate(entry: Any) -> list[str]:
    """Return problems with one server entry; [] when valid."""
    if not isinstance(entry, dict):
        return ["entry must be an object"]
    errors: list[str] = []
    name = entry.get("name")
    if not isinstance(name, str) or not NAME_RE.match(name):
        errors.append("name must match ^[a-z0-9_-]{1,64}$")
    elif name in RESERVED_NAMES:
        errors.append(f'name "{name}" is reserved')
    command = entry.get("command")
    if not isinstance(command, str) or not command.strip():
        errors.append("command must be a non-empty string")
    args = entry.get("args", [])
    if not isinstance(args, list) or any(not isinstance(a, str) for a in args):
        errors.append("args must be a list of strings")
    env = entry.get("env", {})
    if not isinstance(env, dict) or any(
        not isinstance(k, str) or not isinstance(v, str) for k, v in env.items()
    ):
        errors.append("env must map string keys to string values")
    tools = entry.get("tools", "")
    if not isinstance(tools, str):
        errors.append("tools must be a comma-separated string")
    if not isinstance(entry.get("enabled", False), bool):
        errors.append("enabled must be a boolean")
    return errors


def _normalize(entry: dict) -> dict:
    out = {**_DEFAULTS, **entry}
    return {
        "name": out["name"],
        "command": out["command"],
        "args": list(out["args"]),
        "env": dict(out["env"]),
        "enabled": bool(out["enabled"]),
        "tools": out["tools"].strip(),
    }


def load() -> list[dict]:
    """Saved entries; missing or corrupt file is an empty list, never an error."""
    path = config_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        servers = raw.get("servers", [])
        return [_normalize(s) for s in servers if not validate(s)]
    except FileNotFoundError:
        return []
    except Exception as err:  # noqa: BLE001 — a broken file must never block chat
        log.warning("ignoring unreadable %s: %s", path, err)
        return []


def load_enabled() -> list[dict]:
    return [s for s in load() if s["enabled"]]


def save(servers: list[dict]) -> list[dict]:
    """Validate all entries, write atomically, return the normalized list."""
    errors: list[str] = []
    names: set[str] = set()
    for entry in servers:
        errors += [f"{entry.get('name', '?')}: {e}" for e in validate(entry)]
        name = entry.get("name")
        if name in names:
            errors.append(f'duplicate server name "{name}"')
        names.add(name)
    if errors:
        raise ValueError("; ".join(errors))
    normalized = [_normalize(s) for s in servers]
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"servers": normalized}, indent=2), encoding="utf-8")
    tmp.replace(path)
    return normalized


def redact(servers: list[dict]) -> list[dict]:
    """API-facing view: env values never leave the sidecar, only key names."""
    return [
        {**{k: v for k, v in s.items() if k != "env"}, "envKeys": sorted(s["env"])}
        for s in servers
    ]
