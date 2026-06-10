"""Streaming agentic chat turns via the `claude` CLI.

Unlike ``llm/client.py`` (request/response, used by the worker/digest paths),
this module streams: it spawns ``claude -p --output-format stream-json`` and
yields SSE-ready event dicts as lines arrive. Sessions persist CLI-side so
``--resume <session_id>`` gives multi-turn memory for free.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

from ghostbrain.llm.client import _find_claude_binary

log = logging.getLogger("ghostbrain.llm.agent")


@dataclasses.dataclass
class _RunningTurn:
    cancelled: threading.Event
    kill: Callable[[], None]


_running_lock = threading.Lock()
_running: dict[str, _RunningTurn] = {}


def cancel_turn(key: str) -> bool:
    """Kill the in-flight turn for ``key`` (if any). Returns True if one was
    running. The killed run yields a terminal 'stopped' error event, which
    persists any partial text as interrupted and releases the busy guard."""
    with _running_lock:
        entry = _running.get(key)
    if entry is None:
        return False
    entry.cancelled.set()
    entry.kill()
    return True


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
    except Exception:
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
    # `--` terminates option parsing — without it a variadic flag like
    # --allowedTools swallows the positional prompt (verified live).
    cmd += ["--", prompt]
    return cmd


BINARY_MISSING_MESSAGE = (
    "`claude` binary not found. Install Claude Code "
    "(`npm i -g @anthropic-ai/claude-code`), or set `GHOSTBRAIN_CLAUDE_BIN` "
    "to its absolute path."
)


class ResumeFailed(RuntimeError):
    """`--resume <id>` was rejected (stale session). Caller retries fresh."""


def run_chat_turn(
    prompt: str,
    *,
    session_id: str | None = None,
    timeout_s: int = CHAT_TIMEOUT_S,
    binary: str | None = None,
    mcp_binary: str | None = "auto",
    turn_key: str | None = None,
):
    """Yield event dicts for one agentic chat turn.

    Contract: yields zero or more session/delta/tool events, then exactly one
    terminal done/error event — EXCEPT when ``--resume`` fails before claude
    produced anything, which raises ResumeFailed so the caller can retry the
    turn without a session (we must not emit a terminal event in that case,
    the retry will produce its own).
    """
    binary = binary or _find_claude_binary()
    if binary is None:
        yield {"type": "error", "message": BINARY_MISSING_MESSAGE}
        return
    if mcp_binary == "auto":
        mcp_binary = find_mcp_binary()

    cmd = build_chat_command(
        binary, prompt, session_id=session_id, mcp_binary=mcp_binary
    )
    log.info("chat turn: resume=%s mcp=%s", bool(session_id), bool(mcp_binary))
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        env={**os.environ, "CLAUDE_CODE_NO_TELEMETRY": "1"},
        # Own process group: claude spawns descendants (ghostbrain-mcp, tool
        # subprocesses) that inherit the stdout pipe write-end — killing only
        # the direct child would leave the pipe open and our read loop blocked
        # until the orphans exit. Group-kill (below) takes them all out.
        start_new_session=True,
    )

    def _kill_group() -> None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass  # already gone
        except Exception:  # noqa: BLE001 — never let cleanup raise past us
            proc.kill()

    timed_out = threading.Event()
    cancelled = threading.Event()

    def _kill() -> None:
        timed_out.set()
        _kill_group()

    # Register this turn in the cancellation registry so an external caller
    # can kill the subprocess (and unblock the read loop) while we're blocked
    # on proc.stdout — GeneratorExit alone can't reach a running generator.
    if turn_key is not None:
        with _running_lock:
            _running[turn_key] = _RunningTurn(cancelled=cancelled, kill=_kill_group)

    # Watchdog instead of readline timeouts: if claude wedges with no output,
    # a blocking readline would hang forever. The timer fires once, kills the
    # process, and the read loop unblocks on EOF.
    killer = threading.Timer(timeout_s, _kill)
    killer.start()
    saw_any = False
    saw_terminal = False
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            for event in parse_stream_line(raw):
                saw_any = True
                if event["type"] in ("done", "error"):
                    saw_terminal = True
                yield event
        proc.wait()
    finally:
        # Covers normal exit, timeout, and client-disconnect (GeneratorExit
        # propagates here when the SSE consumer goes away — kill claude so
        # we don't leak a billing subprocess).
        killer.cancel()
        if proc.poll() is None:
            _kill_group()
            proc.wait()
        if turn_key is not None:
            with _running_lock:
                _running.pop(turn_key, None)

    if saw_terminal:
        return
    stderr = (proc.stderr.read() if proc.stderr else "")[:500].strip()
    # cancelled is checked FIRST: a cancelled resumed turn that died before any
    # output must NOT be misclassified as ResumeFailed (which would trigger a
    # pointless retry).
    if cancelled.is_set():
        yield {"type": "error", "message": "stopped", "interrupted": True}
        return
    if timed_out.is_set():
        yield {
            "type": "error",
            "message": f"poltergeist took longer than {timeout_s}s and was stopped.",
            "interrupted": True,
        }
        return
    if session_id and not saw_any and proc.returncode != 0:
        raise ResumeFailed(stderr or "resume failed")
    yield {
        "type": "error",
        "message": stderr or f"claude exited with code {proc.returncode}",
    }
