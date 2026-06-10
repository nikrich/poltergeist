"""Streaming agentic chat turns via the `claude` CLI.

Unlike ``llm/client.py`` (request/response, used by the worker/digest paths),
this module streams: it spawns ``claude -p --output-format stream-json`` and
yields SSE-ready event dicts as lines arrive. Sessions persist CLI-side so
``--resume <session_id>`` gives multi-turn memory for free.
"""
from __future__ import annotations

import json
import logging
import shutil
import sys
from pathlib import Path

log = logging.getLogger("ghostbrain.llm.agent")

# tool name → (short name, human summary template over the tool input)
TOOL_SUMMARIES: dict[str, tuple[str, str]] = {
    "mcp__poltergeist__poltergeist_search": ("search", "searched vault: {query}"),
    "mcp__poltergeist__poltergeist_get_note": ("get_note", "read note: {path}"),
    "mcp__poltergeist__poltergeist_ask": ("ask", "asked the archive: {question}"),
}


def _tool_event(block: dict) -> dict:
    name = block.get("name", "")
    short, template = TOOL_SUMMARIES.get(name, (name, name))
    try:
        summary = template.format(**(block.get("input") or {}))
    except (KeyError, IndexError):
        summary = short
    return {"type": "tool", "name": short, "summary": summary}


def parse_stream_line(line: str) -> list[dict]:
    """One stdout line from claude stream-json → zero or more event dicts.

    Event vocabulary (shared with the renderer, see shared/api-types.ts):
      {"type": "session", "session_id"}            — CLI session started
      {"type": "delta", "text"}                    — streamed text token
      {"type": "tool", "name", "summary"}          — tool call started
      {"type": "done", "text", "session_id"}       — terminal success
      {"type": "error", "message"}                 — terminal failure
    """
    line = line.strip()
    if not line:
        return []
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return []
    if not isinstance(obj, dict):
        return []
    t = obj.get("type")

    if t == "system" and obj.get("subtype") == "init":
        sid = obj.get("session_id")
        return [{"type": "session", "session_id": sid}] if sid else []

    if t == "stream_event":
        ev = obj.get("event") or {}
        if ev.get("type") == "content_block_delta":
            delta = ev.get("delta") or {}
            if delta.get("type") == "text_delta" and delta.get("text"):
                return [{"type": "delta", "text": delta["text"]}]
        return []

    if t == "assistant":
        content = (obj.get("message") or {}).get("content") or []
        return [
            _tool_event(b)
            for b in content
            if isinstance(b, dict) and b.get("type") == "tool_use"
        ]

    if t == "result":
        if obj.get("is_error") or obj.get("subtype") != "success":
            msg = str(obj.get("result") or obj.get("subtype") or "unknown error")
            return [{"type": "error", "message": msg}]
        return [
            {
                "type": "done",
                "text": str(obj.get("result") or ""),
                "session_id": str(obj.get("session_id") or ""),
            }
        ]

    return []


DEFAULT_CHAT_MODEL = "sonnet"
CHAT_TIMEOUT_S = 300
# Chat turns can chain several MCP calls (each poltergeist_ask is itself an
# LLM call sidecar-side) — give more headroom than the worker's $0.50.
CHAT_BUDGET_USD = 1.00

ALLOWED_TOOLS = ",".join(TOOL_SUMMARIES)

CHAT_SYSTEM_PROMPT = """You are Poltergeist, the user's second brain. You live inside their \
personal knowledge app and answer questions about their own work, notes, \
meetings, and decisions using the vault tools available to you.

Rules:
1. Use the tools to ground every answer: poltergeist_search to locate notes \
(cheap), poltergeist_get_note to read one, poltergeist_ask for a synthesized \
cited answer when the question is broad.
2. Cite vault notes as Obsidian wikilinks containing the vault-relative path \
exactly as the tools return it, e.g. [[20-contexts/sanlam/decision-x]] or \
[[10-daily/2026-06-09|yesterday's daily]]. The app renders these as clickable \
links — never invent paths.
3. If the vault doesn't cover something, say so plainly. Do NOT invent facts \
about the user's work.
4. Answer in markdown. Lead with the answer; keep it concrete and specific, \
using the user's own terminology.
5. This is an ongoing conversation — you may rely on earlier turns without \
re-fetching notes you already read."""


def find_mcp_binary() -> str | None:
    """Locate ``ghostbrain-mcp``: it lives next to the python running the
    sidecar (same venv / PyInstaller dist), falling back to PATH."""
    candidate = Path(sys.executable).parent / "ghostbrain-mcp"
    if candidate.is_file():
        return str(candidate)
    return shutil.which("ghostbrain-mcp")


def build_chat_command(
    binary: str,
    prompt: str,
    *,
    model: str = DEFAULT_CHAT_MODEL,
    session_id: str | None = None,
    mcp_binary: str | None = None,
) -> list[str]:
    cmd = [
        binary,
        "--print",
        "--output-format", "stream-json",
        "--include-partial-messages",
        "--verbose",  # required by claude for stream-json with --print
        "--model", model,
        "--system-prompt", CHAT_SYSTEM_PROMPT,
        "--exclude-dynamic-system-prompt-sections",
        "--max-budget-usd", f"{CHAT_BUDGET_USD:.4f}",
    ]
    if mcp_binary:
        cmd += [
            "--mcp-config",
            json.dumps({"mcpServers": {"poltergeist": {"command": mcp_binary}}}),
            "--strict-mcp-config",  # don't drag in the user's other MCP servers
            "--allowedTools", ALLOWED_TOOLS,
        ]
    if session_id:
        cmd += ["--resume", session_id]
    cmd.append(prompt)
    return cmd
