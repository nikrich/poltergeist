# Poltergeist Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A full multi-turn chat screen in the Poltergeist desktop app where each turn is an agentic `claude -p` run with the ghostbrain MCP tools, streaming tokens + tool activity live, with conversations persisted as JSON files.

**Architecture:** The FastAPI sidecar gains a `/v1/chat` API (CRUD + an SSE message endpoint). Each message spawns `claude -p --resume <session> --output-format stream-json --include-partial-messages` with `--mcp-config` pointing at the `ghostbrain-mcp` binary (which self-discovers the sidecar via `~/ghostbrain/run/sidecar.json`). The Electron main process relays the SSE stream to the renderer over a dedicated IPC channel. The renderer gets a new Chat screen (conversation list + thread); the old AskPanel is deleted.

**Tech Stack:** Python 3.11 / FastAPI / pytest (sidecar); Electron + React + zustand + React Query + Vitest (desktop); `claude` CLI subprocess for the LLM.

**Repo:** ALL work happens in `/Users/jannik/development/nikrich/ghost-brain` (NOT hive-ide). Spec: `docs/superpowers/specs/2026-06-10-poltergeist-chat-design.md`.

**Setup before Task 1:**

```bash
cd /Users/jannik/development/nikrich/ghost-brain
git checkout -b feat/poltergeist-chat
# Python tests use the repo venv. If .venv is missing:
#   python3.11 -m venv .venv && .venv/bin/pip install -e ".[dev,mcp]"
.venv/bin/pytest --version   # sanity check
cd desktop && npm test -- --run --reporter=dot 2>&1 | tail -3   # sanity check renderer tests pass before we start
```

---

## File structure

**Sidecar (Python):**

| File | Responsibility |
|---|---|
| `ghostbrain/paths.py` (modify) | add `chats_dir()` (env override `GHOSTBRAIN_CHATS_DIR`) |
| `ghostbrain/api/repo/chat_store.py` (create) | JSON-file-per-conversation CRUD, atomic writes |
| `ghostbrain/llm/agent.py` (create) | stream-json parser, chat command builder, `run_chat_turn` subprocess generator |
| `ghostbrain/api/repo/chat.py` (create) | turn orchestration: persist user msg → stream agent events → persist assistant msg, resume-failure retry |
| `ghostbrain/api/models/chat.py` (create) | pydantic schemas |
| `ghostbrain/api/routes/chat.py` (create) | `/v1/chat` CRUD + SSE message route |
| `ghostbrain/api/main.py` (modify) | mount chat router |
| `tests/test_chat_store.py`, `tests/test_agent_stream.py`, `tests/test_agent_run.py`, `ghostbrain/api/tests/test_chat.py` (create) | tests |

**Desktop (Electron/React):**

| File | Responsibility |
|---|---|
| `desktop/src/main/api-forwarder.ts` (modify) | allow PATCH/DELETE |
| `desktop/src/main/chat-stream.ts` (create) | SSE parser + stream relay (fetch → webContents.send), per-conversation abort |
| `desktop/src/main/index.ts` (modify) | register `gb:chat:send` / `gb:chat:stop` IPC; widen `gb:api:request` method allowlist |
| `desktop/src/preload/index.ts` (modify) | expose `gb.chat.send/stop` |
| `desktop/src/shared/types.ts` (modify) | bridge types (chat + PATCH/DELETE + `chat:event` listener) |
| `desktop/src/shared/api-types.ts` (modify) | Conversation/ChatMessage/ChatStreamEvent types |
| `desktop/src/renderer/lib/api/client.ts` (modify) | `patch()` / `del()` helpers |
| `desktop/src/renderer/lib/api/hooks.ts` (modify) | conversation queries/mutations; remove `useAsk` |
| `desktop/src/renderer/stores/chat.ts` (create) | streaming state (per-conversation buffer, tool chips, errors) |
| `desktop/src/renderer/screens/chat.tsx` (create) | Chat screen: conversation list + thread + composer |
| `desktop/src/renderer/stores/navigation.ts`, `components/Sidebar.tsx`, `App.tsx` (modify) | `chat` screen wiring |
| `desktop/src/renderer/screens/today.tsx` (modify), `components/AskPanel.tsx` (delete) | AskPanel removal; ⌘K → chat |
| `desktop/src/main/__tests__/chat-stream.test.ts`, `desktop/src/renderer/__tests__/chat-store.test.ts`, `desktop/src/renderer/__tests__/ChatScreen.test.tsx` (create) | tests |

---

### Task 1: Chat storage (`chats_dir` + `chat_store`)

**Files:**
- Modify: `ghostbrain/paths.py`
- Create: `ghostbrain/api/repo/chat_store.py`
- Test: `tests/test_chat_store.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_chat_store.py`:

```python
"""Chat conversation storage: JSON file per conversation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ghostbrain.api.repo import chat_store


@pytest.fixture
def chats(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "chats"
    monkeypatch.setenv("GHOSTBRAIN_CHATS_DIR", str(d))
    return d


def test_create_writes_file_with_defaults(chats: Path):
    conv = chat_store.create()
    assert conv["title"] == "new chat"
    assert conv["messages"] == []
    assert conv["claude_session_id"] is None
    on_disk = json.loads((chats / f"{conv['id']}.json").read_text())
    assert on_disk == conv


def test_get_missing_returns_none(chats: Path):
    assert chat_store.get("nope") is None


def test_list_skips_corrupt_and_sorts_newest_first(chats: Path):
    a = chat_store.create()
    b = chat_store.create()
    chat_store.append_user_message(chat_store.get(b["id"]), "later message")
    chats.joinpath("garbage.json").write_text("{not json")
    items = chat_store.list_all()
    assert [c["id"] for c in items] == [b["id"], a["id"]]
    assert items[0]["message_count"] == 1
    assert "messages" not in items[0]


def test_first_user_message_derives_title(chats: Path):
    conv = chat_store.create()
    long_text = "what did we   decide about " + "x" * 100
    chat_store.append_user_message(conv, long_text)
    again = chat_store.get(conv["id"])
    assert again["title"].startswith("what did we decide about")
    assert len(again["title"]) <= 60
    # second message must NOT re-derive the title
    chat_store.append_user_message(again, "another question entirely")
    assert chat_store.get(conv["id"])["title"].startswith("what did we decide")


def test_rename_trims_and_caps(chats: Path):
    conv = chat_store.create()
    chat_store.rename(conv["id"], "  My Chat  ")
    assert chat_store.get(conv["id"])["title"] == "My Chat"
    assert chat_store.rename("missing", "x") is None


def test_delete(chats: Path):
    conv = chat_store.create()
    assert chat_store.delete(conv["id"]) is True
    assert chat_store.get(conv["id"]) is None
    assert chat_store.delete(conv["id"]) is False


def test_append_assistant_message_with_tools_and_session(chats: Path):
    conv = chat_store.create()
    chat_store.append_user_message(conv, "q")
    chat_store.set_session_id(conv, "sess-1")
    chat_store.append_assistant_message(
        conv, "answer", [{"name": "search", "summary": "searched vault: q"}]
    )
    got = chat_store.get(conv["id"])
    assert got["claude_session_id"] == "sess-1"
    assert got["messages"][1] == {
        "role": "assistant",
        "text": "answer",
        "tools": [{"name": "search", "summary": "searched vault: q"}],
        "interrupted": False,
    }


def test_interrupted_flag_persists(chats: Path):
    conv = chat_store.create()
    chat_store.append_assistant_message(conv, "partial", [], interrupted=True)
    assert chat_store.get(conv["id"])["messages"][0]["interrupted"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jannik/development/nikrich/ghost-brain && .venv/bin/pytest tests/test_chat_store.py -v`
Expected: FAIL — `ImportError: cannot import name 'chat_store'`

- [ ] **Step 3: Implement**

Add to `ghostbrain/paths.py` (after `state_dir()`):

```python
def chats_dir() -> Path:
    """Chat conversations live outside the vault (not synced, not indexed).

    Override with GHOSTBRAIN_CHATS_DIR (tests)."""
    raw = os.environ.get("GHOSTBRAIN_CHATS_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / "ghostbrain" / "chats").resolve()
```

Create `ghostbrain/api/repo/chat_store.py`:

