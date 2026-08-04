"""GET/PUT /v1/chat/mcp-servers — user MCP servers opted into chat.

The sidecar owns ~/ghostbrain/mcp-servers.json (ghostbrain.llm.mcp_servers);
these routes are the only way the desktop settings UI reads or writes it.
Env values are write-only: responses carry key names (envKeys), and a PUT
entry with env=null keeps whatever is already stored for that server name.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ghostbrain.llm import mcp_servers

log = logging.getLogger("ghostbrain.api.mcp_servers")

router = APIRouter(prefix="/v1/chat", tags=["chat"])


def claude_config_path() -> Path:
    return Path.home() / ".claude.json"


class ServerIn(BaseModel):
    name: str
    command: str
    args: list[str] = []
    env: dict[str, str] | None = None  # null = keep stored env for this name
    enabled: bool = False
    tools: str = ""


class PutBody(BaseModel):
    servers: list[ServerIn]


def _available(saved_names: set[str]) -> list[dict]:
    """Import candidates from ~/.claude.json: stdio servers with valid, unsaved names."""
    try:
        raw = json.loads(claude_config_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except Exception as err:  # noqa: BLE001 — someone else's config file
        log.warning("unreadable claude config: %s", err)
        return []
    out = []
    for name, spec in (raw.get("mcpServers") or {}).items():
        if name in saved_names or not isinstance(spec, dict):
            continue
        if not mcp_servers.NAME_RE.match(name) or name in mcp_servers.RESERVED_NAMES:
            continue
        if spec.get("type") not in (None, "stdio"):
            continue  # sse/http servers can't be spawned as a subprocess
        command = spec.get("command")
        if not isinstance(command, str) or not command.strip():
            continue
        args = spec.get("args") if isinstance(spec.get("args"), list) else []
        out.append({"name": name, "command": command, "args": args})
    return sorted(out, key=lambda s: s["name"])


@router.get("/mcp-servers")
def get_servers() -> dict[str, Any]:
    saved = mcp_servers.load()
    return {
        "servers": mcp_servers.redact(saved),
        "available": _available({s["name"] for s in saved}),
    }


@router.put("/mcp-servers")
def put_servers(body: PutBody) -> dict[str, Any]:
    stored_env = {s["name"]: s["env"] for s in mcp_servers.load()}
    entries = []
    for s in body.servers:
        entry = s.model_dump()
        if entry["env"] is None:
            entry["env"] = stored_env.get(entry["name"], {})
        entries.append(entry)
    try:
        saved = mcp_servers.save(entries)
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    return {"servers": mcp_servers.redact(saved)}