```python
"""JSON-file-per-conversation storage for poltergeist chat.

One file per conversation at ``chats_dir()/<id>.json``. Files are the source
of truth — no DB, no cache. Writes are atomic (tmp + rename) so a crash
mid-write never corrupts a conversation. Corrupt files are skipped on list
and read as missing on get; chat must keep working even if one file rots.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path

from ghostbrain.paths import chats_dir

log = logging.getLogger("ghostbrain.chat.store")

TITLE_MAX_LEN = 60


def _conv_path(conv_id: str) -> Path:
    return chats_dir() / f"{conv_id}.json"


def _write(conv: dict) -> None:
    d = chats_dir()
    d.mkdir(parents=True, exist_ok=True)
    target = _conv_path(conv["id"])
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(conv, ensure_ascii=False, indent=2))
    tmp.replace(target)


def derive_title(text: str) -> str:
    collapsed = " ".join(text.split())
    return collapsed[:TITLE_MAX_LEN] or "new chat"


def create() -> dict:
    now = time.time()
    conv = {
        "id": uuid.uuid4().hex,
        "title": "new chat",
        "created_at": now,
        "updated_at": now,
        "claude_session_id": None,
        "messages": [],
    }
    _write(conv)
    return conv


def get(conv_id: str) -> dict | None:
    path = _conv_path(conv_id)
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError):
        log.warning("unreadable conversation file: %s", path)
        return None


def list_all() -> list[dict]:
    """Conversation summaries (no message bodies), newest-updated first."""
    d = chats_dir()
    if not d.exists():
        return []
    out: list[dict] = []
    for p in d.glob("*.json"):
        try:
            conv = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            log.warning("skipping unreadable conversation file: %s", p)
            continue
        out.append(
            {
                "id": conv["id"],
                "title": conv["title"],
                "created_at": conv["created_at"],
                "updated_at": conv["updated_at"],
                "message_count": len(conv.get("messages", [])),
            }
        )
    out.sort(key=lambda c: c["updated_at"], reverse=True)
    return out


def rename(conv_id: str, title: str) -> dict | None:
    conv = get(conv_id)
    if conv is None:
        return None
    conv["title"] = title.strip()[:TITLE_MAX_LEN]
    conv["updated_at"] = time.time()
    _write(conv)
    return conv


def delete(conv_id: str) -> bool:
    path = _conv_path(conv_id)
    if not path.exists():
        return False
    path.unlink()
    return True


def append_user_message(conv: dict, text: str) -> dict:
    conv["messages"].append({"role": "user", "text": text})
    if len(conv["messages"]) == 1:
        conv["title"] = derive_title(text)
    conv["updated_at"] = time.time()
    _write(conv)
    return conv


def append_assistant_message(
    conv: dict, text: str, tools: list[dict], *, interrupted: bool = False
) -> dict:
    conv["messages"].append(
        {"role": "assistant", "text": text, "tools": tools, "interrupted": interrupted}
    )
    conv["updated_at"] = time.time()
    _write(conv)
    return conv


def set_session_id(conv: dict, session_id: str) -> dict:
    conv["claude_session_id"] = session_id
    _write(conv)
    return conv
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_chat_store.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/paths.py ghostbrain/api/repo/chat_store.py tests/test_chat_store.py
git commit -m "feat(chat): conversation storage — one JSON file per chat"
```

---

### Task 2: stream-json event parser

**Files:**
- Create: `ghostbrain/llm/agent.py`
- Test: `tests/test_agent_stream.py`

The `claude -p --output-format stream-json --include-partial-messages --verbose` stdout is one JSON object per line. The shapes we consume:

- `{"type":"system","subtype":"init","session_id":"..."}` → capture session id
- `{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"..."}}}` → text token
- `{"type":"assistant","message":{"content":[{"type":"tool_use","name":"mcp__poltergeist__poltergeist_search","input":{"query":"..."}}]}}` → tool activity (text blocks in assistant events are IGNORED — they duplicate the deltas)
- `{"type":"result","subtype":"success","result":"<full text>","session_id":"..."}` → terminal success
- `{"type":"result","subtype":"error_*", ...}` or `"is_error": true` → terminal error

- [ ] **Step 1: Write the failing tests**

Create `tests/test_agent_stream.py`:

```python
"""parse_stream_line: claude stream-json lines → SSE-ready event dicts."""
from __future__ import annotations

import json

from ghostbrain.llm.agent import parse_stream_line


def line(obj: dict) -> str:
    return json.dumps(obj)


def test_blank_and_non_json_lines_ignored():
    assert parse_stream_line("") == []
    assert parse_stream_line("   ") == []
    assert parse_stream_line("not json") == []


def test_init_yields_session_event():
    events = parse_stream_line(
        line({"type": "system", "subtype": "init", "session_id": "s-1"})
    )
    assert events == [{"type": "session", "session_id": "s-1"}]


def test_text_delta_yields_delta():
    events = parse_stream_line(
        line(
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "hel"},
                },
            }
        )
    )
    assert events == [{"type": "delta", "text": "hel"}]


def test_non_text_delta_ignored():
    events = parse_stream_line(
        line(
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "input_json_delta", "partial_json": "{"},
                },
            }
        )
    )
    assert events == []


def test_assistant_tool_use_yields_tool_event_with_summary():
    events = parse_stream_line(
        line(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "let me look"},
                        {
                            "type": "tool_use",
                            "name": "mcp__poltergeist__poltergeist_search",
                            "input": {"query": "standup notes"},
                        },
                    ]
                },
            }
        )
    )
    assert events == [
        {"type": "tool", "name": "search", "summary": "searched vault: standup notes"}
    ]


def test_unknown_tool_falls_back_to_raw_name():
    events = parse_stream_line(
        line(
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "tool_use", "name": "WebSearch", "input": {}}]
                },
            }
        )
    )
    assert events == [{"type": "tool", "name": "WebSearch", "summary": "WebSearch"}]


def test_result_success_yields_done():
    events = parse_stream_line(
        line(
            {
                "type": "result",
                "subtype": "success",
                "result": "the answer",
                "session_id": "s-1",
            }
        )
    )
    assert events == [{"type": "done", "text": "the answer", "session_id": "s-1"}]


def test_result_error_yields_error():
    events = parse_stream_line(
        line(
            {
                "type": "result",
                "subtype": "error_max_budget_usd",
                "is_error": True,
                "result": "budget exceeded",
            }
        )
    )
    assert events == [{"type": "error", "message": "budget exceeded"}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_agent_stream.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ghostbrain.llm.agent'`

- [ ] **Step 3: Implement**

Create `ghostbrain/llm/agent.py`:

```python
"""Streaming agentic chat turns via the `claude` CLI.

Unlike ``llm/client.py`` (request/response, used by the worker/digest paths),
this module streams: it spawns ``claude -p --output-format stream-json`` and
yields SSE-ready event dicts as lines arrive. Sessions persist CLI-side so
``--resume <session_id>`` gives multi-turn memory for free.
"""
from __future__ import annotations

import json
import logging

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_agent_stream.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/llm/agent.py tests/test_agent_stream.py
git commit -m "feat(chat): parse claude stream-json lines into chat events"
```

---

### Task 3: chat command builder + system prompt

**Files:**
- Modify: `ghostbrain/llm/agent.py`
- Test: `tests/test_agent_stream.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agent_stream.py`:

```python
from ghostbrain.llm.agent import ALLOWED_TOOLS, CHAT_SYSTEM_PROMPT, build_chat_command


def test_build_chat_command_first_turn_with_mcp():
    cmd = build_chat_command(
        "/bin/claude", "hello", mcp_binary="/venv/bin/ghostbrain-mcp"
    )
    assert cmd[0] == "/bin/claude"
    assert cmd[-1] == "hello"
    assert "--print" in cmd
    assert "--include-partial-messages" in cmd
    assert "--verbose" in cmd
    assert "--resume" not in cmd
    assert "--no-session-persistence" not in cmd  # we NEED sessions for resume
    i = cmd.index("--output-format")
    assert cmd[i + 1] == "stream-json"
    i = cmd.index("--mcp-config")
    mcp = json.loads(cmd[i + 1])
    assert mcp == {"mcpServers": {"poltergeist": {"command": "/venv/bin/ghostbrain-mcp"}}}
    assert "--strict-mcp-config" in cmd
    i = cmd.index("--allowedTools")
    assert cmd[i + 1] == ALLOWED_TOOLS
    assert "poltergeist_search" in ALLOWED_TOOLS


def test_build_chat_command_resume_and_no_mcp():
    cmd = build_chat_command("/bin/claude", "again", session_id="s-9", mcp_binary=None)
    i = cmd.index("--resume")
    assert cmd[i + 1] == "s-9"
    assert "--mcp-config" not in cmd


def test_system_prompt_mentions_wikilink_citations():
    assert "[[" in CHAT_SYSTEM_PROMPT
    i = build_chat_command("/bin/claude", "x").index("--system-prompt")
    assert build_chat_command("/bin/claude", "x")[i + 1] == CHAT_SYSTEM_PROMPT
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_agent_stream.py -v`
Expected: new tests FAIL — `ImportError: cannot import name 'build_chat_command'`

- [ ] **Step 3: Implement**

Add to `ghostbrain/llm/agent.py` (after the imports, extend them too):

```python
import shutil
import sys
from pathlib import Path
```

and after `TOOL_SUMMARIES` / parser code:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_agent_stream.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/llm/agent.py tests/test_agent_stream.py
git commit -m "feat(chat): chat command builder + poltergeist persona prompt"
```

---

### Task 4: `run_chat_turn` subprocess generator

**Files:**
- Modify: `ghostbrain/llm/agent.py`
- Test: `tests/test_agent_run.py`

Tests use a fake `claude` binary — a small shell script that prints fixture stream-json lines — so no real LLM call happens.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_agent_run.py`:

```python
"""run_chat_turn: subprocess lifecycle, timeout, resume-failure detection."""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from ghostbrain.llm.agent import ResumeFailed, run_chat_turn


def fake_claude(tmp_path: Path, body: str) -> str:
    """Write an executable shell script that ignores its args."""
    p = tmp_path / "fake-claude"
    p.write_text("#!/bin/sh\n" + body)
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return str(p)


HAPPY = r"""
cat <<'EOF'
{"type":"system","subtype":"init","session_id":"sess-1"}
{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"hi"}}}
{"type":"result","subtype":"success","result":"hi","session_id":"sess-1"}
EOF
"""


def test_happy_path_yields_events_in_order(tmp_path: Path):
    binary = fake_claude(tmp_path, HAPPY)
    events = list(run_chat_turn("q", binary=binary, mcp_binary=None))
    assert [e["type"] for e in events] == ["session", "delta", "done"]
    assert events[-1]["text"] == "hi"


def test_missing_binary_yields_error(monkeypatch: pytest.MonkeyPatch):
    # _find_claude_binary also probes well-known install paths (~/.local/bin
    # etc.), so env vars alone can't hide a locally installed claude — stub
    # the lookup itself.
    monkeypatch.setattr("ghostbrain.llm.agent._find_claude_binary", lambda: None)
    events = list(run_chat_turn("q", binary=None, mcp_binary=None))
    assert len(events) == 1
    assert events[0]["type"] == "error"
    assert "claude" in events[0]["message"]


def test_resume_failure_raises(tmp_path: Path):
    binary = fake_claude(tmp_path, 'echo "No conversation found" >&2\nexit 1\n')
    gen = run_chat_turn("q", session_id="stale", binary=binary, mcp_binary=None)
    with pytest.raises(ResumeFailed):
        list(gen)


def test_nonzero_exit_without_resume_yields_error(tmp_path: Path):
    binary = fake_claude(tmp_path, 'echo "boom" >&2\nexit 1\n')
    events = list(run_chat_turn("q", binary=binary, mcp_binary=None))
    assert events[-1]["type"] == "error"
    assert "boom" in events[-1]["message"]


def test_timeout_kills_process_and_yields_interrupted_error(tmp_path: Path):
    # Streams init + one delta but no result line, then hangs — the watchdog
    # must kill it and surface an interrupted error.
    body = r"""
cat <<'EOF'
{"type":"system","subtype":"init","session_id":"sess-1"}
{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"par"}}}
EOF
sleep 30
"""
    binary = fake_claude(tmp_path, body)
    events = list(run_chat_turn("q", binary=binary, mcp_binary=None, timeout_s=1))
    assert [e["type"] for e in events[:2]] == ["session", "delta"]
    assert events[-1]["type"] == "error"
    assert events[-1].get("interrupted") is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_agent_run.py -v`
Expected: FAIL — `ImportError: cannot import name 'ResumeFailed'`

- [ ] **Step 3: Implement**

Add to `ghostbrain/llm/agent.py` imports:

```python
import os
import subprocess
import threading
```

and at module level (reuse the binary lookup from the sibling client):

```python
from ghostbrain.llm.client import _find_claude_binary

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
        env={**os.environ, "CLAUDE_CODE_NO_TELEMETRY": "1"},
    )
    timed_out = threading.Event()

    def _kill() -> None:
        timed_out.set()
        proc.kill()

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
            proc.kill()
            proc.wait()

    if saw_terminal:
        return
    stderr = (proc.stderr.read() if proc.stderr else "")[:500].strip()
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_agent_run.py tests/test_agent_stream.py -v`
Expected: all pass (timeout test takes ~1s)

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/llm/agent.py tests/test_agent_run.py
git commit -m "feat(chat): streaming subprocess runner with timeout + resume detection"
```

---

### Task 5: turn orchestration (`repo/chat.py`)

**Files:**
- Create: `ghostbrain/api/repo/chat.py`
- Test: `tests/test_chat_repo.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_chat_repo.py`:

```python
"""send_message orchestration: persistence + resume retry, with a fake agent."""
from __future__ import annotations

from pathlib import Path

import pytest

from ghostbrain.api.repo import chat as repo_chat
from ghostbrain.api.repo import chat_store
from ghostbrain.llm.agent import ResumeFailed


@pytest.fixture
def chats(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "chats"
    monkeypatch.setenv("GHOSTBRAIN_CHATS_DIR", str(d))
    return d


def happy_turn(prompt, *, session_id=None, **kw):
    yield {"type": "session", "session_id": "sess-1"}
    yield {"type": "delta", "text": "hel"}
    yield {"type": "tool", "name": "search", "summary": "searched vault: x"}
    yield {"type": "delta", "text": "lo"}
    yield {"type": "done", "text": "hello", "session_id": "sess-1"}


def test_send_message_streams_and_persists(chats, monkeypatch):
    monkeypatch.setattr(repo_chat.agent, "run_chat_turn", happy_turn)
    conv = chat_store.create()
    events = list(repo_chat.send_message(conv["id"], "hi there"))
    assert [e["type"] for e in events] == ["session", "delta", "tool", "delta", "done"]
    saved = chat_store.get(conv["id"])
    assert saved["claude_session_id"] == "sess-1"
    assert saved["title"] == "hi there"
    assert saved["messages"][0] == {"role": "user", "text": "hi there"}
    a = saved["messages"][1]
    assert a["role"] == "assistant"
    assert a["text"] == "hello"
    assert a["tools"] == [{"name": "search", "summary": "searched vault: x"}]


def test_missing_conversation_yields_error(chats):
    events = list(repo_chat.send_message("nope", "hi"))
    assert events == [{"type": "error", "message": "conversation not found"}]


def test_error_turn_persists_partial_as_interrupted(chats, monkeypatch):
    def bad_turn(prompt, *, session_id=None, **kw):
        yield {"type": "delta", "text": "par"}
        yield {"type": "error", "message": "boom", "interrupted": True}

    monkeypatch.setattr(repo_chat.agent, "run_chat_turn", bad_turn)
    conv = chat_store.create()
    events = list(repo_chat.send_message(conv["id"], "q"))
    assert events[-1]["type"] == "error"
    saved = chat_store.get(conv["id"])
    assert saved["messages"][1]["text"] == "par"
    assert saved["messages"][1]["interrupted"] is True


def test_error_turn_with_no_partial_skips_assistant_message(chats, monkeypatch):
    def bad_turn(prompt, *, session_id=None, **kw):
        yield {"type": "error", "message": "boom"}

    monkeypatch.setattr(repo_chat.agent, "run_chat_turn", bad_turn)
    conv = chat_store.create()
    list(repo_chat.send_message(conv["id"], "q"))
    saved = chat_store.get(conv["id"])
    assert len(saved["messages"]) == 1  # just the user message


def test_resume_failure_retries_without_session_with_history(chats, monkeypatch):
    calls = []

    def turn(prompt, *, session_id=None, **kw):
        calls.append({"prompt": prompt, "session_id": session_id})
        if session_id is not None:
            raise ResumeFailed("stale")
            yield  # pragma: no cover — makes this a generator
        yield {"type": "session", "session_id": "sess-2"}
        yield {"type": "done", "text": "recovered", "session_id": "sess-2"}

    monkeypatch.setattr(repo_chat.agent, "run_chat_turn", turn)
    conv = chat_store.create()
    chat_store.append_user_message(conv, "first q")
    chat_store.append_assistant_message(conv, "first a", [])
    chat_store.set_session_id(conv, "stale-sess")

    events = list(repo_chat.send_message(conv["id"], "second q"))
    assert events[-1]["type"] == "done"
    assert len(calls) == 2
    assert calls[0]["session_id"] == "stale-sess"
    assert calls[1]["session_id"] is None
    # the retry prompt carries recent history
    assert "first q" in calls[1]["prompt"]
    assert "first a" in calls[1]["prompt"]
    assert "second q" in calls[1]["prompt"]
    saved = chat_store.get(conv["id"])
    assert saved["claude_session_id"] == "sess-2"
    assert saved["messages"][-1]["text"] == "recovered"
```

Note the `raise` + unreachable `yield` in `turn`: a generator that raises on first `next()`. `run_chat_turn` raises ResumeFailed before yielding anything in the real stale-resume case, so this models it accurately.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_chat_repo.py -v`
Expected: FAIL — `ImportError: cannot import name 'chat'`

- [ ] **Step 3: Implement**

Create `ghostbrain/api/repo/chat.py`:

```python
"""Chat turn orchestration: stream agent events, persist as a side effect.

Generator-of-dicts all the way down: the route turns these into SSE lines.
If a stale ``--resume`` is rejected we retry ONCE without a session, stuffing
the recent transcript into the prompt so conversational context survives.
"""
from __future__ import annotations

import logging
from typing import Iterator

from ghostbrain.api.repo import chat_store
from ghostbrain.llm import agent

log = logging.getLogger("ghostbrain.chat")

HISTORY_FALLBACK_MESSAGES = 6


def send_message(conv_id: str, text: str) -> Iterator[dict]:
    conv = chat_store.get(conv_id)
    if conv is None:
        yield {"type": "error", "message": "conversation not found"}
        return
    chat_store.append_user_message(conv, text)
    session_id = conv.get("claude_session_id")
    try:
        yield from _stream_turn(conv, text, session_id)
    except agent.ResumeFailed as e:
        log.warning("resume failed for %s (%s); retrying without session", conv_id, e)
        yield from _stream_turn(conv, _with_history(conv, text), None)


def _with_history(conv: dict, text: str) -> str:
    """Fallback prompt for a fresh session: recent transcript + the new turn.

    ``messages[-1]`` is the just-appended user message — exclude it, then take
    the HISTORY_FALLBACK_MESSAGES before it.
    """
    recent = conv["messages"][-(HISTORY_FALLBACK_MESSAGES + 1) : -1]
    lines = [f"{m['role']}: {m['text']}" for m in recent]
    return (
        "Earlier in this conversation (your session was reset — this is the "
        "transcript):\n\n" + "\n\n".join(lines) + f"\n\nuser: {text}"
    )


def _stream_turn(conv: dict, prompt: str, session_id: str | None) -> Iterator[dict]:
    parts: list[str] = []
    tools: list[dict] = []
    for event in agent.run_chat_turn(prompt, session_id=session_id):
        if event["type"] == "session":
            chat_store.set_session_id(conv, event["session_id"])
        elif event["type"] == "delta":
            parts.append(event["text"])
        elif event["type"] == "tool":
            tools.append({"name": event["name"], "summary": event["summary"]})
        elif event["type"] == "done":
            # Prefer the result's full text; fall back to assembled deltas.
            chat_store.append_assistant_message(
                conv, event["text"] or "".join(parts), tools
            )
        elif event["type"] == "error":
            partial = "".join(parts)
            if partial:
                chat_store.append_assistant_message(
                    conv, partial, tools, interrupted=True
                )
        yield event
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_chat_repo.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/repo/chat.py tests/test_chat_repo.py
git commit -m "feat(chat): turn orchestration — persist messages, retry stale resume"
```

---

### Task 6: chat API routes (CRUD + SSE)

**Files:**
- Create: `ghostbrain/api/models/chat.py`, `ghostbrain/api/routes/chat.py`
- Modify: `ghostbrain/api/main.py`, `ghostbrain/api/tests/conftest.py`
- Test: `ghostbrain/api/tests/test_chat.py`

- [ ] **Step 1: Add a chats fixture to the API conftest**

Append to `ghostbrain/api/tests/conftest.py`:

```python
@pytest.fixture
def tmp_chats_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point GHOSTBRAIN_CHATS_DIR at a clean temp dir."""
    chats = tmp_path / "chats"
    monkeypatch.setenv("GHOSTBRAIN_CHATS_DIR", str(chats))
    return chats
```

- [ ] **Step 2: Write the failing tests**

Create `ghostbrain/api/tests/test_chat.py`:

```python
"""Chat routes: CRUD + SSE message streaming (agent faked)."""
from __future__ import annotations

import json

import pytest


def sse_events(body: str) -> list[dict]:
    return [
        json.loads(line[len("data: ") :])
        for line in body.splitlines()
        if line.startswith("data: ")
    ]


def test_crud_roundtrip(client, tmp_chats_dir, auth_headers):
    created = client.post("/v1/chat", headers=auth_headers).json()
    assert created["title"] == "new chat"

    listed = client.get("/v1/chat", headers=auth_headers).json()
    assert [c["id"] for c in listed] == [created["id"]]

    got = client.get(f"/v1/chat/{created['id']}", headers=auth_headers).json()
    assert got["messages"] == []

    renamed = client.patch(
        f"/v1/chat/{created['id']}", json={"title": "my chat"}, headers=auth_headers
    ).json()
    assert renamed["title"] == "my chat"

    assert (
        client.delete(f"/v1/chat/{created['id']}", headers=auth_headers).status_code
        == 200
    )
    assert client.get(f"/v1/chat/{created['id']}", headers=auth_headers).status_code == 404


def test_missing_conversation_404s(client, tmp_chats_dir, auth_headers):
    assert client.get("/v1/chat/nope", headers=auth_headers).status_code == 404
    assert (
        client.patch("/v1/chat/nope", json={"title": "x"}, headers=auth_headers).status_code
        == 404
    )
    assert client.delete("/v1/chat/nope", headers=auth_headers).status_code == 404
    assert (
        client.post(
            "/v1/chat/nope/messages", json={"text": "hi"}, headers=auth_headers
        ).status_code
        == 404
    )


def test_send_message_streams_sse(client, tmp_chats_dir, auth_headers, monkeypatch):
    def fake_turn(prompt, *, session_id=None, **kw):
        yield {"type": "session", "session_id": "s-1"}
        yield {"type": "delta", "text": "hel"}
        yield {"type": "delta", "text": "lo"}
        yield {"type": "done", "text": "hello", "session_id": "s-1"}

    monkeypatch.setattr("ghostbrain.api.repo.chat.agent.run_chat_turn", fake_turn)

    conv = client.post("/v1/chat", headers=auth_headers).json()
    resp = client.post(
        f"/v1/chat/{conv['id']}/messages", json={"text": "say hello"}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = sse_events(resp.text)
    assert [e["type"] for e in events] == ["session", "delta", "delta", "done"]

    # persisted side effects
    got = client.get(f"/v1/chat/{conv['id']}", headers=auth_headers).json()
    assert got["claude_session_id"] == "s-1"
    assert [m["role"] for m in got["messages"]] == ["user", "assistant"]
    assert got["messages"][1]["text"] == "hello"


def test_send_message_validates_text(client, tmp_chats_dir, auth_headers):
    conv = client.post("/v1/chat", headers=auth_headers).json()
    resp = client.post(
        f"/v1/chat/{conv['id']}/messages", json={"text": ""}, headers=auth_headers
    )
    assert resp.status_code == 422
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest ghostbrain/api/tests/test_chat.py -v`
Expected: FAIL — 404s everywhere (router not mounted / module missing)

- [ ] **Step 4: Implement**

Create `ghostbrain/api/models/chat.py`:

```python
"""Chat conversation schemas."""
from typing import Literal

from pydantic import BaseModel, Field


class ChatToolUse(BaseModel):
    name: str
    summary: str


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    text: str
    tools: list[ChatToolUse] = []
    interrupted: bool = False


class ConversationSummary(BaseModel):
    id: str
    title: str
    created_at: float
    updated_at: float
    message_count: int


class Conversation(BaseModel):
    id: str
    title: str
    created_at: float
    updated_at: float
    claude_session_id: str | None = None
    messages: list[ChatMessage] = []


class ChatMessageRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)


class RenameRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
```

Create `ghostbrain/api/routes/chat.py`:

```python
"""Chat API: conversation CRUD + streaming agentic messages over SSE."""
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ghostbrain.api.models.chat import (
    ChatMessageRequest,
    Conversation,
    ConversationSummary,
    RenameRequest,
)
from ghostbrain.api.repo import chat as repo_chat
from ghostbrain.api.repo import chat_store

router = APIRouter(prefix="/v1/chat", tags=["chat"])


@router.get("", response_model=list[ConversationSummary])
def list_conversations() -> list[dict]:
    return chat_store.list_all()


@router.post("", response_model=Conversation)
def create_conversation() -> dict:
    return chat_store.create()


@router.get("/{conv_id}", response_model=Conversation)
def get_conversation(conv_id: str) -> dict:
    conv = chat_store.get(conv_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return conv


@router.patch("/{conv_id}", response_model=Conversation)
def rename_conversation(conv_id: str, payload: RenameRequest) -> dict:
    conv = chat_store.rename(conv_id, payload.title)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return conv


@router.delete("/{conv_id}")
def delete_conversation(conv_id: str) -> dict:
    if not chat_store.delete(conv_id):
        raise HTTPException(status_code=404, detail="conversation not found")
    return {"ok": True}


@router.post("/{conv_id}/messages")
def send_message(conv_id: str, payload: ChatMessageRequest) -> StreamingResponse:
    if chat_store.get(conv_id) is None:
        raise HTTPException(status_code=404, detail="conversation not found")

    def gen():
        # Sync generator: starlette runs it in a threadpool and closes it
        # (GeneratorExit) when the client disconnects — that propagates into
        # run_chat_turn's finally, killing the claude subprocess.
        for event in repo_chat.send_message(conv_id, payload.text):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

Modify `ghostbrain/api/main.py` — add the import and mount:

```python
from ghostbrain.api.routes import chat as chat_routes
```

and inside `create_app`, after the answer router line:

```python
    app.include_router(chat_routes.router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest ghostbrain/api/tests/test_chat.py -v`
Expected: 4 passed

- [ ] **Step 6: Run the whole backend suite**

Run: `.venv/bin/pytest tests ghostbrain/api/tests -q`
Expected: all pass, no regressions

- [ ] **Step 7: Commit**

```bash
git add ghostbrain/api/models/chat.py ghostbrain/api/routes/chat.py ghostbrain/api/main.py ghostbrain/api/tests/conftest.py ghostbrain/api/tests/test_chat.py
git commit -m "feat(chat): /v1/chat CRUD + SSE message route"
```

---

### Task 7: desktop — PATCH/DELETE plumbing

**Files:**
- Modify: `desktop/src/main/api-forwarder.ts`, `desktop/src/main/index.ts:225-240`, `desktop/src/shared/types.ts`, `desktop/src/renderer/lib/api/client.ts`

No new test file — this is type-widening plumbing covered by the existing suite + the route tests later. All desktop commands run from `desktop/`.

- [ ] **Step 1: Widen the forwarder method type**

In `desktop/src/main/api-forwarder.ts` change the signature:

```ts
export async function forward<T = unknown>(
  sidecar: Sidecar,
  method: 'GET' | 'POST' | 'PATCH' | 'DELETE',
  path: string,
  body?: unknown,
): Promise<ApiResult<T>> {
```

- [ ] **Step 2: Widen the IPC allowlist**

In `desktop/src/main/index.ts`, in the `gb:api:request` handler, replace:

```ts
    const m = method.toUpperCase();
    if (m !== 'GET' && m !== 'POST') {
      return { ok: false, error: 'Method not allowed' };
    }
```

with:

```ts
    const m = method.toUpperCase();
    if (m !== 'GET' && m !== 'POST' && m !== 'PATCH' && m !== 'DELETE') {
      return { ok: false, error: 'Method not allowed' };
    }
```

(The `forward(sidecar, m, path, body)` call now typechecks against the widened union.)

- [ ] **Step 3: Widen the bridge type**

In `desktop/src/shared/types.ts`, in `GbBridge.api`:

```ts
  api: {
    request<T = unknown>(
      method: 'GET' | 'POST' | 'PATCH' | 'DELETE',
      path: string,
      body?: unknown,
    ): Promise<
      | { ok: true; data: T }
      | { ok: false; error: string; status?: number }
    >;
  };
```

- [ ] **Step 4: Add renderer helpers**

Append to `desktop/src/renderer/lib/api/client.ts`:

```ts
export async function patch<T>(path: string, body?: unknown): Promise<T> {
  const result = await window.gb.api.request<T>('PATCH', path, body);
  if (!result.ok) throw new Error(result.error);
  return result.data;
}

export async function del<T>(path: string): Promise<T> {
  const result = await window.gb.api.request<T>('DELETE', path);
  if (!result.ok) throw new Error(result.error);
  return result.data;
}
```

- [ ] **Step 5: Verify**

Run: `cd desktop && npm test -- --run`
Expected: existing suite passes (type errors would fail the vitest transform)

- [ ] **Step 6: Commit**

```bash
git add src/main/api-forwarder.ts src/main/index.ts src/shared/types.ts src/renderer/lib/api/client.ts
git commit -m "feat(chat): PATCH/DELETE support through the api bridge"
```

---

### Task 8: desktop main — chat SSE relay

**Files:**
- Create: `desktop/src/main/chat-stream.ts`
- Modify: `desktop/src/main/index.ts`, `desktop/src/preload/index.ts`, `desktop/src/shared/types.ts`, `desktop/src/shared/api-types.ts`
- Test: `desktop/src/main/__tests__/chat-stream.test.ts`

- [ ] **Step 1: Add shared chat types**

Append to `desktop/src/shared/api-types.ts`:

```ts
// ── Chat ──────────────────────────────────────────────────────────────────

export interface ChatToolUse {
  name: string;
  summary: string;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  text: string;
  tools?: ChatToolUse[];
  interrupted?: boolean;
}

export interface ConversationSummary {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
  message_count: number;
}

export interface Conversation {
  id: string;
  title: string;
  created_at: number;
  updated_at: number;
  claude_session_id: string | null;
  messages: ChatMessage[];
}

/** Mirrors the event vocabulary of ghostbrain/llm/agent.py. */
export type ChatStreamEvent =
  | { type: 'session'; session_id: string }
  | { type: 'delta'; text: string }
  | { type: 'tool'; name: string; summary: string }
  | { type: 'done'; text: string; session_id?: string }
  | { type: 'error'; message: string; interrupted?: boolean };
```

- [ ] **Step 2: Write the failing SSE-parser test**

Create `desktop/src/main/__tests__/chat-stream.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { createSseParser } from '../chat-stream';

describe('createSseParser', () => {
  it('extracts data payloads from complete blocks', () => {
    const parse = createSseParser();
    expect(parse('data: {"type":"delta"}\n\n')).toEqual(['{"type":"delta"}']);
  });

  it('buffers partial blocks across chunks', () => {
    const parse = createSseParser();
    expect(parse('data: {"a"')).toEqual([]);
    expect(parse(':1}\n')).toEqual([]);
    expect(parse('\ndata: {"b":2}\n\n')).toEqual(['{"a":1}', '{"b":2}']);
  });

  it('handles multiple events in one chunk', () => {
    const parse = createSseParser();
    expect(parse('data: 1\n\ndata: 2\n\n')).toEqual(['1', '2']);
  });

  it('ignores non-data lines and comments', () => {
    const parse = createSseParser();
    expect(parse(': keepalive\nevent: x\ndata: 3\n\n')).toEqual(['3']);
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd desktop && npm test -- --run src/main/__tests__/chat-stream.test.ts`
Expected: FAIL — cannot resolve `../chat-stream`

- [ ] **Step 4: Implement the relay**

Create `desktop/src/main/chat-stream.ts`:

```ts
import type { Sidecar } from './sidecar';
import type { ChatStreamEvent } from '../shared/api-types';

/** Incremental SSE parser: feed text chunks, get back complete `data:`
 *  payloads. Stateful per stream — create one per request. */
export function createSseParser(): (chunk: string) => string[] {
  let buffer = '';
  return (chunk: string) => {
    buffer += chunk;
    const out: string[] = [];
    let idx: number;
    while ((idx = buffer.indexOf('\n\n')) !== -1) {
      const block = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      for (const line of block.split('\n')) {
        if (line.startsWith('data: ')) out.push(line.slice(6));
        else if (line.startsWith('data:')) out.push(line.slice(5));
      }
    }
    return out;
  };
}

// One in-flight stream per conversation; sending again aborts the previous.
const active = new Map<string, AbortController>();

export async function startChatStream(
  sidecar: Sidecar,
  convId: string,
  text: string,
  send: (event: ChatStreamEvent) => void,
): Promise<{ ok: true } | { ok: false; error: string }> {
  const info = sidecar.getInfo();
  if (!info) return { ok: false, error: 'Sidecar not ready' };
  active.get(convId)?.abort();
  const ac = new AbortController();
  active.set(convId, ac);
  try {
    const res = await fetch(
      `http://127.0.0.1:${info.port}/v1/chat/${encodeURIComponent(convId)}/messages`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${info.token}`,
        },
        body: JSON.stringify({ text }),
        // No timeout: agent turns are long-lived. The sidecar enforces its
        // own 5-minute turn ceiling; stop() aborts from our side.
        signal: ac.signal,
      },
    );
    if (!res.ok || !res.body) {
      return { ok: false, error: `HTTP ${res.status}` };
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    const parse = createSseParser();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      for (const payload of parse(decoder.decode(value, { stream: true }))) {
        try {
          send(JSON.parse(payload) as ChatStreamEvent);
        } catch {
          // skip malformed event; the stream itself is still healthy
        }
      }
    }
    return { ok: true };
  } catch (err) {
    if (ac.signal.aborted) return { ok: true }; // user pressed stop
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  } finally {
    if (active.get(convId) === ac) active.delete(convId);
  }
}

export function stopChatStream(convId: string): void {
  active.get(convId)?.abort();
  active.delete(convId);
}
```

- [ ] **Step 5: Register the IPC handlers**

In `desktop/src/main/index.ts`, import at the top with the other local imports:

```ts
import { startChatStream, stopChatStream } from './chat-stream';
```

and after the `gb:api:request` handler add:

```ts
ipcMain.handle('gb:chat:send', async (e, convId: unknown, text: unknown) => {
  if (typeof convId !== 'string' || typeof text !== 'string') {
    return { ok: false, error: 'Invalid request shape' };
  }
  const wc = e.sender;
  return startChatStream(sidecar, convId, text, (event) => {
    if (!wc.isDestroyed()) wc.send('gb:chat:event', { convId, event });
  });
});

ipcMain.handle('gb:chat:stop', (_e, convId: unknown) => {
  if (typeof convId !== 'string') {
    return { ok: false, error: 'Invalid request shape' };
  }
  stopChatStream(convId);
  return { ok: true };
});
```

- [ ] **Step 6: Expose the bridge**

In `desktop/src/shared/types.ts`, add to `GbBridge` (after `sidecar`):

```ts
  chat: {
    send(
      convId: string,
      text: string,
    ): Promise<{ ok: true } | { ok: false; error: string }>;
    stop(convId: string): Promise<{ ok: true } | { ok: false; error: string }>;
  };
```

add the listener overload next to the other `on(...)` overloads:

```ts
  on(
    channel: 'chat:event',
    listener: (payload: { convId: string; event: ChatStreamEvent }) => void,
  ): () => void;
```

and add the import at the top of the file:

```ts
import type { ChatStreamEvent } from './api-types';
```

In `desktop/src/preload/index.ts`, add to the bridge object (after `sidecar`):

```ts
  chat: {
    send: (convId, text) => ipcRenderer.invoke('gb:chat:send', convId, text),
    stop: (convId) => ipcRenderer.invoke('gb:chat:stop', convId),
  },
```

- [ ] **Step 7: Run tests**

Run: `cd desktop && npm test -- --run`
Expected: chat-stream tests pass, suite green

- [ ] **Step 8: Commit**

```bash
git add src/main/chat-stream.ts src/main/__tests__/chat-stream.test.ts src/main/index.ts src/preload/index.ts src/shared/types.ts src/shared/api-types.ts
git commit -m "feat(chat): SSE relay main↔renderer with per-conversation abort"
```

---

### Task 9: renderer chat store

**Files:**
- Create: `desktop/src/renderer/stores/chat.ts`
- Test: `desktop/src/renderer/__tests__/chat-store.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `desktop/src/renderer/__tests__/chat-store.test.ts`:

```ts
import { beforeEach, describe, expect, it } from 'vitest';
import { useChat } from '../stores/chat';

describe('chat store', () => {
  beforeEach(() => {
    useChat.setState({ activeId: null, streams: {}, errors: {} });
  });

  it('beginStream snapshots the pending user text and clears prior error', () => {
    useChat.setState({ errors: { c1: 'old boom' } });
    useChat.getState().beginStream('c1', 'my question');
    const s = useChat.getState();
    expect(s.streams.c1).toEqual({ userText: 'my question', text: '', tools: [] });
    expect(s.errors.c1).toBeUndefined();
  });

  it('delta events accumulate text', () => {
    useChat.getState().beginStream('c1', 'q');
    useChat.getState().applyEvent('c1', { type: 'delta', text: 'hel' });
    useChat.getState().applyEvent('c1', { type: 'delta', text: 'lo' });
    expect(useChat.getState().streams.c1?.text).toBe('hello');
  });

  it('tool events append chips', () => {
    useChat.getState().beginStream('c1', 'q');
    useChat.getState().applyEvent('c1', {
      type: 'tool',
      name: 'search',
      summary: 'searched vault: x',
    });
    expect(useChat.getState().streams.c1?.tools).toEqual([
      { name: 'search', summary: 'searched vault: x' },
    ]);
  });

  it('done clears the stream', () => {
    useChat.getState().beginStream('c1', 'q');
    useChat.getState().applyEvent('c1', { type: 'done', text: 'hello' });
    expect(useChat.getState().streams.c1).toBeUndefined();
  });

  it('error clears the stream and records the message', () => {
    useChat.getState().beginStream('c1', 'q');
    useChat.getState().applyEvent('c1', { type: 'error', message: 'boom' });
    expect(useChat.getState().streams.c1).toBeUndefined();
    expect(useChat.getState().errors.c1).toBe('boom');
  });

  it('events for conversations without a stream are ignored', () => {
    useChat.getState().applyEvent('ghost', { type: 'delta', text: 'x' });
    expect(useChat.getState().streams.ghost).toBeUndefined();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd desktop && npm test -- --run src/renderer/__tests__/chat-store.test.ts`
Expected: FAIL — cannot resolve `../stores/chat`

- [ ] **Step 3: Implement**

Create `desktop/src/renderer/stores/chat.ts`:

```ts
import { create } from 'zustand';
import type { ChatStreamEvent, ChatToolUse } from '../../shared/api-types';

export interface StreamState {
  /** The user message this turn answers — rendered optimistically until the
   *  refetched conversation includes it. */
  userText: string;
  text: string;
  tools: ChatToolUse[];
}

interface ChatState {
  activeId: string | null;
  /** In-flight turn per conversation. Presence = streaming. */
  streams: Record<string, StreamState>;
  /** Last turn error per conversation, shown inline in the thread. */
  errors: Record<string, string>;
  setActive: (id: string | null) => void;
  beginStream: (id: string, userText: string) => void;
  applyEvent: (id: string, event: ChatStreamEvent) => void;
}

export const useChat = create<ChatState>((set) => ({
  activeId: null,
  streams: {},
  errors: {},
  setActive: (id) => set({ activeId: id }),
  beginStream: (id, userText) =>
    set((s) => {
      const errors = { ...s.errors };
      delete errors[id];
      return {
        streams: { ...s.streams, [id]: { userText, text: '', tools: [] } },
        errors,
      };
    }),
  applyEvent: (id, event) =>
    set((s) => {
      const cur = s.streams[id];
      if (!cur) return {};
      switch (event.type) {
        case 'delta':
          return {
            streams: { ...s.streams, [id]: { ...cur, text: cur.text + event.text } },
          };
        case 'tool':
          return {
            streams: {
              ...s.streams,
              [id]: {
                ...cur,
                tools: [...cur.tools, { name: event.name, summary: event.summary }],
              },
            },
          };
        case 'done': {
          const streams = { ...s.streams };
          delete streams[id];
          return { streams };
        }
        case 'error': {
          const streams = { ...s.streams };
          delete streams[id];
          return { streams, errors: { ...s.errors, [id]: event.message } };
        }
        default:
          return {};
      }
    }),
}));
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd desktop && npm test -- --run src/renderer/__tests__/chat-store.test.ts`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/renderer/stores/chat.ts src/renderer/__tests__/chat-store.test.ts
git commit -m "feat(chat): renderer streaming state store"
```

---

### Task 10: conversation hooks

**Files:**
- Modify: `desktop/src/renderer/lib/api/hooks.ts`

- [ ] **Step 1: Add hooks**

In `desktop/src/renderer/lib/api/hooks.ts`:

1. Extend the type import to include the chat types, and the client import:

```ts
import type {
  // ...existing names...
  Conversation,
  ConversationSummary,
} from '../../../shared/api-types';
import { del, get, patch, post } from './client';
```

2. Append at the end of the file:

```ts
// ── Chat ──────────────────────────────────────────────────────────────────

export function useConversations() {
  return useQuery({
    queryKey: ['chat'],
    queryFn: () => get<ConversationSummary[]>('/v1/chat'),
    staleTime: 10_000,
  });
}

export function useConversation(id: string | null) {
  return useQuery({
    queryKey: ['chat', id],
    queryFn: () => get<Conversation>(`/v1/chat/${encodeURIComponent(id!)}`),
    enabled: id !== null,
    // Refetched explicitly when a turn completes — no background polling.
    staleTime: Infinity,
  });
}

export function useCreateConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => post<Conversation>('/v1/chat'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['chat'] }),
  });
}

export function useRenameConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; title: string }) =>
      patch<Conversation>(`/v1/chat/${encodeURIComponent(vars.id)}`, {
        title: vars.title,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['chat'] }),
  });
}

export function useDeleteConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => del<{ ok: boolean }>(`/v1/chat/${encodeURIComponent(id)}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['chat'] }),
  });
}
```

- [ ] **Step 2: Verify**

Run: `cd desktop && npm test -- --run`
Expected: suite green

- [ ] **Step 3: Commit**

```bash
git add src/renderer/lib/api/hooks.ts
git commit -m "feat(chat): conversation query/mutation hooks"
```

---

### Task 11: Chat screen UI + navigation

**Files:**
- Create: `desktop/src/renderer/screens/chat.tsx`
- Modify: `desktop/src/renderer/stores/navigation.ts`, `desktop/src/renderer/components/Sidebar.tsx`, `desktop/src/renderer/App.tsx`
- Test: `desktop/src/renderer/__tests__/ChatScreen.test.tsx`

Follow the app's visual language: design tokens (`bg-paper`, `bg-vellum`, `border-hairline`, `text-ink-0/1/2/3`, `text-neon`, `rounded-*`, `text-12/14`, `font-mono`, `Eyebrow`, `Btn`, `Lucide`, `TopBar`) — copy patterns from `screens/today.tsx` and `components/AskPanel.tsx`.

- [ ] **Step 1: Wire navigation**

`desktop/src/renderer/stores/navigation.ts` — add `'chat'` to the union:

```ts
export type ScreenId =
  | 'today'
  | 'chat'
  | 'connectors'
  | 'meetings'
  | 'capture'
  | 'vault'
  | 'daily'
  | 'setup'
  | 'settings';
```

`desktop/src/renderer/components/Sidebar.tsx` — add to `NAV_ITEMS` right after `today`:

```ts
  { id: 'chat', icon: 'message-circle', label: 'chat' },
```

(If `Lucide.tsx` keeps an explicit icon map and lacks `message-circle`, register it there the same way the existing icons are registered.)

`desktop/src/renderer/App.tsx` — add the import and render branch alongside the others:

```ts
import { ChatScreen } from './screens/chat';
```

```tsx
          {active === 'chat' && <ChatScreen />}
```

- [ ] **Step 2: Write the failing screen test**

Create `desktop/src/renderer/__tests__/ChatScreen.test.tsx` (mock the API client module like the existing screen tests mock data fetching; check `App.test.tsx` for the established `QueryClientProvider` wrapper pattern and reuse it):

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ChatScreen } from '../screens/chat';
import { useChat } from '../stores/chat';
import type { Conversation, ConversationSummary } from '../../shared/api-types';

const conversations: ConversationSummary[] = [
  { id: 'c1', title: 'standup decisions', created_at: 1, updated_at: 2, message_count: 2 },
];
const conversation: Conversation = {
  id: 'c1',
  title: 'standup decisions',
  created_at: 1,
  updated_at: 2,
  claude_session_id: 's-1',
  messages: [
    { role: 'user', text: 'what did we decide?' },
    {
      role: 'assistant',
      text: 'You decided to ship it. See [[10-daily/2026-06-09]].',
      tools: [{ name: 'search', summary: 'searched vault: decisions' }],
    },
  ],
};

vi.mock('../lib/api/client', () => ({
  get: vi.fn((path: string) => {
    if (path === '/v1/chat') return Promise.resolve(conversations);
    return Promise.resolve(conversation);
  }),
  post: vi.fn(() => Promise.resolve(conversation)),
  patch: vi.fn(() => Promise.resolve(conversation)),
  del: vi.fn(() => Promise.resolve({ ok: true })),
}));

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ChatScreen />
    </QueryClientProvider>,
  );
}

describe('ChatScreen', () => {
  beforeEach(() => {
    window.gb = {
      ...(window.gb ?? {}),
      chat: { send: vi.fn(async () => ({ ok: true })), stop: vi.fn(async () => ({ ok: true })) },
      on: vi.fn(() => () => {}),
    } as never;
    useChat.setState({ activeId: 'c1', streams: {}, errors: {} });
  });

  it('renders the conversation list and thread', async () => {
    renderScreen();
    expect(await screen.findAllByText('standup decisions')).toBeTruthy();
    expect(await screen.findByText('what did we decide?')).toBeTruthy();
    expect(await screen.findByText(/You decided to ship it/)).toBeTruthy();
    expect(screen.getByText('searched vault: decisions')).toBeTruthy();
  });

  it('shows streaming text, tool chips, and a stop button mid-turn', async () => {
    useChat.setState({
      activeId: 'c1',
      streams: {
        c1: {
          userText: 'and then?',
          text: 'Then you',
          tools: [{ name: 'search', summary: 'searched vault: then' }],
        },
      },
      errors: {},
    });
    renderScreen();
    expect(await screen.findByText('and then?')).toBeTruthy();
    expect(await screen.findByText(/Then you/)).toBeTruthy();
    expect(screen.getByText('searched vault: then')).toBeTruthy();
    expect(screen.getByRole('button', { name: /stop/i })).toBeTruthy();
  });

  it('shows turn errors inline', async () => {
    useChat.setState({ activeId: 'c1', streams: {}, errors: { c1: 'boom' } });
    renderScreen();
    expect(await screen.findByText(/boom/)).toBeTruthy();
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd desktop && npm test -- --run src/renderer/__tests__/ChatScreen.test.tsx`
Expected: FAIL — cannot resolve `../screens/chat`

- [ ] **Step 4: Implement the screen**

Create `desktop/src/renderer/screens/chat.tsx`:

```tsx
import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { Btn } from '../components/Btn';
import { Eyebrow } from '../components/Eyebrow';
import { Lucide } from '../components/Lucide';
import { MarkdownBody } from '../components/MarkdownBody';
import { TopBar } from '../components/TopBar';
import {
  useConversation,
  useConversations,
  useCreateConversation,
  useDeleteConversation,
  useRenameConversation,
} from '../lib/api/hooks';
import { useChat } from '../stores/chat';
import type {
  ChatMessage,
  ChatToolUse,
  ConversationSummary,
} from '../../shared/api-types';

export function ChatScreen() {
  const qc = useQueryClient();
  const { activeId, setActive: setActiveConv, streams, errors, beginStream, applyEvent } =
    useChat();
  const conversations = useConversations();
  const conversation = useConversation(activeId);
  const createConv = useCreateConversation();

  // Relay stream events from the main process into the store. Mounted once
  // per screen visit; turns persist sidecar-side, so events missed while on
  // another screen are recovered by the refetch on 'done' / remount.
  useEffect(() => {
    return window.gb.on('chat:event', ({ convId, event }) => {
      applyEvent(convId, event);
      if (event.type === 'done' || event.type === 'error') {
        qc.invalidateQueries({ queryKey: ['chat'] });
        qc.invalidateQueries({ queryKey: ['chat', convId] });
      }
    });
  }, [applyEvent, qc]);

  // Auto-select the most recent conversation; create one for first-time use.
  useEffect(() => {
    if (activeId !== null || !conversations.data) return;
    if (conversations.data.length > 0) {
      setActiveConv(conversations.data[0].id);
    }
  }, [activeId, conversations.data, setActiveConv]);

  const newChat = () =>
    createConv.mutate(undefined, { onSuccess: (conv) => setActiveConv(conv.id) });

  const sendMessage = (text: string) => {
    if (!activeId) return;
    beginStream(activeId, text);
    void window.gb.chat.send(activeId, text).then((res) => {
      if (!res.ok) applyEvent(activeId, { type: 'error', message: res.error });
    });
  };

  const stream = activeId ? streams[activeId] : undefined;
  const error = activeId ? errors[activeId] : undefined;

  return (
    <div className="flex flex-1 overflow-hidden bg-paper">
      <ConversationList
        items={conversations.data ?? []}
        activeId={activeId}
        onSelect={setActiveConv}
        onNew={newChat}
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar title="chat" subtitle={conversation.data?.title ?? 'with poltergeist'} />
        {activeId === null ? (
          <EmptyState onNew={newChat} />
        ) : (
          <Thread
            messages={conversation.data?.messages ?? []}
            stream={stream}
            error={error}
            onStop={() => void window.gb.chat.stop(activeId)}
          />
        )}
        <Composer
          disabled={activeId === null || stream !== undefined}
          onSend={sendMessage}
        />
      </div>
    </div>
  );
}

function ConversationList({
  items,
  activeId,
  onSelect,
  onNew,
}: {
  items: ConversationSummary[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
}) {
  return (
    <aside className="flex w-[240px] flex-shrink-0 flex-col border-r border-hairline bg-vellum">
      <div className="flex items-center justify-between px-4 pb-2 pt-4">
        <Eyebrow>conversations</Eyebrow>
        <Btn
          variant="ghost"
          size="sm"
          icon={<Lucide name="plus" size={14} />}
          onClick={onNew}
          aria-label="new chat"
        />
      </div>
      <div className="flex-1 overflow-y-auto px-2 pb-4">
        {items.map((c) => (
          <ConversationRow
            key={c.id}
            item={c}
            active={c.id === activeId}
            onSelect={() => onSelect(c.id)}
          />
        ))}
        {items.length === 0 && (
          <div className="px-2 py-6 text-center text-12 text-ink-3">
            no conversations yet
          </div>
        )}
      </div>
    </aside>
  );
}

function ConversationRow({
  item,
  active,
  onSelect,
}: {
  item: ConversationSummary;
  active: boolean;
  onSelect: () => void;
}) {
  const rename = useRenameConversation();
  const del = useDeleteConversation();
  const setActiveConv = useChat((s) => s.setActive);
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(item.title);

  const commit = () => {
    setEditing(false);
    const trimmed = title.trim();
    if (trimmed && trimmed !== item.title) rename.mutate({ id: item.id, title: trimmed });
    else setTitle(item.title);
  };

  return (
    <div
      className={`group flex items-center gap-1 rounded-sm px-2 py-[7px] ${
        active ? 'bg-paper text-ink-0' : 'text-ink-1 hover:bg-paper/60'
      }`}
    >
      {editing ? (
        <input
          value={title}
          autoFocus
          onChange={(e) => setTitle(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commit();
            if (e.key === 'Escape') {
              setTitle(item.title);
              setEditing(false);
            }
          }}
          className="flex-1 border-none bg-transparent text-12 text-ink-0 focus:outline-none"
        />
      ) : (
        <button
          type="button"
          onClick={onSelect}
          onDoubleClick={() => setEditing(true)}
          className="min-w-0 flex-1 truncate text-left text-12"
          title={item.title}
        >
          {item.title}
        </button>
      )}
      <button
        type="button"
        aria-label="delete conversation"
        onClick={() =>
          del.mutate(item.id, {
            onSuccess: () => {
              if (active) setActiveConv(null);
            },
          })
        }
        className="hidden flex-shrink-0 text-ink-3 hover:text-oxblood group-hover:block"
      >
        <Lucide name="trash-2" size={12} />
      </button>
    </div>
  );
}

function Thread({
  messages,
  stream,
  error,
  onStop,
}: {
  messages: ChatMessage[];
  stream?: { userText: string; text: string; tools: ChatToolUse[] };
  error?: string;
  onStop: () => void;
}) {
  const bottomRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'end' });
  }, [messages.length, stream?.text, stream?.tools.length, error]);

  return (
    <div className="flex-1 overflow-y-auto px-8 py-6">
      <div className="mx-auto flex max-w-[760px] flex-col gap-5">
        {messages.length === 0 && !stream && !error && <ThreadHint />}
        {messages.map((m, i) => (
          <MessageBubble key={i} message={m} />
        ))}
        {stream && (
          <>
            <MessageBubble message={{ role: 'user', text: stream.userText }} />
            <div className="flex flex-col gap-2">
              <ToolChips tools={stream.tools} />
              {stream.text ? (
                <MarkdownBody className="text-14 leading-[1.65] text-ink-0">
                  {stream.text}
                </MarkdownBody>
              ) : (
                <div className="text-12 text-ink-3">poltergeist is thinking…</div>
              )}
              <div>
                <Btn variant="ghost" size="sm" onClick={onStop}>
                  stop
                </Btn>
              </div>
            </div>
          </>
        )}
        {error && (
          <div className="rounded-md border border-oxblood/30 bg-oxblood/10 p-3 text-12 text-oxblood">
            {error}
          </div>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  if (message.role === 'user') {
    return (
      <div className="self-end rounded-r10 border border-hairline bg-vellum px-4 py-3 text-14 text-ink-0">
        {message.text}
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-2">
      <ToolChips tools={message.tools ?? []} />
      <MarkdownBody className="text-14 leading-[1.65] text-ink-0">
        {message.text}
      </MarkdownBody>
      {message.interrupted && (
        <div className="text-10 font-mono text-ink-3">⏱ turn was interrupted</div>
      )}
    </div>
  );
}

function ToolChips({ tools }: { tools: ChatToolUse[] }) {
  if (tools.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1">
      {tools.map((t, i) => (
        <span
          key={i}
          className="inline-flex items-center gap-1 rounded-xs border border-hairline bg-fog px-2 py-[2px] font-mono text-10 text-ink-2"
        >
          <Lucide name="search" size={10} />
          {t.summary}
        </span>
      ))}
    </div>
  );
}

function ThreadHint() {
  return (
    <div className="flex flex-col items-center gap-2 py-16 text-center text-12 text-ink-3">
      <Lucide name="sparkles" size={14} color="var(--ink-3)" />
      <span className="max-w-[44ch]">
        chat with poltergeist about anything in your vault. it searches your
        notes, reads them, and answers with links you can open.
      </span>
    </div>
  );
}

function Composer({
  disabled,
  onSend,
}: {
  disabled: boolean;
  onSend: (text: string) => void;
}) {
  const [text, setText] = useState('');
  const submit = () => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText('');
  };
  return (
    <div className="border-t border-hairline bg-vellum px-8 py-4">
      <div className="mx-auto flex max-w-[760px] items-end gap-2">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder="ask poltergeist… (enter to send, shift+enter for newline)"
          rows={Math.min(5, Math.max(1, text.split('\n').length))}
          className="flex-1 resize-none rounded-md border border-hairline bg-paper px-3 py-2 text-14 text-ink-0 placeholder:text-ink-3 focus:outline-none"
        />
        <Btn
          variant="primary"
          size="md"
          icon={<Lucide name="send" size={14} color="#0E0F12" />}
          onClick={submit}
          disabled={disabled || !text.trim()}
        >
          send
        </Btn>
      </div>
    </div>
  );
}

function EmptyState({ onNew }: { onNew: () => void }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3">
      <Lucide name="message-circle" size={20} color="var(--ink-3)" />
      <div className="text-14 text-ink-1">no conversation selected</div>
      <Btn variant="primary" size="md" onClick={onNew}>
        new chat
      </Btn>
    </div>
  );
}
```

Adjust to the real props of `Btn` / `TopBar` / `Lucide` as found in the codebase (e.g. if `Btn` has no `disabled` prop, pass it through or fall back to a plain `<button>` styled like the composer's neighbors). If `Lucide` lacks `plus`, `send`, `trash-2`, or `message-circle`, register them in `Lucide.tsx` following the existing pattern.

- [ ] **Step 5: Run tests**

Run: `cd desktop && npm test -- --run`
Expected: ChatScreen tests pass; if `App.test.tsx` asserts the sidebar nav list, update its expectations to include `chat`.

- [ ] **Step 6: Commit**

```bash
git add src/renderer/screens/chat.tsx src/renderer/__tests__/ChatScreen.test.tsx src/renderer/stores/navigation.ts src/renderer/components/Sidebar.tsx src/renderer/App.tsx src/renderer/components/Lucide.tsx
git commit -m "feat(chat): chat screen — conversation list, streaming thread, composer"
```

---

### Task 12: remove AskPanel, route ⌘K to chat

**Files:**
- Delete: `desktop/src/renderer/components/AskPanel.tsx`
- Modify: `desktop/src/renderer/screens/today.tsx`, `desktop/src/renderer/lib/api/hooks.ts`

- [ ] **Step 1: Rewire today.tsx**

In `desktop/src/renderer/screens/today.tsx`:

1. Remove `import { AskPanel } from '../components/AskPanel';` and the `const [askOpen, setAskOpen] = useState(false);` line, plus the `<AskPanel open={askOpen} onClose={...} />` element.
2. The screen already has `const setActive = useNavigation((s) => s.setActive);` — replace every `setAskOpen(true)` (⌘K handler at ~line 46, the TopBar "ask…" button at ~line 83, the hero "ask the archive" button at ~line 133) with:

```ts
setActive('chat')
```

3. Update the ⌘K effect's dependency array from `[]` to `[setActive]`.
4. If `useState` is now unused in the file, remove it from the react import (check remaining usages first).

- [ ] **Step 2: Delete AskPanel and the dead hook**

```bash
cd desktop && git rm src/renderer/components/AskPanel.tsx
```

In `desktop/src/renderer/lib/api/hooks.ts`: delete the `useAsk` function and remove `AnswerResponse` from the type import (verify with `grep -rn "useAsk\|AnswerResponse" src/renderer` that no other renderer code uses them; the `/v1/answer` endpoint itself stays — the MCP `poltergeist_ask` tool calls it).

- [ ] **Step 3: Run the full desktop suite**

Run: `cd desktop && npm test -- --run`
Expected: green (fix any test that referenced AskPanel)

- [ ] **Step 4: Commit**

```bash
git add -A src/renderer
git commit -m "feat(chat): replace AskPanel with the chat screen (⌘K opens chat)"
```

---

### Task 13: full verification + manual smoke

- [ ] **Step 1: Full backend suite**

Run: `cd /Users/jannik/development/nikrich/ghost-brain && .venv/bin/pytest tests ghostbrain/api/tests -q`
Expected: all pass

- [ ] **Step 2: Full desktop suite**

Run: `cd desktop && npm test -- --run`
Expected: all pass

- [ ] **Step 3: Manual smoke (real claude, real vault)**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/desktop && npm run dev
```

In the app:
1. Sidebar shows **chat**; open it, click **new chat**.
2. Send "what have I been working on this week?" — expect tool chips ("searched vault: …") to appear within ~5s, then streaming text, then a final answer with clickable `[[note]]` links that open NoteView.
3. Send a follow-up ("and what's still open on that?") — answer must use conversation context (resume works).
4. Press **stop** mid-turn — streaming halts; check `ps aux | grep claude` shows no orphaned process.
5. Quit and relaunch the app — the conversation list and history are still there; sending another follow-up still has context.
6. Rename and delete a conversation from the list.
7. On the today screen press ⌘K — lands on the chat screen.

Record any deviation, fix, re-run the affected tests.

- [ ] **Step 4: Final commit / merge prep**

Use the superpowers:finishing-a-development-branch skill (PR to `main` of ghost-brain).

---

## Self-review (run after writing, before execution)

1. **Spec coverage:** storage ✅ (Task 1), agent runner + persona + citations ✅ (Tasks 2-4), resume retry ✅ (Task 5), API ✅ (Task 6), Electron bridge + abort ✅ (Tasks 7-8), UI + streaming + chips + stop ✅ (Tasks 9-11), AskPanel removal + ⌘K ✅ (Task 12), error handling ✅ (Tasks 4, 5, 11), testing ✅ (every task).
2. **Known judgment calls for the executor:** exact `Btn`/`TopBar`/`Lucide` props and available icon names must be checked against the real components; `App.test.tsx` may need its nav expectations updated; claude CLI flag names follow `llm/client.py` precedent (`--include-partial-messages`, `--strict-mcp-config` — verify against `claude --help` during Task 13 smoke if the CLI version differs).
