# LLM Providers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run every Poltergeist LLM call, batch and chat, on Claude Code (unchanged), the Codex CLI, the Gemini CLI, or a local OpenAI-compatible server, selected by one config key, without touching the 24 batch call sites or the desktop chat renderer.

**Architecture:** A `Provider` protocol in `ghostbrain/llm/providers/` with four adapters. `client.run()` and `agent.run_chat_turn()` become one-line dispatchers. Model choice is a tier (`fast`/`balanced`/`quality`) mapped per provider, with the old Claude aliases as synonyms. Each CLI driver runs with a generated, isolated config so the user's own `~/.codex` / `~/.gemini` are never edited; the local driver runs an in-process tool loop over the four vault tools.

**Tech Stack:** Python 3.11+ (subprocess, httpx, PyYAML, FastAPI), pytest; Electron/React/TypeScript/vitest for the desktop.

**Spec:** `docs/superpowers/specs/2026-09-14-llm-providers-design.md`

## Global Constraints

- Work in the worktree `/Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/llm-providers` on branch `feat/llm-providers`. Every shell command starts with `cd` to that path.
- Python tests: `.venv/bin/python -m pytest <path> -q -p no:cacheprovider`. Create the venv once with `uv sync --extra dev --extra api -q` if `.venv/bin/python` is missing. A repo-root `conftest.py` sandboxes HOME/state/run/vault for every test. Do NOT run `ghostbrain/api/tests/test_recorder_capture_settings.py` or `tests/test_recorder.py` while a manual recording is in flight on this machine (they read the real `~/ghostbrain/recorder/manual.state`).
- Ruff: `.venv/bin/python -m ruff check <files>` must be clean on every file you create or edit (pre-existing findings elsewhere are not yours).
- Desktop: `cd desktop && npm test && npm run typecheck && npm run lint` (zero warnings) before any desktop commit. `npm ci` once if `desktop/node_modules` is missing.
- Provider ids: `claude`, `codex`, `gemini`, `openai_http`. Tiers: `fast`, `balanced`, `quality`. Alias synonyms: `haiku→fast`, `sonnet→balanced`, `opus→quality`.
- Renderer chat event vocabulary is frozen: `{"type":"session","session_id"}`, `{"type":"delta","text"}`, `{"type":"tool","name","summary"}`, `{"type":"done","text","session_id"}`, `{"type":"error","message"}`.
- `client.run()` keeps its exact signature: `run(prompt, *, model=DEFAULT_MODEL, json_schema=None, system_prompt=None, budget_usd=None, timeout_s=DEFAULT_TIMEOUT_S, image_paths=None) -> LLMResult`. `LLMResult` fields stay `text, structured, model, cost_usd, duration_ms, session_id, raw`.
- Never modify `~/.codex/*` or `~/.gemini/*`. Generated CLI configs live under `~/ghostbrain/run/llm/` (`codex/` and `gemini/`), recreated per turn.
- No test shells out to a real CLI or the network. CLI drivers are tested against fixtures in `tests/fixtures/llm/`; the local adapter against a stdlib `http.server` fake. The fixtures in this plan are written from the CLIs' documented formats; Task 13 replaces them with real captures during manual acceptance.
- Commits are conventional commits ending with:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Am1c7X3TWrhHBnMPwzDRVx
  ```

## File structure

Created:
- `ghostbrain/llm/providers/__init__.py` — `get_provider()`, `PROVIDER_IDS`.
- `ghostbrain/llm/providers/base.py` — `Tier`, `to_tier`, `CompletionRequest`, `ChatRequest`, `ProviderProbe`, `Provider`, the running-turn registry (`register_turn`, `cancel_turn`, `kill_all_running`).
- `ghostbrain/llm/providers/config.py` — `LlmConfig`, `load_llm_config()`, `TIER_DEFAULTS`.
- `ghostbrain/llm/providers/claude_cli.py` — today's `claude -p` batch + chat code.
- `ghostbrain/llm/providers/openai_http.py` — HTTP batch adapter + local tool-loop chat.
- `ghostbrain/llm/providers/vault_tools.py` — the four vault tools as OpenAI function schemas + an in-process dispatcher.
- `ghostbrain/llm/providers/codex_cli.py`, `ghostbrain/llm/providers/gemini_cli.py`.
- `ghostbrain/llm/providers/stream.py` — shared subprocess streaming with watchdog/kill-group (extracted from `agent.run_chat_turn`).
- `ghostbrain/api/routes/llm_providers.py` — `GET /v1/llm/providers`.
- `tests/test_llm_providers_*.py`, `tests/fixtures/llm/*`.
- `docs/llm-providers.md`.

Modified: `ghostbrain/llm/client.py` (dispatcher), `ghostbrain/llm/agent.py` (dispatcher; `parse_stream_line` stays for the Claude adapter), `ghostbrain/bootstrap.py` (seeded `llm:` block), `ghostbrain/api/models/settings.py`, `ghostbrain/api/repo/settings.py`, `ghostbrain/api/routes/settings.py`, `ghostbrain/api/main.py`, `ghostbrain/api/repo/answer.py`, `ghostbrain/api/repo/chat.py`, `ghostbrain/doctor/checks_app.py`, `.claude/skills/poltergeist-setup/{SKILL,checks}.md`, `desktop/src/shared/{types,settings-schema,api-types}.ts`, `desktop/src/main/settings.ts`, `desktop/src/renderer/stores/settings.ts`, `desktop/src/renderer/lib/api/hooks.ts`, `desktop/src/renderer/screens/settings.tsx`, `desktop/src/renderer/screens/chat.tsx`, `README.md`.

---

### Task 1: Provider protocol, tiers, and the shared turn registry

**Files:**
- Create: `ghostbrain/llm/providers/__init__.py`, `ghostbrain/llm/providers/base.py`
- Test: `tests/test_llm_providers_base.py`

**Interfaces:**
- Produces (all in `base.py`):
  ```python
  Tier = Literal["fast", "balanced", "quality"]
  TIERS: tuple[str, ...] = ("fast", "balanced", "quality")
  ALIASES: dict[str, str] = {"haiku": "fast", "sonnet": "balanced", "opus": "quality"}
  def to_tier(model: str) -> Tier                      # raises LLMError on unknown
  @dataclass class CompletionRequest: prompt: str; tier: Tier; json_schema: dict|None=None; system_prompt: str|None=None; image_paths: list[str]|None=None; timeout_s: int=120; budget_usd: float|None=None
  @dataclass class ChatRequest: prompt: str; tier: Tier; session_id: str|None; turn_key: str|None; system_prompt: str|None=None; user_servers: list[dict]=field(default_factory=list); history: list[dict]|None=None; timeout_s: int=300; allowed_tools: str|None=None
  @dataclass class ProviderProbe: ok: bool; reason: str; detail: dict=field(default_factory=dict)
  class Provider(Protocol): id: str; def models(self) -> dict[str, str]; def complete(self, req) -> LLMResult; def chat(self, req) -> Iterator[dict]; def probe(self) -> ProviderProbe
  def register_turn(key: str, *, cancelled: threading.Event, kill: Callable[[], None]) -> None
  def unregister_turn(key: str) -> None
  def cancel_turn(key: str) -> bool
  def kill_all_running() -> int
  ```
  `agent.cancel_turn` / `agent.kill_all_running` become re-exports of these (Task 2).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_llm_providers_base.py
from __future__ import annotations

import threading

import pytest

from ghostbrain.llm.client import LLMError
from ghostbrain.llm.providers import base


@pytest.mark.parametrize("name,tier", [
    ("haiku", "fast"), ("sonnet", "balanced"), ("opus", "quality"),
    ("fast", "fast"), ("balanced", "balanced"), ("quality", "quality"),
    ("Sonnet", "balanced"),
])
def test_to_tier_accepts_tiers_and_claude_aliases(name, tier):
    assert base.to_tier(name) == tier


def test_to_tier_rejects_unknown():
    with pytest.raises(LLMError, match="gpt-4"):
        base.to_tier("gpt-4")


def test_turn_registry_cancel_and_kill_all():
    killed: list[str] = []
    ev = threading.Event()
    base.register_turn("conv-1", cancelled=ev, kill=lambda: killed.append("conv-1"))
    base.register_turn("conv-2", cancelled=threading.Event(), kill=lambda: killed.append("conv-2"))
    assert base.cancel_turn("conv-1") is True
    assert ev.is_set() and killed == ["conv-1"]
    assert base.cancel_turn("nope") is False
    assert base.kill_all_running() == 1          # conv-2 still registered
    assert killed == ["conv-1", "conv-2"]
    base.unregister_turn("conv-1"); base.unregister_turn("conv-2")
    assert base.kill_all_running() == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/llm-providers && .venv/bin/python -m pytest tests/test_llm_providers_base.py -q -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.llm.providers'`.

- [ ] **Step 3: Implement**

```python
# ghostbrain/llm/providers/__init__.py
"""LLM provider adapters. `get_provider()` is filled in by config (Task 3)."""
from __future__ import annotations

PROVIDER_IDS: tuple[str, ...] = ("claude", "codex", "gemini", "openai_http")
```

```python
# ghostbrain/llm/providers/base.py
"""Provider protocol, request/response types, tiers, and the shared turn registry.

A provider turns a CompletionRequest into an LLMResult (batch) or a ChatRequest
into the renderer's event stream (chat). Model choice is a *tier*; each provider
maps tiers to its own model names. The old Claude aliases are accepted as tier
synonyms so existing config.yaml keys keep working.
"""
from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Literal, Protocol

from ghostbrain.llm.client import LLMError, LLMResult

Tier = Literal["fast", "balanced", "quality"]
TIERS: tuple[str, ...] = ("fast", "balanced", "quality")
ALIASES: dict[str, str] = {"haiku": "fast", "sonnet": "balanced", "opus": "quality"}


def to_tier(model: str) -> Tier:
    name = (model or "").strip().lower()
    if name in TIERS:
        return name  # type: ignore[return-value]
    if name in ALIASES:
        return ALIASES[name]  # type: ignore[return-value]
    raise LLMError(
        f"unknown model tier {model!r}: use fast | balanced | quality "
        f"(or the aliases haiku | sonnet | opus)"
    )


@dataclass
class CompletionRequest:
    prompt: str
    tier: Tier
    json_schema: dict | None = None
    system_prompt: str | None = None
    image_paths: list[str] | None = None
    timeout_s: int = 120
    budget_usd: float | None = None


@dataclass
class ChatRequest:
    prompt: str
    tier: Tier
    session_id: str | None
    turn_key: str | None
    system_prompt: str | None = None
    user_servers: list[dict] = field(default_factory=list)
    history: list[dict] | None = None
    timeout_s: int = 300
    allowed_tools: str | None = None


@dataclass
class ProviderProbe:
    ok: bool
    reason: str
    detail: dict = field(default_factory=dict)


class Provider(Protocol):
    id: str

    def models(self) -> dict[str, str]: ...
    def complete(self, req: CompletionRequest) -> LLMResult: ...
    def chat(self, req: ChatRequest) -> Iterator[dict]: ...
    def probe(self) -> ProviderProbe: ...


# --- running-turn registry (shared by every chat driver) ---------------------

@dataclass
class _RunningTurn:
    cancelled: threading.Event
    kill: Callable[[], None]


_lock = threading.Lock()
_running: dict[str, _RunningTurn] = {}


def register_turn(key: str, *, cancelled: threading.Event, kill: Callable[[], None]) -> None:
    with _lock:
        _running[key] = _RunningTurn(cancelled=cancelled, kill=kill)


def unregister_turn(key: str) -> None:
    with _lock:
        _running.pop(key, None)


def cancel_turn(key: str) -> bool:
    with _lock:
        entry = _running.get(key)
    if entry is None:
        return False
    entry.cancelled.set()
    entry.kill()
    return True


def kill_all_running() -> int:
    with _lock:
        entries = list(_running.values())
    for e in entries:
        e.cancelled.set()
        e.kill()
    return len(entries)
```

- [ ] **Step 4: Run tests and ruff**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/llm-providers && .venv/bin/python -m pytest tests/test_llm_providers_base.py -q -p no:cacheprovider && .venv/bin/python -m ruff check ghostbrain/llm/providers`
Expected: PASS, ruff clean. (`base.py` imports `LLMError`/`LLMResult` from `client.py`; `client.py` must NOT import `providers` at module level in Task 2 — it imports lazily inside `run()` — or this becomes a cycle.)

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/llm-providers
git add ghostbrain/llm/providers tests/test_llm_providers_base.py
git commit -m "feat(llm): provider protocol, tiers with Claude alias synonyms, shared turn registry"
```

---

### Task 2: Claude adapter extracted; `run()` and `run_chat_turn()` become dispatchers

**Files:**
- Create: `ghostbrain/llm/providers/claude_cli.py`, `ghostbrain/llm/providers/stream.py`
- Modify: `ghostbrain/llm/client.py` (`run()` body), `ghostbrain/llm/agent.py` (`run_chat_turn`, `cancel_turn`, `kill_all_running`)
- Test: `tests/test_llm_providers_claude.py`; existing `tests/test_llm_client.py`, `tests/test_llm_client_image.py`, `tests/test_agent_run.py`, `tests/test_agent_stream.py`, `tests/test_llm_child_lifecycle.py` must pass unchanged.

**Interfaces:**
- Produces:
  ```python
  # stream.py
  def stream_subprocess(cmd, *, timeout_s, turn_key, env=None, stdin_text=None, cwd=None, parse: Callable[[str], list[dict]], on_exit: Callable[[int, str], list[dict]]) -> Iterator[dict]
  # yields parse(line) for each stdout line; registers the turn; watchdog kill-group on timeout; on process exit with no terminal event, yields on_exit(returncode, stderr_tail) events.
  # claude_cli.py
  class ClaudeCli:  id = "claude"
      def __init__(self, models: dict[str,str] | None = None)   # tier→alias overrides
      def models(self) -> dict[str,str]                         # {"fast":"haiku","balanced":"sonnet","quality":"opus"} + overrides
      def build_completion_command(self, req: CompletionRequest) -> list[str]   # today's argv, verbatim
      def complete(self, req) -> LLMResult                       # today's retry loop + _run_once
      def chat(self, req) -> Iterator[dict]                      # today's run_chat_turn body
      def probe(self) -> ProviderProbe
  ```
  `client.run()` calls `_provider().complete(CompletionRequest(...))` where `client._provider()` is a module-level seam returning `get_provider()` (Task 3) — until Task 3 lands it returns `ClaudeCli()`. `client._run_once`, `_parse_json_tolerant`, `_find_claude_binary`, `_redact`, `_pick_model` stay in `client.py` (tests import them) and the adapter imports them.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_llm_providers_claude.py
from __future__ import annotations

import json

from ghostbrain.llm import client as llm_client
from ghostbrain.llm.providers import base
from ghostbrain.llm.providers.claude_cli import ClaudeCli


def test_completion_command_is_identical_to_legacy_argv(monkeypatch):
    """The refactor must be argv-for-argv identical for Claude."""
    monkeypatch.setattr(llm_client, "_find_claude_binary", lambda: "/usr/local/bin/claude")
    req = base.CompletionRequest(
        prompt="hello", tier="fast", json_schema={"type": "object"},
        system_prompt="sys", timeout_s=30, budget_usd=0.25,
    )
    cmd = ClaudeCli().build_completion_command(req)
    assert cmd == [
        "/usr/local/bin/claude", "--print", "--output-format", "json",
        "--model", "haiku", "--system-prompt", "sys", "--no-session-persistence",
        "--max-budget-usd", "0.2500", "--exclude-dynamic-system-prompt-sections",
        "--json-schema", json.dumps({"type": "object"}), "hello",
    ]


def test_tier_overrides_change_model_alias(monkeypatch):
    monkeypatch.setattr(llm_client, "_find_claude_binary", lambda: "/c")
    cmd = ClaudeCli(models={"fast": "sonnet"}).build_completion_command(
        base.CompletionRequest(prompt="p", tier="fast"))
    assert cmd[cmd.index("--model") + 1] == "sonnet"


def test_run_dispatches_through_provider(monkeypatch):
    seen = {}

    class Fake:
        id = "fake"
        def complete(self, req):
            seen["req"] = req
            return llm_client.LLMResult(text="ok", structured=None, model="m",
                                        cost_usd=0, duration_ms=1, session_id="", raw={})
    monkeypatch.setattr(llm_client, "_provider", lambda: Fake())
    out = llm_client.run("hi", model="opus", json_schema={"a": 1}, timeout_s=7)
    assert out.text == "ok"
    assert seen["req"].tier == "quality" and seen["req"].json_schema == {"a": 1}
    assert seen["req"].timeout_s == 7


def test_probe_reports_missing_binary(monkeypatch):
    monkeypatch.setattr(llm_client, "_find_claude_binary", lambda: None)
    p = ClaudeCli().probe()
    assert p.ok is False and "claude" in p.reason
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_llm_providers_claude.py -q -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.llm.providers.claude_cli'`.

- [ ] **Step 3: Implement**

`ghostbrain/llm/providers/stream.py` — extract the subprocess/watchdog/kill-group/registry mechanics from `agent.run_chat_turn` (lines from `proc = subprocess.Popen(` through the `finally:` block) into one reusable generator:

```python
"""Stream a CLI subprocess's stdout as renderer events with the same lifecycle
guarantees run_chat_turn had: own process group, watchdog timeout, cancel via
the turn registry, kill-group on generator close, stderr tail on failure."""
from __future__ import annotations

import os
import signal
import subprocess
import threading
from collections.abc import Callable, Iterator

from ghostbrain.llm.providers import base


def stream_subprocess(
    cmd: list[str], *, timeout_s: int, turn_key: str | None,
    parse: Callable[[str], list[dict]],
    on_exit: Callable[[int, str, bool], list[dict]],
    env: dict[str, str] | None = None, stdin_text: str | None = None, cwd: str | None = None,
) -> Iterator[dict]:
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace",
        env={**os.environ, **(env or {})}, cwd=cwd, start_new_session=True,
    )
    if stdin_text is not None:
        assert proc.stdin is not None
        proc.stdin.write(stdin_text); proc.stdin.close()

    def _kill_group() -> None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        except Exception:  # noqa: BLE001
            proc.kill()

    timed_out = threading.Event()
    cancelled = threading.Event()

    def _on_timeout() -> None:
        timed_out.set(); _kill_group()

    if turn_key is not None:
        base.register_turn(turn_key, cancelled=cancelled, kill=_kill_group)
    killer = threading.Timer(timeout_s, _on_timeout)
    killer.start()
    saw_terminal = False
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            for event in parse(raw):
                if event["type"] in ("done", "error"):
                    saw_terminal = True
                yield event
        proc.wait()
        if not saw_terminal:
            stderr_tail = (proc.stderr.read() if proc.stderr else "")[-2000:]
            if cancelled.is_set():
                yield {"type": "error", "message": "stopped"}
            elif timed_out.is_set():
                yield {"type": "error", "message": f"timed out after {timeout_s}s"}
            else:
                yield from on_exit(proc.returncode, stderr_tail, False)
    finally:
        killer.cancel()
        _kill_group()
        if turn_key is not None:
            base.unregister_turn(turn_key)
```

Read `agent.run_chat_turn`'s existing `finally:` block and the code after it in full before writing this: every behavior it has today (the `ResumeFailed` raise when `--resume` fails before any output, the "stopped" event on cancel, the interrupted-on-timeout event, stderr capture) must be preserved. `on_exit(returncode, stderr_tail, saw_any)` is where the Claude adapter raises `ResumeFailed` (keep `saw_any` tracking: pass it through the closure or extend the signature; the tests in `tests/test_agent_run.py` pin each case).

`ghostbrain/llm/providers/claude_cli.py`:

```python
"""Claude Code adapter: `claude -p` for batch, `claude -p --output-format stream-json` for chat."""
from __future__ import annotations

import json
import logging
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

from ghostbrain.llm import agent, client as llm_client, mcp_servers
from ghostbrain.llm.client import LLMError, LLMRateLimit, LLMResult, LLMTimeout
from ghostbrain.llm.providers import base
from ghostbrain.llm.providers.stream import stream_subprocess

log = logging.getLogger("ghostbrain.llm.providers.claude")

DEFAULT_MODELS: dict[str, str] = {"fast": "haiku", "balanced": "sonnet", "quality": "opus"}


class ClaudeCli:
    id = "claude"

    def __init__(self, models: dict[str, str] | None = None) -> None:
        self._overrides = {k: v for k, v in (models or {}).items() if v}

    def models(self) -> dict[str, str]:
        return {**DEFAULT_MODELS, **self._overrides}

    # -- batch ---------------------------------------------------------------
    def build_completion_command(self, req: base.CompletionRequest) -> list[str]:
        binary = llm_client._find_claude_binary()
        if binary is None:
            raise LLMError(llm_client.BINARY_MISSING_MESSAGE)
        add_dir: list[str] = []
        if req.image_paths:
            dirs = sorted({str(Path(p).resolve().parent) for p in req.image_paths})
            add_dir = ["--add-dir", *dirs]
        cmd = [
            binary, "--print", *add_dir, "--output-format", "json",
            "--model", self.models()[req.tier],
            "--system-prompt", req.system_prompt or llm_client.MINIMAL_SYSTEM_PROMPT,
            "--no-session-persistence",
            "--max-budget-usd", f"{req.budget_usd or llm_client.DEFAULT_BUDGET_USD:.4f}",
            "--exclude-dynamic-system-prompt-sections",
        ]
        if req.json_schema is not None:
            cmd += ["--json-schema", json.dumps(req.json_schema)]
        prompt = req.prompt
        if req.image_paths:
            refs = "\n".join(f"- {p}" for p in req.image_paths)
            prompt = f"{prompt}\n\nRead the following image file(s) and use their contents:\n{refs}"
        cmd.append(prompt)
        return cmd

    def complete(self, req: base.CompletionRequest) -> LLMResult:
        cmd = self.build_completion_command(req)
        last_err: Exception | None = None
        for attempt, delay in enumerate((0,) + llm_client.RETRY_DELAYS_S):
            if delay:
                log.warning("LLM retry %d after %ds (last error: %s)", attempt, delay, last_err)
                time.sleep(delay)
            try:
                return llm_client._run_once(cmd, timeout_s=req.timeout_s)
            except (LLMRateLimit, LLMTimeout) as e:
                last_err = e
        raise LLMError(f"LLM call failed after {len(llm_client.RETRY_DELAYS_S)} retries: {last_err}")

    # -- chat ----------------------------------------------------------------
    def chat(self, req: base.ChatRequest) -> Iterator[dict]:
        # Body of today's agent.run_chat_turn, using stream_subprocess. Keep the
        # missing-binary and missing-MCP-binary error events, mcp_servers.load_enabled(),
        # build_chat_command(...), the CLAUDE_CODE_NO_TELEMETRY env, and ResumeFailed.
        ...

    def probe(self) -> base.ProviderProbe:
        binary = llm_client._find_claude_binary()
        if binary is None:
            return base.ProviderProbe(False, "`claude` CLI not found; install Claude Code and run `claude login`")
        try:
            out = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired) as e:
            return base.ProviderProbe(False, f"`claude --version` failed: {e}")
        if out.returncode != 0:
            return base.ProviderProbe(False, "`claude --version` failed; run `claude login`")
        return base.ProviderProbe(True, out.stdout.strip(), {"binary": binary, "models": self.models()})
```

Move the exact `BINARY_MISSING_MESSAGE` text (currently inline in `client.run`) and `MINIMAL_SYSTEM_PROMPT` to module constants in `client.py` if they are not already. In `client.py`, `run()` becomes:

```python
def _provider():
    """Seam for tests; Task 3 replaces the body with get_provider()."""
    from ghostbrain.llm.providers.claude_cli import ClaudeCli
    return ClaudeCli()


def run(prompt, *, model=DEFAULT_MODEL, json_schema=None, system_prompt=None,
        budget_usd=None, timeout_s=DEFAULT_TIMEOUT_S, image_paths=None) -> LLMResult:
    from ghostbrain.llm.providers.base import CompletionRequest, to_tier
    return _provider().complete(CompletionRequest(
        prompt=prompt, tier=to_tier(model), json_schema=json_schema,
        system_prompt=system_prompt, image_paths=image_paths,
        timeout_s=timeout_s, budget_usd=budget_usd,
    ))
```

In `agent.py`: `run_chat_turn(prompt, *, session_id=None, timeout_s=CHAT_TIMEOUT_S, binary=None, mcp_binary="auto", turn_key=None, system_prompt=None, allowed_tools=None)` keeps its signature (tests call it with `binary=`/`mcp_binary=`); it builds a `ChatRequest` and delegates to `_provider().chat(req)` where `agent._provider()` mirrors `client._provider()`. Because tests pass `binary=`/`mcp_binary=None` overrides that only make sense for Claude, keep those two parameters and pass them to `ClaudeCli.chat` via optional attributes on the adapter (`ClaudeCli(binary=..., mcp_binary=...)`) — when `_provider()` returns a non-Claude provider those overrides are ignored. `cancel_turn` and `kill_all_running` in `agent.py` become `from ghostbrain.llm.providers.base import cancel_turn, kill_all_running` re-exports; delete `_RunningTurn`/`_running`/`_running_lock` from `agent.py`.

- [ ] **Step 4: Run the new tests and every existing LLM test**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/llm-providers && .venv/bin/python -m pytest tests/test_llm_providers_claude.py tests/test_llm_providers_base.py tests/test_llm_client.py tests/test_llm_client_image.py tests/test_agent_run.py tests/test_agent_stream.py tests/test_llm_child_lifecycle.py ghostbrain/api/tests/test_routes_llm_run.py ghostbrain/api/tests/test_chat.py -q -p no:cacheprovider && .venv/bin/python -m ruff check ghostbrain/llm`
Expected: all PASS except `tests/test_agent_stream.py::test_unknown_tool_falls_back_to_raw_name`, which fails on `main` before this change (pre-existing); ruff clean.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/llm-providers
git add ghostbrain/llm tests/test_llm_providers_claude.py
git commit -m "refactor(llm): extract the Claude adapter; run() and run_chat_turn() dispatch through a provider"
```

---

### Task 3: `llm:` config block, tier defaults, `get_provider()`

**Files:**
- Create: `ghostbrain/llm/providers/config.py`
- Modify: `ghostbrain/llm/providers/__init__.py` (`get_provider`), `ghostbrain/llm/client.py` + `ghostbrain/llm/agent.py` (`_provider()` bodies → `get_provider()`), `ghostbrain/bootstrap.py` (seed a commented `llm:` block after the `worker:` block in the config.yaml template)
- Test: `tests/test_llm_providers_config.py`

**Interfaces:**
- Produces:
  ```python
  # config.py
  @dataclass class LlmConfig: provider: str = "claude"; models: dict[str, str|None] = {fast:None,balanced:None,quality:None}; base_url: str = "http://127.0.0.1:11434/v1"; api_key_env: str = "OPENAI_API_KEY"
  TIER_DEFAULTS: dict[str, dict[str, str]] = {"claude": {...haiku/sonnet/opus}, "codex": {"fast":"gpt-5-mini","balanced":"gpt-5","quality":"gpt-5"}, "gemini": {"fast":"gemini-2.5-flash","balanced":"gemini-2.5-pro","quality":"gemini-2.5-pro"}, "openai_http": {}}
  def load_llm_config(cfg: dict | None = None) -> LlmConfig      # reads <vault>/90-meta/config.yaml `llm:` via ghostbrain.recorder.config.load_config_yaml()
  def effective_models(provider_id: str, cfg: LlmConfig) -> dict[str, str]   # defaults + non-null overrides; openai_http returns only the overrides
  # __init__.py
  def get_provider(cfg: LlmConfig | None = None) -> Provider    # claude→ClaudeCli(models=…); others raise LLMError("provider X not implemented yet") until their tasks land
  ```

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_llm_providers_config.py
from __future__ import annotations

from pathlib import Path

import pytest

from ghostbrain.llm.client import LLMError
from ghostbrain.llm.providers import config as pcfg, get_provider


def _write(vault: Path, text: str) -> None:
    (vault / "90-meta").mkdir(parents=True, exist_ok=True)
    (vault / "90-meta" / "config.yaml").write_text(text)


def test_defaults_to_claude_when_block_absent(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    _write(tmp_path, "worker:\n  routing_mode: live\n")
    cfg = pcfg.load_llm_config()
    assert cfg.provider == "claude"
    assert pcfg.effective_models("claude", cfg) == {"fast": "haiku", "balanced": "sonnet", "quality": "opus"}


def test_overrides_and_openai_http_fields(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    _write(tmp_path, "llm:\n  provider: codex\n  models:\n    quality: gpt-5-pro\n  openai_http:\n    base_url: http://127.0.0.1:1234/v1\n    api_key_env: LMSTUDIO_KEY\n")
    cfg = pcfg.load_llm_config()
    assert cfg.provider == "codex"
    assert pcfg.effective_models("codex", cfg) == {"fast": "gpt-5-mini", "balanced": "gpt-5", "quality": "gpt-5-pro"}
    assert cfg.base_url == "http://127.0.0.1:1234/v1" and cfg.api_key_env == "LMSTUDIO_KEY"


def test_unknown_provider_is_rejected(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    _write(tmp_path, "llm:\n  provider: bard\n")
    with pytest.raises(LLMError, match="bard"):
        pcfg.load_llm_config()


def test_get_provider_returns_claude_adapter_with_overrides(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    _write(tmp_path, "llm:\n  provider: claude\n  models:\n    fast: sonnet\n")
    p = get_provider()
    assert p.id == "claude" and p.models()["fast"] == "sonnet"


def test_bootstrap_seeds_commented_llm_block(tmp_path: Path):
    import ghostbrain.bootstrap as bootstrap_mod

    root = bootstrap_mod.bootstrap(tmp_path / "vault")
    text = (root / "90-meta" / "config.yaml").read_text()
    assert "llm:" in text and "# provider: claude" in text and "openai_http" in text
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_llm_providers_config.py -q -p no:cacheprovider`
Expected: FAIL with `ImportError: cannot import name 'config'`.

- [ ] **Step 3: Implement**

```python
# ghostbrain/llm/providers/config.py
"""The `llm:` block of <vault>/90-meta/config.yaml and per-provider tier defaults."""
from __future__ import annotations

from dataclasses import dataclass, field

from ghostbrain.llm.client import LLMError
from ghostbrain.llm.providers import PROVIDER_IDS

TIER_DEFAULTS: dict[str, dict[str, str]] = {
    "claude": {"fast": "haiku", "balanced": "sonnet", "quality": "opus"},
    "codex": {"fast": "gpt-5-mini", "balanced": "gpt-5", "quality": "gpt-5"},
    "gemini": {"fast": "gemini-2.5-flash", "balanced": "gemini-2.5-pro", "quality": "gemini-2.5-pro"},
    "openai_http": {},
}
DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"
DEFAULT_API_KEY_ENV = "OPENAI_API_KEY"


@dataclass
class LlmConfig:
    provider: str = "claude"
    models: dict[str, str | None] = field(default_factory=lambda: {"fast": None, "balanced": None, "quality": None})
    base_url: str = DEFAULT_BASE_URL
    api_key_env: str = DEFAULT_API_KEY_ENV


def load_llm_config(cfg: dict | None = None) -> LlmConfig:
    if cfg is None:
        from ghostbrain.recorder.config import load_config_yaml
        cfg = load_config_yaml()
    block = cfg.get("llm") if isinstance(cfg.get("llm"), dict) else {}
    provider = str(block.get("provider") or "claude").strip().lower()
    if provider not in PROVIDER_IDS:
        raise LLMError(f"llm.provider {provider!r} is not one of {', '.join(PROVIDER_IDS)}")
    raw_models = block.get("models") if isinstance(block.get("models"), dict) else {}
    models = {t: (str(raw_models[t]).strip() if raw_models.get(t) else None) for t in ("fast", "balanced", "quality")}
    http = block.get("openai_http") if isinstance(block.get("openai_http"), dict) else {}
    return LlmConfig(
        provider=provider, models=models,
        base_url=str(http.get("base_url") or DEFAULT_BASE_URL).rstrip("/"),
        api_key_env=str(http.get("api_key_env") or DEFAULT_API_KEY_ENV),
    )


def effective_models(provider_id: str, cfg: LlmConfig) -> dict[str, str]:
    out = dict(TIER_DEFAULTS.get(provider_id, {}))
    out.update({t: m for t, m in cfg.models.items() if m})
    return out
```

`ghostbrain/llm/providers/__init__.py` gains:

```python
def get_provider(cfg=None):
    from ghostbrain.llm.client import LLMError
    from ghostbrain.llm.providers.config import effective_models, load_llm_config

    cfg = cfg or load_llm_config()
    models = effective_models(cfg.provider, cfg)
    if cfg.provider == "claude":
        from ghostbrain.llm.providers.claude_cli import ClaudeCli
        return ClaudeCli(models=models)
    raise LLMError(f"llm.provider {cfg.provider!r} is not implemented yet")
```

(Tasks 4, 6, 8 each add their branch.) `client._provider()` and `agent._provider()` now `return get_provider()` (lazy import). In `ghostbrain/bootstrap.py`, after the `worker:` block of the config template add:

```yaml

llm:
  # Which model provider runs routing, extraction, digests and chat.
  # provider: claude        # claude | codex | gemini | openai_http
  # models:                 # per-tier overrides (null = provider default)
  #   fast: null
  #   balanced: null
  #   quality: null
  # openai_http:
  #   base_url: http://127.0.0.1:11434/v1   # Ollama; LM Studio is http://127.0.0.1:1234/v1
  #   api_key_env: OPENAI_API_KEY           # only read when base_url is not localhost
  {}
```

(`{}` keeps the key present and valid YAML while every value stays commented, matching how the routing template ships empty maps.)

- [ ] **Step 4: Run tests and ruff**

Run: `.venv/bin/python -m pytest tests/test_llm_providers_config.py tests/test_llm_providers_claude.py tests/test_bootstrap_routing_mode.py -q -p no:cacheprovider && .venv/bin/python -m ruff check ghostbrain/llm/providers ghostbrain/bootstrap.py`
Expected: PASS, ruff clean on the providers package (pre-existing bootstrap findings are not yours).

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/llm/providers ghostbrain/llm/client.py ghostbrain/llm/agent.py ghostbrain/bootstrap.py tests/test_llm_providers_config.py
git commit -m "feat(llm): llm config block, per-provider tier defaults, get_provider()"
```

---

### Task 4: `openai_http` batch adapter (Ollama, LM Studio, any OpenAI-compatible server)

**Files:**
- Create: `ghostbrain/llm/providers/openai_http.py`
- Modify: `ghostbrain/llm/providers/__init__.py` (branch)
- Test: `tests/test_llm_providers_openai_http.py`

**Interfaces:**
- Produces:
  ```python
  class OpenAiHttp:  id = "openai_http"
      def __init__(self, base_url: str, api_key_env: str, models: dict[str,str])
      def is_ollama(self) -> bool                         # GET {origin}/api/tags answers (cached per instance)
      def build_messages(self, req: CompletionRequest) -> list[dict]
      def complete(self, req) -> LLMResult
      def probe(self) -> ProviderProbe                    # GET {base_url}/models; detail["models"] = [ids]; ok only if all three tiers are set and listed
      def chat(self, req) -> Iterator[dict]               # Task 5
  ```

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_llm_providers_openai_http.py
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ghostbrain.llm.client import LLMError
from ghostbrain.llm.providers import base
from ghostbrain.llm.providers.openai_http import OpenAiHttp


class _Fake(BaseHTTPRequestHandler):
    """Scripted OpenAI-compatible server. Set `script` per test."""
    script: dict = {}
    seen: list[dict] = []

    def log_message(self, *a): pass

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        if self.path == "/v1/models":
            return self._send(200, {"data": [{"id": m} for m in self.script.get("models", [])]})
        if self.path == "/api/tags":
            if self.script.get("ollama"):
                return self._send(200, {"models": [{"name": m} for m in self.script.get("models", [])]})
            return self._send(404, {})
        self._send(404, {})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        _Fake.seen.append({"path": self.path, "body": body, "auth": self.headers.get("Authorization")})
        if self.path == "/v1/chat/completions":
            return self._send(200, {"choices": [{"message": {"role": "assistant", "content": self.script["reply"]}}], "model": body.get("model")})
        if self.path == "/api/chat":
            return self._send(200, {"message": {"role": "assistant", "content": self.script["reply"]}, "model": body.get("model")})
        self._send(404, {})


@pytest.fixture
def server():
    _Fake.seen = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Fake)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/v1"
    httpd.shutdown()


MODELS = {"fast": "llama3.2", "balanced": "qwen3", "quality": "qwen3"}


def test_complete_uses_chat_completions_with_system_and_json_schema(server):
    _Fake.script = {"reply": '{"ok": true}', "models": list(MODELS.values())}
    p = OpenAiHttp(server, "NOPE_KEY", MODELS)
    out = p.complete(base.CompletionRequest(prompt="hi", tier="fast", system_prompt="be terse",
                                            json_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}}))
    assert out.structured == {"ok": True} and out.model == "llama3.2" and out.cost_usd == 0
    req = _Fake.seen[-1]
    assert req["path"] == "/v1/chat/completions" and req["auth"] is None   # localhost: no key sent
    assert req["body"]["messages"][0] == {"role": "system", "content": "be terse"}
    assert req["body"]["response_format"]["type"] == "json_schema"


def test_ollama_uses_api_chat_with_format(server):
    _Fake.script = {"reply": '{"a": 1}', "models": ["qwen3"], "ollama": True}
    p = OpenAiHttp(server, "K", {"fast": "qwen3", "balanced": "qwen3", "quality": "qwen3"})
    out = p.complete(base.CompletionRequest(prompt="p", tier="fast", json_schema={"type": "object"}))
    assert out.structured == {"a": 1}
    assert _Fake.seen[-1]["path"] == "/api/chat" and _Fake.seen[-1]["body"]["format"] == {"type": "object"}


def test_non_localhost_sends_bearer_from_env(monkeypatch, server):
    _Fake.script = {"reply": "x", "models": ["m"]}
    monkeypatch.setenv("MY_KEY", "sk-test")
    p = OpenAiHttp(server.replace("127.0.0.1", "localhost"), "MY_KEY", {"fast": "m", "balanced": "m", "quality": "m"})
    p._is_local = lambda: False  # type: ignore[attr-defined]
    p.complete(base.CompletionRequest(prompt="p", tier="fast"))
    assert _Fake.seen[-1]["auth"] == "Bearer sk-test"


def test_missing_tier_model_is_llm_error(server):
    p = OpenAiHttp(server, "K", {"fast": "m"})
    with pytest.raises(LLMError, match="balanced"):
        p.complete(base.CompletionRequest(prompt="p", tier="balanced"))


def test_probe_lists_models_and_requires_all_tiers(server):
    _Fake.script = {"models": ["llama3.2", "qwen3"]}
    assert OpenAiHttp(server, "K", MODELS).probe().ok is True
    bad = OpenAiHttp(server, "K", {"fast": "llama3.2"}).probe()
    assert bad.ok is False and "balanced" in bad.reason and bad.detail["models"] == ["llama3.2", "qwen3"]
    down = OpenAiHttp("http://127.0.0.1:9/v1", "K", MODELS).probe()
    assert down.ok is False and "not answering" in down.reason


def test_image_paths_become_data_url_parts(server, tmp_path):
    img = tmp_path / "a.png"; img.write_bytes(b"\x89PNG\r\n\x1a\n")
    _Fake.script = {"reply": "seen", "models": list(MODELS.values())}
    OpenAiHttp(server, "K", MODELS).complete(base.CompletionRequest(prompt="describe", tier="fast", image_paths=[str(img)]))
    content = _Fake.seen[-1]["body"]["messages"][-1]["content"]
    assert content[0] == {"type": "text", "text": "describe"}
    assert content[1]["type"] == "image_url" and content[1]["image_url"]["url"].startswith("data:image/png;base64,")
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_llm_providers_openai_http.py -q -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError ... openai_http`.

- [ ] **Step 3: Implement**

```python
# ghostbrain/llm/providers/openai_http.py
"""Local / OpenAI-compatible HTTP adapter (Ollama, LM Studio, OpenRouter-style endpoints)."""
from __future__ import annotations

import base64
import json
import logging
import mimetypes
import os
import time
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse

import httpx

from ghostbrain.llm.client import LLMError, LLMResult, LLMTimeout, _parse_json_tolerant
from ghostbrain.llm.providers import base

log = logging.getLogger("ghostbrain.llm.providers.openai_http")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}


class OpenAiHttp:
    id = "openai_http"

    def __init__(self, base_url: str, api_key_env: str, models: dict[str, str]) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key_env = api_key_env
        self._models = dict(models)
        self._ollama: bool | None = None

    # -- helpers ---------------------------------------------------------------
    def models(self) -> dict[str, str]:
        return dict(self._models)

    def _origin(self) -> str:
        u = urlparse(self.base_url)
        return f"{u.scheme}://{u.netloc}"

    def _is_local(self) -> bool:
        return (urlparse(self.base_url).hostname or "") in LOCAL_HOSTS

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if not self._is_local():
            key = os.environ.get(self.api_key_env, "")
            if key:
                h["Authorization"] = f"Bearer {key}"
        return h

    def is_ollama(self) -> bool:
        if self._ollama is None:
            try:
                r = httpx.get(f"{self._origin()}/api/tags", timeout=3.0)
                self._ollama = r.status_code == 200
            except httpx.HTTPError:
                self._ollama = False
        return self._ollama

    def _model_for(self, tier: str) -> str:
        model = self._models.get(tier)
        if not model:
            raise LLMError(f"openai_http: no model configured for the {tier} tier — set llm.models.{tier} in config.yaml")
        return model

    def build_messages(self, req: base.CompletionRequest) -> list[dict]:
        msgs: list[dict] = []
        if req.system_prompt:
            msgs.append({"role": "system", "content": req.system_prompt})
        if req.image_paths:
            parts: list[dict] = [{"type": "text", "text": req.prompt}]
            for p in req.image_paths:
                mime = mimetypes.guess_type(p)[0] or "application/octet-stream"
                data = base64.b64encode(Path(p).read_bytes()).decode()
                parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}})
            msgs.append({"role": "user", "content": parts})
        else:
            msgs.append({"role": "user", "content": req.prompt})
        return msgs

    # -- batch -----------------------------------------------------------------
    def complete(self, req: base.CompletionRequest) -> LLMResult:
        model = self._model_for(req.tier)
        messages = self.build_messages(req)
        started = time.monotonic()
        try:
            if self.is_ollama():
                body: dict = {"model": model, "messages": messages, "stream": False}
                if req.json_schema is not None:
                    body["format"] = req.json_schema
                r = httpx.post(f"{self._origin()}/api/chat", json=body, headers=self._headers(), timeout=req.timeout_s)
                r.raise_for_status()
                text = (r.json().get("message") or {}).get("content") or ""
            else:
                body = {"model": model, "messages": messages, "stream": False}
                if req.json_schema is not None:
                    body["response_format"] = {"type": "json_schema", "json_schema": {"name": "result", "schema": req.json_schema}}
                r = httpx.post(f"{self.base_url}/chat/completions", json=body, headers=self._headers(), timeout=req.timeout_s)
                r.raise_for_status()
                text = ((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        except httpx.TimeoutException as e:
            raise LLMTimeout(f"openai_http: timed out after {req.timeout_s}s") from e
        except httpx.HTTPError as e:
            raise LLMError(f"openai_http: {e}") from e
        structured = _parse_json_tolerant(text) if req.json_schema is not None else None
        return LLMResult(text=text, structured=structured, model=model, cost_usd=0.0,
                         duration_ms=int((time.monotonic() - started) * 1000), session_id="", raw={"body": body})

    def probe(self) -> base.ProviderProbe:
        try:
            r = httpx.get(f"{self.base_url}/models", headers=self._headers(), timeout=3.0)
            r.raise_for_status()
            listed = [m.get("id") for m in (r.json().get("data") or []) if m.get("id")]
        except httpx.HTTPError as e:
            return base.ProviderProbe(False, f"{self.base_url} is not answering ({e.__class__.__name__}); start Ollama or LM Studio, or fix llm.openai_http.base_url", {"base_url": self.base_url})
        missing = [t for t in base.TIERS if not self._models.get(t)]
        if missing:
            return base.ProviderProbe(False, f"no model set for tier(s): {', '.join(missing)} — pick them in Settings → AI provider", {"base_url": self.base_url, "models": listed})
        absent = [m for m in self._models.values() if listed and m not in listed]
        if absent:
            return base.ProviderProbe(False, f"model(s) not installed on the server: {', '.join(sorted(set(absent)))}", {"base_url": self.base_url, "models": listed})
        return base.ProviderProbe(True, f"{self.base_url} ({'ollama' if self.is_ollama() else 'openai-compatible'})", {"base_url": self.base_url, "models": listed, "tiers": self.models()})

    def chat(self, req: base.ChatRequest) -> Iterator[dict]:
        raise LLMError("openai_http chat lands in Task 5")
```

Add the branch to `get_provider()`: `if cfg.provider == "openai_http": return OpenAiHttp(cfg.base_url, cfg.api_key_env, models)`.

- [ ] **Step 4: Run tests and ruff**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/llm-providers && .venv/bin/python -m pytest tests/test_llm_providers_openai_http.py tests/test_llm_providers_config.py -q -p no:cacheprovider && .venv/bin/python -m ruff check ghostbrain/llm/providers`
Expected: PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/llm/providers tests/test_llm_providers_openai_http.py
git commit -m "feat(llm): openai_http batch adapter with Ollama format and OpenAI json_schema support"
```

---

### Task 5: Vault tools as functions + the local chat tool loop

**Files:**
- Create: `ghostbrain/llm/providers/vault_tools.py`
- Modify: `ghostbrain/llm/providers/openai_http.py` (`chat`)
- Test: `tests/test_llm_providers_vault_tools.py`, `tests/test_llm_providers_openai_http_chat.py`

**Interfaces:**
- Produces:
  ```python
  # vault_tools.py
  TOOL_SCHEMAS: list[dict]      # OpenAI function-tool definitions for poltergeist_search/get_note/ask/write_doc, descriptions copied from ghostbrain/mcp/__main__.py
  def call_tool(name: str, arguments: dict, client=None) -> str   # dispatches to ghostbrain.mcp.tools.{search,get_note,ask,write_doc}(client, **arguments); unknown name → "error: unknown tool <name>"
  def summary_for(name: str, arguments: dict) -> str               # reuses agent.TOOL_SUMMARIES templates → e.g. "searched vault: q"
  MAX_TOOL_ROUNDS = 8
  ```
  `OpenAiHttp.chat(req)` yields `session` (id = `req.turn_key or "local"`), `delta` per streamed text chunk, `tool` per tool call, then `done` with the full text; errors → `error`. Uses `req.history` (list of `{"role","text"}` from the chat store) to rebuild `messages`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_llm_providers_vault_tools.py
from __future__ import annotations

from ghostbrain.llm.providers import vault_tools as vt


def test_schemas_cover_the_four_tools_with_required_params():
    names = {t["function"]["name"] for t in vt.TOOL_SCHEMAS}
    assert names == {"poltergeist_search", "poltergeist_get_note", "poltergeist_ask", "poltergeist_write_doc"}
    by = {t["function"]["name"]: t["function"]["parameters"] for t in vt.TOOL_SCHEMAS}
    assert by["poltergeist_search"]["required"] == ["query"]
    assert set(by["poltergeist_write_doc"]["required"]) == {"title", "html"}


def test_call_tool_dispatches_to_mcp_tools(monkeypatch):
    from ghostbrain.mcp import tools
    monkeypatch.setattr(tools, "search", lambda client, query, limit=10, days=None: f"hits for {query} ({limit},{days})")
    assert vt.call_tool("poltergeist_search", {"query": "budget", "days": 7}, client=object()) == "hits for budget (10,7)"
    assert vt.call_tool("nope", {}, client=object()).startswith("error: unknown tool")


def test_summary_matches_claude_tool_summaries():
    assert vt.summary_for("poltergeist_search", {"query": "q"}) == "searched vault: q"
    assert vt.summary_for("poltergeist_get_note", {"path": "a/b.md"}) == "read note: a/b.md"
```

```python
# tests/test_llm_providers_openai_http_chat.py
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ghostbrain.llm.providers import base, vault_tools
from ghostbrain.llm.providers.openai_http import OpenAiHttp


def _sse(chunks):
    return "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"


class _Fake(BaseHTTPRequestHandler):
    turns: list[str] = []      # scripted SSE bodies, consumed in order
    seen: list[dict] = []
    def log_message(self, *a): pass
    def do_GET(self):
        self.send_response(404); self.end_headers()
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); body = json.loads(self.rfile.read(n))
        _Fake.seen.append(body)
        data = _Fake.turns.pop(0).encode()
        self.send_response(200); self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)


@pytest.fixture
def server():
    _Fake.seen = []; _Fake.turns = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Fake)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/v1"
    httpd.shutdown()


M = {"fast": "m", "balanced": "m", "quality": "m"}


def test_chat_streams_text_then_done(server):
    _Fake.turns = [_sse([
        {"choices": [{"delta": {"content": "Hel"}}]},
        {"choices": [{"delta": {"content": "lo"}}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ])]
    p = OpenAiHttp(server, "K", M); p._ollama = False
    events = list(p.chat(base.ChatRequest(prompt="hi", tier="balanced", session_id=None, turn_key="c1", system_prompt="sys")))
    assert events[0] == {"type": "session", "session_id": "c1"}
    assert [e["text"] for e in events if e["type"] == "delta"] == ["Hel", "lo"]
    assert events[-1] == {"type": "done", "text": "Hello", "session_id": "c1"}
    body = _Fake.seen[0]
    assert body["stream"] is True and body["messages"][0]["role"] == "system"
    assert {t["function"]["name"] for t in body["tools"]} == {"poltergeist_search", "poltergeist_get_note", "poltergeist_ask", "poltergeist_write_doc"}


def test_chat_runs_a_tool_round_and_feeds_the_result_back(server, monkeypatch):
    monkeypatch.setattr(vault_tools, "call_tool", lambda name, args, client=None: f"RESULT({name},{args['query']})")
    _Fake.turns = [
        _sse([{"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "poltergeist_search", "arguments": "{\"query\": \"budget\"}"}}]}, "finish_reason": "tool_calls"}]}]),
        _sse([{"choices": [{"delta": {"content": "Found it."}}]}, {"choices": [{"delta": {}, "finish_reason": "stop"}]}]),
    ]
    p = OpenAiHttp(server, "K", M); p._ollama = False
    events = list(p.chat(base.ChatRequest(prompt="q", tier="fast", session_id=None, turn_key="c2",
                                          history=[{"role": "user", "text": "earlier"}, {"role": "assistant", "text": "ok"}])))
    assert {"type": "tool", "name": "poltergeist_search", "summary": "searched vault: budget"} in events
    assert events[-1]["type"] == "done" and events[-1]["text"] == "Found it."
    second = _Fake.seen[1]["messages"]
    assert second[-1] == {"role": "tool", "tool_call_id": "call_1", "content": "RESULT(poltergeist_search,budget)"}
    assert second[1]["content"] == "earlier" and second[2]["content"] == "ok"   # history replayed after system


def test_chat_gives_up_after_max_rounds(server, monkeypatch):
    monkeypatch.setattr(vault_tools, "call_tool", lambda *a, **k: "r")
    call = _sse([{"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "x", "function": {"name": "poltergeist_ask", "arguments": "{\"question\":\"?\"}"}}]}, "finish_reason": "tool_calls"}]}])
    _Fake.turns = [call] * (vault_tools.MAX_TOOL_ROUNDS + 1)
    p = OpenAiHttp(server, "K", M); p._ollama = False
    events = list(p.chat(base.ChatRequest(prompt="q", tier="fast", session_id=None, turn_key="c3")))
    assert events[-1]["type"] == "error" and "tool rounds" in events[-1]["message"]


def test_chat_http_failure_is_error_event(server):
    p = OpenAiHttp("http://127.0.0.1:9/v1", "K", M); p._ollama = False
    events = list(p.chat(base.ChatRequest(prompt="q", tier="fast", session_id=None, turn_key="c4")))
    assert events[-1]["type"] == "error"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_llm_providers_vault_tools.py tests/test_llm_providers_openai_http_chat.py -q -p no:cacheprovider`
Expected: FAIL (`vault_tools` missing; chat raises the Task-5 placeholder).

- [ ] **Step 3: Implement**

```python
# ghostbrain/llm/providers/vault_tools.py
"""The four Poltergeist vault tools as OpenAI-style function definitions, for
providers that have no MCP client (local models). Descriptions mirror the MCP
server in ghostbrain/mcp/__main__.py; execution calls the same implementations."""
from __future__ import annotations

import json
import logging

from ghostbrain.llm.agent import TOOL_SUMMARIES
from ghostbrain.mcp import tools

log = logging.getLogger("ghostbrain.llm.providers.vault_tools")
MAX_TOOL_ROUNDS = 8


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required}}}


TOOL_SCHEMAS: list[dict] = [
    _fn("poltergeist_search",
        "Semantic search across the user's vault. Cheap and fast (no LLM). Returns ranked note paths with snippets; follow up with poltergeist_get_note to read a full note. For time-anchored questions pass days (today → 1, this week → 7).",
        {"query": {"type": "string"}, "limit": {"type": "integer", "default": 10}, "days": {"type": "integer"}}, ["query"]),
    _fn("poltergeist_get_note",
        "Fetch the full content and metadata of one vault note by its vault-relative path (as returned by poltergeist_search or a citation from poltergeist_ask).",
        {"path": {"type": "string"}}, ["path"]),
    _fn("poltergeist_ask",
        "Ask a natural-language question about the user's own work, history, and decisions across all their contexts. Returns a synthesized answer with citations. Costs an LLM call — prefer poltergeist_search when you only need to locate notes.",
        {"question": {"type": "string"}, "limit": {"type": "integer", "default": 8}}, ["question"]),
    _fn("poltergeist_write_doc",
        "Save a document the user asked you to write. Pass a COMPLETE, self-contained HTML document as html. Returns the vault-relative path of the saved doc.",
        {"title": {"type": "string"}, "html": {"type": "string"}}, ["title", "html"]),
]

_DISPATCH = {
    "poltergeist_search": lambda c, a: tools.search(c, a["query"], limit=int(a.get("limit", 10)), days=a.get("days")),
    "poltergeist_get_note": lambda c, a: tools.get_note(c, a["path"]),
    "poltergeist_ask": lambda c, a: tools.ask(c, a["question"], limit=int(a.get("limit", 8))),
    "poltergeist_write_doc": lambda c, a: tools.write_doc(c, a["title"], a["html"]),
}


def call_tool(name: str, arguments: dict, client=None) -> str:
    fn = _DISPATCH.get(name)
    if fn is None:
        return f"error: unknown tool {name}"
    if client is None:
        from ghostbrain.mcp.client import SidecarClient
        client = SidecarClient()
    try:
        return str(fn(client, arguments or {}))
    except Exception as e:  # noqa: BLE001 — the model must see the failure, not the loop
        log.warning("vault tool %s failed: %s", name, e)
        return f"error: {e}"


def summary_for(name: str, arguments: dict) -> str:
    entry = TOOL_SUMMARIES.get(f"mcp__poltergeist__{name}") or TOOL_SUMMARIES.get(name)
    if not entry:
        return name
    _, template = entry
    try:
        return template.format(**{k: (v if isinstance(v, str) else json.dumps(v)) for k, v in (arguments or {}).items()})
    except (KeyError, IndexError):
        return template
```

(Read `agent.TOOL_SUMMARIES`' value shape at `agent.py:74-86` before writing `summary_for`: entries are `(short_name, template)` tuples keyed by the `mcp__poltergeist__…` name; adapt if the shape differs.)

`OpenAiHttp.chat` (replace the placeholder):

```python
    def chat(self, req: base.ChatRequest) -> Iterator[dict]:
        from ghostbrain.llm.agent import CHAT_SYSTEM_PROMPT
        from ghostbrain.llm.providers import vault_tools

        sid = req.session_id or req.turn_key or "local"
        yield {"type": "session", "session_id": sid}
        try:
            model = self._model_for(req.tier)
        except LLMError as e:
            yield {"type": "error", "message": str(e)}; return
        messages: list[dict] = [{"role": "system", "content": req.system_prompt or CHAT_SYSTEM_PROMPT}]
        for m in req.history or []:
            messages.append({"role": m["role"], "content": m["text"]})
        messages.append({"role": "user", "content": req.prompt})
        cancelled = threading.Event()
        if req.turn_key:
            base.register_turn(req.turn_key, cancelled=cancelled, kill=lambda: None)
        full: list[str] = []
        try:
            for _round in range(vault_tools.MAX_TOOL_ROUNDS + 1):
                if _round == vault_tools.MAX_TOOL_ROUNDS:
                    yield {"type": "error", "message": f"gave up after {vault_tools.MAX_TOOL_ROUNDS} tool rounds"}; return
                text, calls = yield from self._stream_once(model, messages, req.timeout_s, cancelled, full)
                if cancelled.is_set():
                    yield {"type": "error", "message": "stopped"}; return
                if not calls:
                    yield {"type": "done", "text": "".join(full), "session_id": sid}; return
                messages.append({"role": "assistant", "content": text or None, "tool_calls": calls})
                for c in calls:
                    args = _parse_json_tolerant(c["function"]["arguments"] or "{}") if c["function"]["arguments"] else {}
                    yield {"type": "tool", "name": c["function"]["name"], "summary": vault_tools.summary_for(c["function"]["name"], args)}
                    result = vault_tools.call_tool(c["function"]["name"], args)
                    messages.append({"role": "tool", "tool_call_id": c["id"], "content": result})
        except httpx.HTTPError as e:
            yield {"type": "error", "message": f"openai_http: {e}"}
        finally:
            if req.turn_key:
                base.unregister_turn(req.turn_key)

    def _stream_once(self, model, messages, timeout_s, cancelled, full):
        """Stream one completion. Yields delta events; returns (text, tool_calls)."""
        body = {"model": model, "messages": messages, "stream": True, "tools": vault_tools.TOOL_SCHEMAS}
        url = f"{self.base_url}/chat/completions"
        text_parts: list[str] = []
        calls: dict[int, dict] = {}
        with httpx.stream("POST", url, json=body, headers=self._headers(), timeout=timeout_s) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if cancelled.is_set():
                    break
                if not line.startswith("data: "):
                    continue
                payload = line[6:].strip()
                if payload == "[DONE]":
                    break
                delta = ((json.loads(payload).get("choices") or [{}])[0]).get("delta") or {}
                if delta.get("content"):
                    text_parts.append(delta["content"]); full.append(delta["content"])
                    yield {"type": "delta", "text": delta["content"]}
                for tc in delta.get("tool_calls") or []:
                    slot = calls.setdefault(tc.get("index", 0), {"id": tc.get("id", ""), "type": "function", "function": {"name": "", "arguments": ""}})
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["function"]["name"] = fn["name"]
                    slot["function"]["arguments"] += fn.get("arguments") or ""
        return "".join(text_parts), [calls[i] for i in sorted(calls)]
```

(`_stream_once` is a generator that returns a value; call it with `yield from`. Import `threading` and keep `vault_tools` imported lazily inside `chat` to avoid a cycle through `agent`.) Ollama's `/v1/chat/completions` supports streaming tool calls in the same OpenAI shape, so the chat path uses `/v1/chat/completions` for both; only batch structured output special-cases `/api/chat`.

- [ ] **Step 4: Run tests and ruff**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/llm-providers && .venv/bin/python -m pytest tests/test_llm_providers_vault_tools.py tests/test_llm_providers_openai_http_chat.py tests/test_llm_providers_openai_http.py -q -p no:cacheprovider && .venv/bin/python -m ruff check ghostbrain/llm/providers`
Expected: PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/llm/providers tests/test_llm_providers_vault_tools.py tests/test_llm_providers_openai_http_chat.py
git commit -m "feat(llm): local chat via an in-process tool loop over the four vault tools"
```

---

### Task 6: Codex CLI batch adapter

**Files:**
- Create: `ghostbrain/llm/providers/codex_cli.py`, `tests/fixtures/llm/codex-exec-message.jsonl`, `tests/fixtures/llm/codex-exec-error.jsonl`
- Modify: `ghostbrain/llm/providers/__init__.py` (branch)
- Test: `tests/test_llm_providers_codex.py`

**Interfaces:**
- Produces:
  ```python
  class CodexCli:  id = "codex"
      def __init__(self, models: dict[str,str], binary: str | None = None)
      def build_completion_command(self, req, schema_path: Path | None) -> list[str]
      def complete(self, req) -> LLMResult
      def probe(self) -> ProviderProbe
      def chat(self, req) -> Iterator[dict]        # Task 7
  def parse_exec_events(lines: Iterable[str]) -> tuple[str, str | None, str | None]
      # returns (final_agent_message_text, thread_id, error_message)
  def find_codex_binary() -> str | None            # GHOSTBRAIN_CODEX_BIN → shutil.which("codex") → ~/.local/bin, /opt/homebrew/bin, /usr/local/bin
  ```
  Fixture `codex-exec-message.jsonl` (documented `codex exec --json` event shapes):
  ```
  {"type":"thread.started","thread_id":"thr_abc123"}
  {"type":"turn.started"}
  {"type":"item.started","item":{"id":"item_1","type":"agent_message","text":""}}
  {"type":"item.completed","item":{"id":"item_1","type":"agent_message","text":"{\"context\": \"work\", \"confidence\": 0.9}"}}
  {"type":"turn.completed","usage":{"input_tokens":120,"output_tokens":18}}
  ```
  Fixture `codex-exec-error.jsonl`:
  ```
  {"type":"thread.started","thread_id":"thr_err"}
  {"type":"turn.started"}
  {"type":"turn.failed","error":{"message":"Model quota exceeded for this account"}}
  ```

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_llm_providers_codex.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ghostbrain.llm.client import LLMError
from ghostbrain.llm.providers import base
from ghostbrain.llm.providers import codex_cli as cx

FIX = Path(__file__).parent / "fixtures" / "llm"
M = {"fast": "gpt-5-mini", "balanced": "gpt-5", "quality": "gpt-5"}


def test_parse_exec_events_returns_final_message_and_thread():
    text, thread, err = cx.parse_exec_events((FIX / "codex-exec-message.jsonl").read_text().splitlines())
    assert json.loads(text) == {"context": "work", "confidence": 0.9}
    assert thread == "thr_abc123" and err is None


def test_parse_exec_events_surfaces_turn_failed():
    text, thread, err = cx.parse_exec_events((FIX / "codex-exec-error.jsonl").read_text().splitlines())
    assert text == "" and thread == "thr_err" and "quota" in err


def test_completion_command_shape(tmp_path: Path):
    p = cx.CodexCli(M, binary="/usr/local/bin/codex")
    req = base.CompletionRequest(prompt="classify this", tier="quality", system_prompt="be terse", json_schema={"type": "object"})
    cmd = p.build_completion_command(req, schema_path=tmp_path / "schema.json")
    assert cmd[:2] == ["/usr/local/bin/codex", "exec"]
    for flag in ("--json", "--skip-git-repo-check", "--ephemeral"):
        assert flag in cmd
    assert cmd[cmd.index("--sandbox") + 1] == "read-only"
    assert cmd[cmd.index("-m") + 1] == "gpt-5"
    assert cmd[cmd.index("--output-schema") + 1] == str(tmp_path / "schema.json")
    assert "-c" in cmd and 'model_reasoning_effort="high"' in cmd   # quality tier only
    assert cmd[-1] == "-"                                            # prompt on stdin


def test_stdin_text_prepends_system_prompt():
    p = cx.CodexCli(M)
    text = p.stdin_text(base.CompletionRequest(prompt="hello", tier="fast", system_prompt="You are terse."))
    assert text.startswith("<instructions>\nYou are terse.\n</instructions>\n\n") and text.endswith("hello")


def test_complete_runs_subprocess_and_parses(monkeypatch, tmp_path: Path):
    p = cx.CodexCli(M, binary="/c")
    monkeypatch.setattr(cx, "_run", lambda cmd, stdin_text, timeout_s: ((FIX / "codex-exec-message.jsonl").read_text(), "", 0))
    out = p.complete(base.CompletionRequest(prompt="x", tier="fast", json_schema={"type": "object"}))
    assert out.structured == {"context": "work", "confidence": 0.9} and out.model == "gpt-5-mini" and out.session_id == "thr_abc123"


def test_complete_error_event_raises(monkeypatch):
    p = cx.CodexCli(M, binary="/c")
    monkeypatch.setattr(cx, "_run", lambda cmd, stdin_text, timeout_s: ((FIX / "codex-exec-error.jsonl").read_text(), "", 1))
    with pytest.raises(LLMError, match="quota"):
        p.complete(base.CompletionRequest(prompt="x", tier="fast"))


def test_images_are_refused():
    with pytest.raises(LLMError, match="image"):
        cx.CodexCli(M, binary="/c").complete(base.CompletionRequest(prompt="x", tier="fast", image_paths=["/a.png"]))


def test_probe_missing_binary_and_logged_out(monkeypatch):
    monkeypatch.setattr(cx, "find_codex_binary", lambda: None)
    assert cx.CodexCli(M).probe().ok is False
    monkeypatch.setattr(cx, "find_codex_binary", lambda: "/c")
    monkeypatch.setattr(cx, "_run", lambda cmd, stdin_text, timeout_s: ("", "Not logged in", 1))
    pr = cx.CodexCli(M).probe()
    assert pr.ok is False and "codex login" in pr.reason
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_llm_providers_codex.py -q -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError ... codex_cli`.

- [ ] **Step 3: Implement**

Write the two fixture files with the exact lines above. Then:

```python
# ghostbrain/llm/providers/codex_cli.py
"""OpenAI Codex CLI adapter (`codex exec`), billed to the user's ChatGPT login."""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Iterable, Iterator
from pathlib import Path

from ghostbrain.llm.client import LLMError, LLMResult, LLMTimeout, _parse_json_tolerant
from ghostbrain.llm.providers import base

log = logging.getLogger("ghostbrain.llm.providers.codex")


def find_codex_binary() -> str | None:
    env = os.environ.get("GHOSTBRAIN_CODEX_BIN")
    if env and Path(env).is_file():
        return env
    found = shutil.which("codex")
    if found:
        return found
    for c in (Path.home() / ".local/bin/codex", Path("/opt/homebrew/bin/codex"), Path("/usr/local/bin/codex")):
        if c.is_file():
            return str(c)
    return None


def _run(cmd: list[str], stdin_text: str | None, timeout_s: int) -> tuple[str, str, int]:
    """Seam: (stdout, stderr, returncode). Own process group so a hung CLI can be killed."""
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace",
                            start_new_session=True)
    try:
        out, err = proc.communicate(stdin_text, timeout=timeout_s)
    except subprocess.TimeoutExpired as e:
        import signal
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        raise LLMTimeout(f"codex exec timed out after {timeout_s}s") from e
    return out, err, proc.returncode


def parse_exec_events(lines: Iterable[str]) -> tuple[str, str | None, str | None]:
    text, thread, err = "", None, None
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError:
            continue
        t = ev.get("type")
        if t == "thread.started":
            thread = ev.get("thread_id")
        elif t == "item.completed" and (ev.get("item") or {}).get("type") == "agent_message":
            text = str((ev.get("item") or {}).get("text") or "")
        elif t in ("turn.failed", "error"):
            err = str(((ev.get("error") or {}).get("message")) or ev.get("message") or "codex turn failed")
    return text, thread, err


class CodexCli:
    id = "codex"

    def __init__(self, models: dict[str, str], binary: str | None = None) -> None:
        self._models = dict(models)
        self._binary = binary

    def models(self) -> dict[str, str]:
        return dict(self._models)

    def _bin(self) -> str:
        b = self._binary or find_codex_binary()
        if b is None:
            raise LLMError("`codex` CLI not found; install it (`npm i -g @openai/codex`) and run `codex login`, or set GHOSTBRAIN_CODEX_BIN")
        return b

    def stdin_text(self, req: base.CompletionRequest) -> str:
        if req.system_prompt:
            return f"<instructions>\n{req.system_prompt}\n</instructions>\n\n{req.prompt}"
        return req.prompt

    def build_completion_command(self, req: base.CompletionRequest, schema_path: Path | None) -> list[str]:
        cmd = [self._bin(), "exec", "--json", "--sandbox", "read-only", "--skip-git-repo-check", "--ephemeral",
               "-m", self._models[req.tier]]
        if req.tier == "quality":
            cmd += ["-c", 'model_reasoning_effort="high"']
        if schema_path is not None:
            cmd += ["--output-schema", str(schema_path)]
        cmd.append("-")
        return cmd

    def complete(self, req: base.CompletionRequest) -> LLMResult:
        if req.image_paths:
            raise LLMError("codex: image input is unsupported in non-interactive mode (codex exec --json hangs with --image)")
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="ghostbrain-codex-") as d:
            schema_path = None
            if req.json_schema is not None:
                schema_path = Path(d) / "schema.json"
                schema_path.write_text(json.dumps(req.json_schema))
            cmd = self.build_completion_command(req, schema_path)
            out, err, rc = _run(cmd, self.stdin_text(req), req.timeout_s)
        text, thread, error = parse_exec_events(out.splitlines())
        if error or (rc != 0 and not text):
            raise LLMError(f"codex exec failed: {error or err.strip()[-500:] or f'exit {rc}'}")
        structured = _parse_json_tolerant(text) if req.json_schema is not None else None
        return LLMResult(text=text, structured=structured, model=self._models[req.tier], cost_usd=0.0,
                         duration_ms=int((time.monotonic() - started) * 1000), session_id=thread or "", raw={"cmd": cmd})

    def probe(self) -> base.ProviderProbe:
        b = self._binary or find_codex_binary()
        if b is None:
            return base.ProviderProbe(False, "`codex` CLI not found; install with `npm i -g @openai/codex`, then `codex login`")
        out, err, rc = _run([b, "login", "status"], None, 15)
        if rc != 0:
            return base.ProviderProbe(False, "codex is not logged in; run `codex login` (ChatGPT account)", {"binary": b, "stderr": err[-300:]})
        return base.ProviderProbe(True, (out or "logged in").strip().splitlines()[-1], {"binary": b, "models": self.models()})

    def chat(self, req: base.ChatRequest) -> Iterator[dict]:
        raise LLMError("codex chat lands in Task 7")
```

Add to `get_provider()`: `if cfg.provider == "codex": return CodexCli(models)`.

- [ ] **Step 4: Run tests and ruff**

Run: `.venv/bin/python -m pytest tests/test_llm_providers_codex.py -q -p no:cacheprovider && .venv/bin/python -m ruff check ghostbrain/llm/providers`
Expected: PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/llm/providers tests/fixtures/llm tests/test_llm_providers_codex.py
git commit -m "feat(llm): Codex CLI batch adapter with --output-schema structured output"
```

---

### Task 7: Codex chat driver with an isolated `CODEX_HOME`

**Files:**
- Create: `tests/fixtures/llm/codex-exec-chat.jsonl`
- Modify: `ghostbrain/llm/providers/codex_cli.py` (`chat`, `write_codex_home`, `parse_chat_line`)
- Test: `tests/test_llm_providers_codex_chat.py`

**Interfaces:**
- Produces:
  ```python
  def write_codex_home(root: Path, *, model: str, mcp_argv: list[str], user_servers: list[dict], real_home: Path) -> Path
      # writes root/config.toml; symlinks root/auth.json → real_home/auth.json if it exists; returns root
  def parse_chat_line(line: str) -> list[dict]     # codex --json event → renderer events
  CodexCli.chat(req) -> Iterator[dict]
  ```
  Fixture `codex-exec-chat.jsonl`:
  ```
  {"type":"thread.started","thread_id":"thr_chat1"}
  {"type":"turn.started"}
  {"type":"item.started","item":{"id":"i1","type":"mcp_tool_call","server":"poltergeist","tool":"poltergeist_search","arguments":{"query":"budget"}}}
  {"type":"item.completed","item":{"id":"i1","type":"mcp_tool_call","server":"poltergeist","tool":"poltergeist_search","status":"completed"}}
  {"type":"item.completed","item":{"id":"i2","type":"agent_message","text":"The budget was approved on [[20-contexts/work/budget]]."}}
  {"type":"turn.completed","usage":{"input_tokens":900,"output_tokens":40}}
  ```

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_llm_providers_codex_chat.py
from __future__ import annotations

import tomllib
from pathlib import Path

from ghostbrain.llm.providers import base
from ghostbrain.llm.providers import codex_cli as cx

FIX = Path(__file__).parent / "fixtures" / "llm"
M = {"fast": "gpt-5-mini", "balanced": "gpt-5", "quality": "gpt-5"}


def test_parse_chat_line_maps_events():
    lines = (FIX / "codex-exec-chat.jsonl").read_text().splitlines()
    events = [e for line in lines for e in cx.parse_chat_line(line)]
    assert events[0] == {"type": "session", "session_id": "thr_chat1"}
    assert {"type": "tool", "name": "poltergeist_search", "summary": "searched vault: budget"} in events
    assert events[-2]["type"] == "delta" and "budget was approved" in events[-2]["text"]
    assert events[-1]["type"] == "done" and events[-1]["session_id"] == "thr_chat1"


def test_write_codex_home_config_and_auth_symlink(tmp_path: Path):
    real = tmp_path / "real-codex"; real.mkdir(); (real / "auth.json").write_text("{}")
    root = cx.write_codex_home(tmp_path / "gen", model="gpt-5", mcp_argv=["/app/ghostbrain-api", "mcp"],
                               user_servers=[{"name": "mem", "command": "npx", "args": ["-y", "mem-mcp"], "env": {"TOKEN": "t"}}],
                               real_home=real)
    cfg = tomllib.loads((root / "config.toml").read_text())
    assert cfg["model"] == "gpt-5" and cfg["sandbox_mode"] == "read-only" and cfg["approval_policy"] == "never"
    assert cfg["mcp_servers"]["poltergeist"] == {"command": "/app/ghostbrain-api", "args": ["mcp"], "required": True}
    assert cfg["mcp_servers"]["mem"]["command"] == "npx" and cfg["mcp_servers"]["mem"]["env"] == {"TOKEN": "t"}
    assert (root / "auth.json").is_symlink() and (root / "auth.json").resolve() == (real / "auth.json").resolve()


def test_chat_command_and_env(monkeypatch, tmp_path: Path):
    captured = {}
    def fake_stream(cmd, **kw):
        captured["cmd"] = cmd; captured["kw"] = kw
        for line in (FIX / "codex-exec-chat.jsonl").read_text().splitlines():
            yield from cx.parse_chat_line(line)
    monkeypatch.setattr(cx, "stream_subprocess", fake_stream)
    monkeypatch.setattr(cx, "find_codex_binary", lambda: "/c")
    monkeypatch.setattr(cx, "_run_root", lambda: tmp_path / "run")
    monkeypatch.setattr(cx, "_real_codex_home", lambda: tmp_path / "nohome")
    p = cx.CodexCli(M)
    events = list(p.chat(base.ChatRequest(prompt="q", tier="balanced", session_id=None, turn_key="c1", system_prompt="sys")))
    assert events[-1]["type"] == "done"
    assert captured["cmd"][:3] == ["/c", "exec", "--json"] and captured["cmd"][-1] == "-"
    assert captured["kw"]["env"]["CODEX_HOME"] == str(tmp_path / "run" / "codex")
    assert captured["kw"]["stdin_text"].startswith("<instructions>\nsys")
    assert (tmp_path / "run" / "codex" / "config.toml").exists()


def test_chat_resume_uses_exec_resume(monkeypatch, tmp_path: Path):
    captured = {}
    def fake_stream(cmd, **kw):
        captured["cmd"] = cmd
        yield {"type": "done", "text": "ok", "session_id": "thr_chat1"}
    monkeypatch.setattr(cx, "stream_subprocess", fake_stream)
    monkeypatch.setattr(cx, "find_codex_binary", lambda: "/c")
    monkeypatch.setattr(cx, "_run_root", lambda: tmp_path / "run")
    monkeypatch.setattr(cx, "_real_codex_home", lambda: tmp_path / "nohome")
    list(cx.CodexCli(M).chat(base.ChatRequest(prompt="more", tier="fast", session_id="thr_chat1", turn_key="c2")))
    assert captured["cmd"][1:4] == ["exec", "resume", "thr_chat1"]


def test_chat_missing_binary_is_error_event(monkeypatch):
    monkeypatch.setattr(cx, "find_codex_binary", lambda: None)
    events = list(cx.CodexCli(M).chat(base.ChatRequest(prompt="q", tier="fast", session_id=None, turn_key=None)))
    assert events == [{"type": "error", "message": events[0]["message"]}] and "codex" in events[0]["message"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_llm_providers_codex_chat.py -q -p no:cacheprovider`
Expected: FAIL (`parse_chat_line`/`write_codex_home` missing).

- [ ] **Step 3: Implement** (in `codex_cli.py`)

```python
from ghostbrain.llm.providers.stream import stream_subprocess   # module import so tests can monkeypatch cx.stream_subprocess


def _run_root() -> Path:
    from ghostbrain.api.runtime import run_dir
    return run_dir() / "llm"


def _real_codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))


def _toml_str(s: str) -> str:
    return json.dumps(s)   # JSON string escaping is valid TOML basic-string escaping for our values


def write_codex_home(root: Path, *, model: str, mcp_argv: list[str], user_servers: list[dict], real_home: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    lines = [f"model = {_toml_str(model)}", 'sandbox_mode = "read-only"', 'approval_policy = "never"', ""]
    lines += ["[mcp_servers.poltergeist]", f"command = {_toml_str(mcp_argv[0])}",
              "args = [" + ", ".join(_toml_str(a) for a in mcp_argv[1:]) + "]", "required = true", ""]
    for s in user_servers:
        lines += [f"[mcp_servers.{s['name']}]", f"command = {_toml_str(s['command'])}",
                  "args = [" + ", ".join(_toml_str(a) for a in s.get("args") or []) + "]"]
        if s.get("env"):
            lines.append("env = { " + ", ".join(f"{k} = {_toml_str(v)}" for k, v in s["env"].items()) + " }")
        lines.append("")
    (root / "config.toml").write_text("\n".join(lines))
    auth_src = real_home / "auth.json"
    auth_dst = root / "auth.json"
    if auth_dst.is_symlink() or auth_dst.exists():
        auth_dst.unlink()
    if auth_src.exists():
        auth_dst.symlink_to(auth_src)
    return root


def parse_chat_line(line: str) -> list[dict]:
    from ghostbrain.llm.providers import vault_tools
    line = line.strip()
    if not line:
        return []
    try:
        ev = json.loads(line)
    except json.JSONDecodeError:
        return []
    t, item = ev.get("type"), ev.get("item") or {}
    if t == "thread.started":
        return [{"type": "session", "session_id": str(ev.get("thread_id") or "")}]
    if t == "item.started" and item.get("type") == "mcp_tool_call":
        name = str(item.get("tool") or "")
        return [{"type": "tool", "name": name, "summary": vault_tools.summary_for(name, item.get("arguments") or {})}]
    if t == "item.completed" and item.get("type") == "agent_message":
        return [{"type": "delta", "text": str(item.get("text") or "")}]
    if t == "turn.completed":
        return [{"type": "done", "text": "", "session_id": ""}]
    if t in ("turn.failed", "error"):
        return [{"type": "error", "message": str(((ev.get("error") or {}).get("message")) or ev.get("message") or "codex turn failed")}]
    return []
```

`CodexCli.chat`:

```python
    def chat(self, req: base.ChatRequest) -> Iterator[dict]:
        from ghostbrain.llm.agent import CHAT_SYSTEM_PROMPT, find_mcp_binary
        b = self._binary or find_codex_binary()
        if b is None:
            yield {"type": "error", "message": "`codex` CLI not found; install it and run `codex login`"}; return
        mcp = find_mcp_binary()
        if mcp is None:
            yield {"type": "error", "message": "Vault tools are unavailable: the ghostbrain-api mcp helper could not be found"}; return
        home = write_codex_home(_run_root() / "codex", model=self._models[req.tier], mcp_argv=list(mcp),
                                user_servers=req.user_servers, real_home=_real_codex_home())
        cmd = [b, "exec"]
        if req.session_id:
            cmd += ["resume", req.session_id]
        cmd += ["--json", "--skip-git-repo-check", "-"]
        stdin = f"<instructions>\n{req.system_prompt or CHAT_SYSTEM_PROMPT}\n</instructions>\n\n{req.prompt}"
        session = req.session_id or ""
        text_parts: list[str] = []
        for ev in stream_subprocess(cmd, timeout_s=req.timeout_s, turn_key=req.turn_key, parse=parse_chat_line,
                                    on_exit=lambda rc, err, saw: [{"type": "error", "message": f"codex exited {rc}: {err[-300:]}"}],
                                    env={"CODEX_HOME": str(home)}, stdin_text=stdin):
            if ev["type"] == "session":
                session = ev["session_id"]
            elif ev["type"] == "delta":
                text_parts.append(ev["text"])
            elif ev["type"] == "done":
                ev = {"type": "done", "text": "".join(text_parts), "session_id": session}
            yield ev
```

- [ ] **Step 4: Run tests and ruff**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/llm-providers && .venv/bin/python -m pytest tests/test_llm_providers_codex_chat.py tests/test_llm_providers_codex.py -q -p no:cacheprovider && .venv/bin/python -m ruff check ghostbrain/llm/providers`
Expected: PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/llm/providers/codex_cli.py tests/fixtures/llm/codex-exec-chat.jsonl tests/test_llm_providers_codex_chat.py
git commit -m "feat(llm): Codex chat driver with an isolated CODEX_HOME carrying the vault MCP server"
```

---

### Task 8: Gemini CLI batch adapter

**Files:**
- Create: `ghostbrain/llm/providers/gemini_cli.py`, `tests/fixtures/llm/gemini-json.json`
- Modify: `ghostbrain/llm/providers/__init__.py` (branch)
- Test: `tests/test_llm_providers_gemini.py`

**Interfaces:**
- Produces:
  ```python
  class GeminiCli:  id = "gemini"
      def __init__(self, models, binary=None)
      def build_completion_command(self, req) -> list[str]     # [gemini, "-p", <prompt>, "--output-format", "json", "-m", model]
      def prompt_text(self, req, *, strict=False) -> str        # system prompt + schema instruction + prompt (+ @image refs)
      def complete(self, req) -> LLMResult                       # one retry with strict=True when schema parsing fails
      def probe(self) -> ProviderProbe                           # binary + auth type in ~/.gemini/settings.json (or GEMINI_API_KEY)
      def chat(self, req) -> Iterator[dict]                      # Task 9
  def find_gemini_binary() -> str | None
  def read_gemini_auth() -> str | None                           # security.auth.selectedType from ~/.gemini/settings.json; "gemini-api-key" when GEMINI_API_KEY is set
  ```
  Fixture `gemini-json.json`: `{"response": "{\"context\": \"work\", \"confidence\": 0.8}", "stats": {"models": {"gemini-2.5-flash": {"tokens": {"prompt": 100, "candidates": 20}}}}}`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_llm_providers_gemini.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ghostbrain.llm.client import LLMError
from ghostbrain.llm.providers import base
from ghostbrain.llm.providers import gemini_cli as gm

FIX = Path(__file__).parent / "fixtures" / "llm"
M = {"fast": "gemini-2.5-flash", "balanced": "gemini-2.5-pro", "quality": "gemini-2.5-pro"}


def test_command_shape():
    p = gm.GeminiCli(M, binary="/g")
    req = base.CompletionRequest(prompt="hi", tier="quality")
    cmd = p.build_completion_command(req)
    assert cmd[0] == "/g" and cmd[1] == "-p" and cmd[-4:] == ["--output-format", "json", "-m", "gemini-2.5-pro"]


def test_prompt_embeds_system_schema_and_images(tmp_path: Path):
    p = gm.GeminiCli(M, binary="/g")
    req = base.CompletionRequest(prompt="classify", tier="fast", system_prompt="be terse",
                                 json_schema={"type": "object"}, image_paths=[str(tmp_path / "x.png")])
    text = p.prompt_text(req)
    assert text.startswith("be terse\n\n")
    assert "Respond with JSON matching this schema" in text and json.dumps({"type": "object"}) in text
    assert f"@{tmp_path / 'x.png'}" in text
    assert "ONLY the JSON" in p.prompt_text(req, strict=True)


def test_complete_parses_response_field(monkeypatch):
    monkeypatch.setattr(gm, "_run", lambda cmd, timeout_s: ((FIX / "gemini-json.json").read_text(), "", 0))
    out = gm.GeminiCli(M, binary="/g").complete(base.CompletionRequest(prompt="x", tier="fast", json_schema={"type": "object"}))
    assert out.structured == {"context": "work", "confidence": 0.8} and out.model == "gemini-2.5-flash"


def test_complete_retries_once_with_strict_prompt_then_raises(monkeypatch):
    calls = []
    def fake(cmd, timeout_s):
        calls.append(cmd[2])
        return (json.dumps({"response": "Sure! Here is prose without JSON."}), "", 0)
    monkeypatch.setattr(gm, "_run", fake)
    with pytest.raises(LLMError):
        gm.GeminiCli(M, binary="/g").complete(base.CompletionRequest(prompt="x", tier="fast", json_schema={"type": "object"}))
    assert len(calls) == 2 and "ONLY the JSON" in calls[1]


def test_complete_error_field_raises(monkeypatch):
    monkeypatch.setattr(gm, "_run", lambda cmd, timeout_s: (json.dumps({"error": {"message": "quota"}}), "", 1))
    with pytest.raises(LLMError, match="quota"):
        gm.GeminiCli(M, binary="/g").complete(base.CompletionRequest(prompt="x", tier="fast"))


def test_probe_auth_detection(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(gm, "find_gemini_binary", lambda: "/g")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(gm, "_settings_path", lambda: tmp_path / "settings.json")
    assert gm.GeminiCli(M).probe().ok is False
    (tmp_path / "settings.json").write_text(json.dumps({"security": {"auth": {"selectedType": "oauth-personal"}}}))
    pr = gm.GeminiCli(M).probe()
    assert pr.ok is True and pr.detail["auth"] == "oauth-personal"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_llm_providers_gemini.py -q -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError ... gemini_cli`.

- [ ] **Step 3: Implement**

```python
# ghostbrain/llm/providers/gemini_cli.py
"""Google Gemini CLI adapter (`gemini -p`), billed to the user's Google login."""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

from ghostbrain.llm.client import LLMError, LLMResult, LLMTimeout, _parse_json_tolerant
from ghostbrain.llm.providers import base

log = logging.getLogger("ghostbrain.llm.providers.gemini")
SCHEMA_INSTRUCTION = "Respond with JSON matching this schema, and nothing else:\n{schema}"
STRICT_INSTRUCTION = "Output ONLY the JSON object — no prose, no markdown fences, no explanation.\n"


def find_gemini_binary() -> str | None:
    env = os.environ.get("GHOSTBRAIN_GEMINI_BIN")
    if env and Path(env).is_file():
        return env
    found = shutil.which("gemini")
    if found:
        return found
    for c in (Path.home() / ".local/bin/gemini", Path("/opt/homebrew/bin/gemini"), Path("/usr/local/bin/gemini")):
        if c.is_file():
            return str(c)
    return None


def _settings_path() -> Path:
    return Path.home() / ".gemini" / "settings.json"


def read_gemini_auth() -> str | None:
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini-api-key"
    try:
        doc = json.loads(_settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return ((doc.get("security") or {}).get("auth") or {}).get("selectedType") or None


def _run(cmd: list[str], timeout_s: int) -> tuple[str, str, int]:
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, errors="replace", start_new_session=True)
    try:
        out, err = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired as e:
        import signal
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        raise LLMTimeout(f"gemini timed out after {timeout_s}s") from e
    return out, err, proc.returncode


class GeminiCli:
    id = "gemini"

    def __init__(self, models: dict[str, str], binary: str | None = None) -> None:
        self._models = dict(models)
        self._binary = binary

    def models(self) -> dict[str, str]:
        return dict(self._models)

    def _bin(self) -> str:
        b = self._binary or find_gemini_binary()
        if b is None:
            raise LLMError("`gemini` CLI not found; install it (`npm i -g @google/gemini-cli`) and sign in, or set GHOSTBRAIN_GEMINI_BIN")
        return b

    def prompt_text(self, req: base.CompletionRequest, *, strict: bool = False) -> str:
        parts: list[str] = []
        if req.system_prompt:
            parts.append(req.system_prompt)
        if req.json_schema is not None:
            parts.append((STRICT_INSTRUCTION if strict else "") + SCHEMA_INSTRUCTION.format(schema=json.dumps(req.json_schema)))
        body = req.prompt
        if req.image_paths:
            body += "\n\n" + "\n".join(f"@{p}" for p in req.image_paths)
        parts.append(body)
        return "\n\n".join(parts)

    def build_completion_command(self, req: base.CompletionRequest, *, strict: bool = False) -> list[str]:
        return [self._bin(), "-p", self.prompt_text(req, strict=strict), "--output-format", "json", "-m", self._models[req.tier]]

    def _once(self, req: base.CompletionRequest, *, strict: bool) -> tuple[str, dict]:
        out, err, rc = _run(self.build_completion_command(req, strict=strict), req.timeout_s)
        try:
            doc = json.loads(out) if out.strip() else {}
        except json.JSONDecodeError:
            doc = {}
        if doc.get("error"):
            raise LLMError(f"gemini: {(doc['error'] or {}).get('message') or doc['error']}")
        if rc != 0 and not doc.get("response"):
            raise LLMError(f"gemini exited {rc}: {err.strip()[-500:]}")
        return str(doc.get("response") or ""), doc

    def complete(self, req: base.CompletionRequest) -> LLMResult:
        started = time.monotonic()
        text, doc = self._once(req, strict=False)
        structured = None
        if req.json_schema is not None:
            try:
                structured = _parse_json_tolerant(text)
            except LLMError:
                log.warning("gemini: no JSON in response; retrying with the strict instruction")
                text, doc = self._once(req, strict=True)
                structured = _parse_json_tolerant(text)   # raises LLMError if still not JSON
        return LLMResult(text=text, structured=structured, model=self._models[req.tier], cost_usd=0.0,
                         duration_ms=int((time.monotonic() - started) * 1000), session_id="", raw=doc)

    def probe(self) -> base.ProviderProbe:
        b = self._binary or find_gemini_binary()
        if b is None:
            return base.ProviderProbe(False, "`gemini` CLI not found; install with `npm i -g @google/gemini-cli` and sign in")
        auth = read_gemini_auth()
        if auth is None:
            return base.ProviderProbe(False, "gemini is not signed in; run `gemini` once and choose Login with Google (or set GEMINI_API_KEY)", {"binary": b})
        return base.ProviderProbe(True, f"gemini ({auth})", {"binary": b, "auth": auth, "models": self.models()})

    def chat(self, req: base.ChatRequest) -> Iterator[dict]:
        raise LLMError("gemini chat lands in Task 9")
```

Add to `get_provider()`: `if cfg.provider == "gemini": return GeminiCli(models)`.

- [ ] **Step 4: Run tests and ruff**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/llm-providers && .venv/bin/python -m pytest tests/test_llm_providers_gemini.py -q -p no:cacheprovider && .venv/bin/python -m ruff check ghostbrain/llm/providers`
Expected: PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/llm/providers tests/fixtures/llm/gemini-json.json tests/test_llm_providers_gemini.py
git commit -m "feat(llm): Gemini CLI batch adapter with prompt-embedded schema and one strict retry"
```

---

### Task 9: Gemini chat driver with a per-turn workspace settings file

**Files:**
- Create: `tests/fixtures/llm/gemini-stream.jsonl`
- Modify: `ghostbrain/llm/providers/gemini_cli.py` (`chat`, `write_gemini_workspace`, `parse_stream_line`, `supports_resume`)
- Test: `tests/test_llm_providers_gemini_chat.py`

**Interfaces:**
- Produces:
  ```python
  def write_gemini_workspace(root: Path, *, mcp_argv: list[str], user_servers: list[dict], auth_type: str | None) -> Path
      # writes root/.gemini/settings.json: {"security":{"auth":{"selectedType":auth}}, "mcpServers": {"poltergeist": {command,args,trust:true,includeTools:[4 tools]}, <user>: {...,trust:true}}}
  def parse_stream_line(line: str) -> list[dict]
  def supports_resume(binary: str) -> bool     # cached: "--resume" in `gemini --help`
  GeminiCli.chat(req)
  ```
  Fixture `gemini-stream.jsonl` (documented `--output-format stream-json` events):
  ```
  {"type":"init","session_id":"gs-1","model":"gemini-2.5-pro"}
  {"type":"tool_use","tool_name":"poltergeist_search","parameters":{"query":"budget"}}
  {"type":"tool_result","tool_name":"poltergeist_search","status":"success"}
  {"type":"message","role":"assistant","content":"The budget was approved."}
  {"type":"result","status":"success","stats":{"total_tokens":1200}}
  ```

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_llm_providers_gemini_chat.py
from __future__ import annotations

import json
from pathlib import Path

from ghostbrain.llm.providers import base
from ghostbrain.llm.providers import gemini_cli as gm

FIX = Path(__file__).parent / "fixtures" / "llm"
M = {"fast": "gemini-2.5-flash", "balanced": "gemini-2.5-pro", "quality": "gemini-2.5-pro"}


def test_parse_stream_line_maps_events():
    events = [e for line in (FIX / "gemini-stream.jsonl").read_text().splitlines() for e in gm.parse_stream_line(line)]
    assert events[0] == {"type": "session", "session_id": "gs-1"}
    assert {"type": "tool", "name": "poltergeist_search", "summary": "searched vault: budget"} in events
    assert {"type": "delta", "text": "The budget was approved."} in events
    assert events[-1]["type"] == "done"


def test_parse_stream_line_error():
    assert gm.parse_stream_line(json.dumps({"type": "error", "message": "quota"})) == [{"type": "error", "message": "quota"}]


def test_write_gemini_workspace(tmp_path: Path):
    root = gm.write_gemini_workspace(tmp_path / "ws", mcp_argv=["/app/ghostbrain-api", "mcp"],
                                     user_servers=[{"name": "mem", "command": "npx", "args": ["mem"], "env": {}, "tools": ""}],
                                     auth_type="oauth-personal")
    doc = json.loads((root / ".gemini" / "settings.json").read_text())
    assert doc["security"]["auth"]["selectedType"] == "oauth-personal"
    pol = doc["mcpServers"]["poltergeist"]
    assert pol["command"] == "/app/ghostbrain-api" and pol["args"] == ["mcp"] and pol["trust"] is True
    assert set(pol["includeTools"]) == {"poltergeist_search", "poltergeist_get_note", "poltergeist_ask", "poltergeist_write_doc"}
    assert doc["mcpServers"]["mem"]["trust"] is True


def test_chat_command_cwd_and_events(monkeypatch, tmp_path: Path):
    captured = {}
    def fake_stream(cmd, **kw):
        captured["cmd"] = cmd; captured["kw"] = kw
        for line in (FIX / "gemini-stream.jsonl").read_text().splitlines():
            yield from gm.parse_stream_line(line)
    monkeypatch.setattr(gm, "stream_subprocess", fake_stream)
    monkeypatch.setattr(gm, "find_gemini_binary", lambda: "/g")
    monkeypatch.setattr(gm, "supports_resume", lambda binary: True)
    monkeypatch.setattr(gm, "read_gemini_auth", lambda: "oauth-personal")
    monkeypatch.setattr(gm, "_run_root", lambda: tmp_path / "run")
    events = list(gm.GeminiCli(M).chat(base.ChatRequest(prompt="q", tier="balanced", session_id="gs-0", turn_key="c1", system_prompt="sys")))
    cmd = captured["cmd"]
    assert cmd[0] == "/g" and cmd[cmd.index("--output-format") + 1] == "stream-json"
    assert "--approval-mode=yolo" in cmd and cmd[cmd.index("-m") + 1] == "gemini-2.5-pro"
    assert cmd[cmd.index("--resume") + 1] == "gs-0"
    assert cmd[cmd.index("-p") + 1].startswith("sys\n\n")
    assert captured["kw"]["cwd"] == str(tmp_path / "run" / "gemini")
    assert events[-1] == {"type": "done", "text": "The budget was approved.", "session_id": "gs-1"}


def test_chat_without_resume_support_prefixes_history(monkeypatch, tmp_path: Path):
    captured = {}
    def fake_stream(cmd, **kw):
        captured["cmd"] = cmd
        yield {"type": "done", "text": "ok", "session_id": ""}
    monkeypatch.setattr(gm, "stream_subprocess", fake_stream)
    monkeypatch.setattr(gm, "find_gemini_binary", lambda: "/g")
    monkeypatch.setattr(gm, "supports_resume", lambda binary: False)
    monkeypatch.setattr(gm, "read_gemini_auth", lambda: "oauth-personal")
    monkeypatch.setattr(gm, "_run_root", lambda: tmp_path / "run")
    list(gm.GeminiCli(M).chat(base.ChatRequest(prompt="next", tier="fast", session_id="gs-0", turn_key="c2",
                                                 history=[{"role": "user", "text": "first"}, {"role": "assistant", "text": "reply"}])))
    assert "--resume" not in captured["cmd"]
    prompt = captured["cmd"][captured["cmd"].index("-p") + 1]
    assert "user: first" in prompt and "assistant: reply" in prompt and prompt.rstrip().endswith("user: next")
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_llm_providers_gemini_chat.py -q -p no:cacheprovider`
Expected: FAIL (`parse_stream_line`/`write_gemini_workspace` missing).

- [ ] **Step 3: Implement** (in `gemini_cli.py`)

```python
from ghostbrain.llm.providers.stream import stream_subprocess

VAULT_TOOL_NAMES = ["poltergeist_search", "poltergeist_get_note", "poltergeist_ask", "poltergeist_write_doc"]
_resume_cache: dict[str, bool] = {}


def _run_root() -> Path:
    from ghostbrain.api.runtime import run_dir
    return run_dir() / "llm"


def supports_resume(binary: str) -> bool:
    if binary not in _resume_cache:
        try:
            out = subprocess.run([binary, "--help"], capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.TimeoutExpired):
            out = ""
        _resume_cache[binary] = "--resume" in out
    return _resume_cache[binary]


def write_gemini_workspace(root: Path, *, mcp_argv: list[str], user_servers: list[dict], auth_type: str | None) -> Path:
    (root / ".gemini").mkdir(parents=True, exist_ok=True)
    servers: dict[str, dict] = {}
    for s in user_servers:
        entry: dict = {"command": s["command"], "args": list(s.get("args") or []), "trust": True}
        if s.get("env"):
            entry["env"] = dict(s["env"])
        if s.get("tools"):
            entry["includeTools"] = [t.strip() for t in s["tools"].split(",") if t.strip()]
        servers[s["name"]] = entry
    servers["poltergeist"] = {"command": mcp_argv[0], "args": list(mcp_argv[1:]), "trust": True, "includeTools": list(VAULT_TOOL_NAMES)}
    doc: dict = {"mcpServers": servers}
    if auth_type:
        doc["security"] = {"auth": {"selectedType": auth_type}}
    (root / ".gemini" / "settings.json").write_text(json.dumps(doc, indent=2))
    return root


def parse_stream_line(line: str) -> list[dict]:
    from ghostbrain.llm.providers import vault_tools
    line = line.strip()
    if not line:
        return []
    try:
        ev = json.loads(line)
    except json.JSONDecodeError:
        return []
    t = ev.get("type")
    if t == "init":
        return [{"type": "session", "session_id": str(ev.get("session_id") or "")}]
    if t == "tool_use":
        name = str(ev.get("tool_name") or "")
        return [{"type": "tool", "name": name, "summary": vault_tools.summary_for(name, ev.get("parameters") or {})}]
    if t == "message" and ev.get("role") == "assistant" and ev.get("content"):
        return [{"type": "delta", "text": str(ev["content"])}]
    if t == "result":
        if ev.get("status") not in (None, "success"):
            return [{"type": "error", "message": str(ev.get("error") or ev.get("status"))}]
        return [{"type": "done", "text": "", "session_id": ""}]
    if t == "error":
        return [{"type": "error", "message": str(ev.get("message") or "gemini error")}]
    return []
```

`GeminiCli.chat`:

```python
    def chat(self, req: base.ChatRequest) -> Iterator[dict]:
        from ghostbrain.llm.agent import CHAT_SYSTEM_PROMPT, find_mcp_binary
        b = self._binary or find_gemini_binary()
        if b is None:
            yield {"type": "error", "message": "`gemini` CLI not found; install it and sign in"}; return
        mcp = find_mcp_binary()
        if mcp is None:
            yield {"type": "error", "message": "Vault tools are unavailable: the ghostbrain-api mcp helper could not be found"}; return
        ws = write_gemini_workspace(_run_root() / "gemini", mcp_argv=list(mcp), user_servers=req.user_servers, auth_type=read_gemini_auth())
        resume = bool(req.session_id) and supports_resume(b)
        prompt = req.prompt
        if req.session_id and not resume and req.history:
            lines = [f"{m['role']}: {m['text']}" for m in req.history]
            prompt = "Earlier in this conversation (transcript):\n\n" + "\n\n".join(lines) + f"\n\nuser: {req.prompt}"
        full_prompt = f"{req.system_prompt or CHAT_SYSTEM_PROMPT}\n\n{prompt}"
        cmd = [b, "-p", full_prompt, "--output-format", "stream-json", "--approval-mode=yolo", "-m", self._models[req.tier]]
        if resume:
            cmd += ["--resume", req.session_id]
        session = req.session_id or ""
        parts: list[str] = []
        for ev in stream_subprocess(cmd, timeout_s=req.timeout_s, turn_key=req.turn_key, parse=parse_stream_line,
                                    on_exit=lambda rc, err, saw: [{"type": "error", "message": f"gemini exited {rc}: {err[-300:]}"}],
                                    cwd=str(ws)):
            if ev["type"] == "session":
                session = ev["session_id"]
            elif ev["type"] == "delta":
                parts.append(ev["text"])
            elif ev["type"] == "done":
                ev = {"type": "done", "text": "".join(parts), "session_id": session}
            yield ev
```

- [ ] **Step 4: Run tests and ruff**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/llm-providers && .venv/bin/python -m pytest tests/test_llm_providers_gemini_chat.py tests/test_llm_providers_gemini.py -q -p no:cacheprovider && .venv/bin/python -m ruff check ghostbrain/llm/providers`
Expected: PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/llm/providers/gemini_cli.py tests/fixtures/llm/gemini-stream.jsonl tests/test_llm_providers_gemini_chat.py
git commit -m "feat(llm): Gemini chat driver with a per-turn workspace settings file carrying the vault MCP server"
```

---

### Task 10: Doctor `llm-provider` check (replaces `claude-cli`) and skill updates

**Files:**
- Modify: `ghostbrain/doctor/checks_app.py` (replace `check_claude_cli` with `check_llm_provider`, same registration slot), `tests/test_doctor_app_checks.py`, `.claude/skills/poltergeist-setup/checks.md`, `.claude/skills/poltergeist-setup/SKILL.md`
- Test: `tests/test_doctor_app_checks.py` (replace the `claude-cli` tests)

**Interfaces:**
- Consumes: `ghostbrain.llm.providers.get_provider()`, `load_llm_config()`, `Provider.probe()`.
- Produces: check id `llm-provider` registered where `claude-cli` was (between `contexts` and `scheduler`). `ok` summary `"<provider>: <probe.reason> — fast=<m> balanced=<m> quality=<m>"`, data `{"provider", "models", "probe": probe.detail}`. `fail` when the probe is not ok, `fix` manual: Claude → `npm install -g @anthropic-ai/claude-code && claude login`; Codex → `npm i -g @openai/codex && codex login`; Gemini → `npm i -g @google/gemini-cli` then sign in; openai_http → `Settings → AI provider → set the base URL and pick a model for each tier`. A `config.yaml` naming an unknown provider → `fail` with fix `edit llm.provider in 90-meta/config.yaml (claude | codex | gemini | openai_http)`.
- The check id `claude-cli` is removed from the contract list in the plan header of `2026-09-11-setup-doctor.md`'s successors; `checks.md` and `SKILL.md` step 3 mention the new id.

- [ ] **Step 1: Write the failing tests** — in `tests/test_doctor_app_checks.py`, delete `test_claude_cli` and add:

```python
def test_llm_provider_ok_reports_models(monkeypatch):
    from ghostbrain.llm.providers import base

    class Fake:
        id = "codex"
        def models(self): return {"fast": "gpt-5-mini", "balanced": "gpt-5", "quality": "gpt-5"}
        def probe(self): return base.ProviderProbe(True, "logged in", {"binary": "/c"})
    monkeypatch.setattr(ca, "_llm_provider", lambda: Fake())
    r = ca.check_llm_provider()
    assert r.status == "ok" and r.summary.startswith("codex: logged in") and "fast=gpt-5-mini" in r.summary
    assert r.data["provider"] == "codex"


def test_llm_provider_fail_names_the_login_fix(monkeypatch):
    from ghostbrain.llm.providers import base

    class Fake:
        id = "gemini"
        def models(self): return {}
        def probe(self): return base.ProviderProbe(False, "gemini is not signed in")
    monkeypatch.setattr(ca, "_llm_provider", lambda: Fake())
    r = ca.check_llm_provider()
    assert r.status == "fail" and r.fix.kind == "manual" and "gemini-cli" in r.fix.command


def test_llm_provider_unknown_config_is_fail(monkeypatch):
    from ghostbrain.llm.client import LLMError
    def boom():
        raise LLMError("llm.provider 'bard' is not one of claude, codex, gemini, openai_http")
    monkeypatch.setattr(ca, "_llm_provider", boom)
    r = ca.check_llm_provider()
    assert r.status == "fail" and "llm.provider" in r.fix.command


def test_registration_replaced_claude_cli():
    from ghostbrain import doctor
    ids = [i for i, _ in doctor.CHECKS]
    assert "claude-cli" not in ids
    assert ids.index("llm-provider") == ids.index("contexts") + 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_doctor_app_checks.py -q -p no:cacheprovider`
Expected: FAIL (`check_llm_provider` missing).

- [ ] **Step 3: Implement** — in `checks_app.py` replace `_claude_version` + `check_claude_cli` with:

```python
_LOGIN_FIX = {
    "claude": "npm install -g @anthropic-ai/claude-code && claude login",
    "codex": "npm i -g @openai/codex && codex login",
    "gemini": "npm i -g @google/gemini-cli, run `gemini` once and choose Login with Google",
    "openai_http": "Settings → AI provider → set the base URL and pick a model for each tier",
}


def _llm_provider():
    from ghostbrain.llm.providers import get_provider
    return get_provider()


@register("llm-provider")
def check_llm_provider() -> CheckResult:
    from ghostbrain.llm.client import LLMError

    try:
        provider = _llm_provider()
    except LLMError as e:
        return CheckResult(id="llm-provider", status="fail", summary=str(e),
                           fix=Fix(kind="manual", command="edit llm.provider in 90-meta/config.yaml (claude | codex | gemini | openai_http)"))
    probe = provider.probe()
    models = provider.models()
    tiers = " ".join(f"{t}={models.get(t, '?')}" for t in ("fast", "balanced", "quality"))
    data = {"provider": provider.id, "models": models, "probe": probe.detail}
    if not probe.ok:
        return CheckResult(id="llm-provider", status="fail", summary=f"{provider.id}: {probe.reason}",
                           detail="Every routing, extraction, digest and chat call goes through this provider.",
                           fix=Fix(kind="manual", command=_LOGIN_FIX[provider.id]), data=data)
    return CheckResult(id="llm-provider", status="ok", summary=f"{provider.id}: {probe.reason} — {tiers}", data=data)
```

Update `checks.md`: replace the `claude-cli` paragraph with `llm-provider` (what each provider needs, the fix per provider, what to say if it fails twice: paste the probe reason and `llm.provider` from config.yaml). Update `SKILL.md` step 2/3: after rendering the table, if `llm-provider` failed, ask which provider the user actually has (Claude Code, ChatGPT/Codex, Gemini, or a local Ollama/LM Studio) and, if it differs from `data.provider`, tell them to switch it in Settings → AI provider (or `llm.provider` in `90-meta/config.yaml`) before continuing. Also grep the repo for `claude-cli` (`grep -rn "claude-cli" ghostbrain .claude docs README.md`) and update every remaining reference (the spec's catalog table for the doctor may stay historical; the skill and any doc must not).

- [ ] **Step 4: Run tests and ruff**

Run: `.venv/bin/python -m pytest tests/test_doctor_app_checks.py tests/test_doctor_core.py tests/test_doctor_recorder_checks.py -q -p no:cacheprovider && .venv/bin/python -m ruff check ghostbrain/doctor && grep -rn "claude-cli" .claude README.md docs/install docs/connectors.md; echo "(no output above = clean)"`
Expected: PASS, ruff clean, grep empty.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/doctor/checks_app.py tests/test_doctor_app_checks.py .claude/skills/poltergeist-setup
git commit -m "feat(doctor): llm-provider check replaces claude-cli; skill asks which provider the user has"
```

---

### Task 11: Settings API for the `llm` block, `GET /v1/llm/providers`, and 412 gating

**Files:**
- Create: `ghostbrain/api/routes/llm_providers.py`, `ghostbrain/api/tests/test_llm_settings.py`
- Modify: `ghostbrain/api/models/settings.py` (`LlmSettings`, `UpdateLlmSettings`), `ghostbrain/api/repo/settings.py` (`get_llm_settings`, `update_llm_settings`), `ghostbrain/api/routes/settings.py` (`GET/PUT /v1/settings/llm`), `ghostbrain/api/main.py` (include router), `ghostbrain/api/repo/answer.py` + `ghostbrain/api/repo/chat.py` (probe gate)

**Interfaces:**
- Produces:
  ```python
  class LlmSettings(BaseModel): provider: Literal["claude","codex","gemini","openai_http"]; models: dict[str, str|None]; base_url: str; api_key_env: str; effective_models: dict[str,str]
  class UpdateLlmSettings(BaseModel): provider: ... | None = None; models: dict[str, str|None] | None = None; base_url: str | None = None; api_key_env: str | None = None
  def get_llm_settings() -> dict; def update_llm_settings(**fields) -> dict     # merges into config.yaml `llm:` via the same _load_yaml/_write_yaml_atomic as recorder settings; ValueError on bad provider/tier
  GET /v1/settings/llm, PUT /v1/settings/llm (400 on ValueError)
  GET /v1/llm/providers → {"active": "<id>", "providers": {"<id>": {"ok", "reason", "detail"}}}   # probes all four; openai_http detail carries "models"
  ```
  Gating: `repo/answer.py`'s entry function and `repo/chat.py`'s turn start call `get_provider().probe()` once per request; if not ok raise a new `ProviderUnavailable(reason)` that the routes map to 412 `{"detail": reason}` (answer) / a terminal `{"type":"error","message": reason}` event (chat stream, which already yields errors as events).

- [ ] **Step 1: Write the failing tests**

```python
# ghostbrain/api/tests/test_llm_settings.py
from __future__ import annotations

from fastapi.testclient import TestClient

from ghostbrain.api.main import create_app
from ghostbrain.llm.providers import base


def _client():
    return TestClient(create_app("tok")), {"Authorization": "Bearer tok"}


def test_get_and_put_llm_settings_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    (tmp_path / "90-meta").mkdir(parents=True)
    (tmp_path / "90-meta" / "config.yaml").write_text("worker:\n  routing_mode: live\n")
    c, h = _client()
    assert c.get("/v1/settings/llm", headers=h).json()["provider"] == "claude"
    r = c.put("/v1/settings/llm", json={"provider": "openai_http", "models": {"fast": "llama3.2"}, "base_url": "http://127.0.0.1:1234/v1"}, headers=h)
    assert r.status_code == 200 and r.json()["provider"] == "openai_http" and r.json()["effective_models"]["fast"] == "llama3.2"
    text = (tmp_path / "90-meta" / "config.yaml").read_text()
    assert "provider: openai_http" in text and "routing_mode: live" in text


def test_put_rejects_unknown_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    c, h = _client()
    assert c.put("/v1/settings/llm", json={"provider": "bard"}, headers=h).status_code == 422 or 400


def test_providers_route_probes_all(monkeypatch):
    from ghostbrain.api.routes import llm_providers as route
    monkeypatch.setattr(route, "_probe_all", lambda: {"claude": base.ProviderProbe(True, "2.1.0"), "codex": base.ProviderProbe(False, "not installed"),
                                                      "gemini": base.ProviderProbe(False, "not installed"), "openai_http": base.ProviderProbe(False, "not answering", {"models": []})})
    monkeypatch.setattr(route, "_active", lambda: "claude")
    c, h = _client()
    body = c.get("/v1/llm/providers", headers=h).json()
    assert body["active"] == "claude" and body["providers"]["codex"]["ok"] is False and body["providers"]["openai_http"]["detail"]["models"] == []


def test_answer_returns_412_when_provider_unusable(monkeypatch):
    from ghostbrain.api.repo import answer as answer_repo
    from ghostbrain.api.repo.settings import ProviderUnavailable
    def gate():
        raise ProviderUnavailable("codex is not logged in; run `codex login`")
    monkeypatch.setattr(answer_repo, "require_provider", gate)
    c, h = _client()
    r = c.post("/v1/answer", json={"question": "hi"}, headers=h)
    assert r.status_code == 412 and "codex login" in r.json()["detail"]
```

(Read `ghostbrain/api/routes/answer.py` for the exact request body field names before writing the last test; adjust `{"question": ...}` to the real model.)

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest ghostbrain/api/tests/test_llm_settings.py -q -p no:cacheprovider`
Expected: FAIL (404 on `/v1/settings/llm`, import errors).

- [ ] **Step 3: Implement**

In `ghostbrain/api/models/settings.py` add `LlmProviderId = Literal["claude", "codex", "gemini", "openai_http"]`, `LlmSettings`, `UpdateLlmSettings` (fields as in Interfaces; `models` validated to keys ⊆ {fast, balanced, quality}). In `ghostbrain/api/repo/settings.py`:

```python
class ProviderUnavailable(RuntimeError):
    """Active LLM provider failed its probe; message is the user-facing reason."""


def get_llm_settings() -> dict:
    from ghostbrain.llm.providers.config import effective_models, load_llm_config
    cfg = load_llm_config(_load_yaml())
    return {"provider": cfg.provider, "models": cfg.models, "base_url": cfg.base_url,
            "api_key_env": cfg.api_key_env, "effective_models": effective_models(cfg.provider, cfg)}


def update_llm_settings(**fields) -> dict:
    from ghostbrain.llm.providers import PROVIDER_IDS
    config = _load_yaml()
    block = config.get("llm") if isinstance(config.get("llm"), dict) else {}
    if fields.get("provider") is not None:
        p = str(fields["provider"]).strip().lower()
        if p not in PROVIDER_IDS:
            raise ValueError(f"provider must be one of {', '.join(PROVIDER_IDS)}")
        block["provider"] = p
    if fields.get("models") is not None:
        models = block.get("models") if isinstance(block.get("models"), dict) else {}
        for tier, model in fields["models"].items():
            if tier not in ("fast", "balanced", "quality"):
                raise ValueError(f"unknown tier {tier!r}")
            models[tier] = (str(model).strip() or None) if model is not None else None
        block["models"] = models
    http = block.get("openai_http") if isinstance(block.get("openai_http"), dict) else {}
    if fields.get("base_url") is not None:
        http["base_url"] = str(fields["base_url"]).strip().rstrip("/")
    if fields.get("api_key_env") is not None:
        http["api_key_env"] = str(fields["api_key_env"]).strip()
    if http:
        block["openai_http"] = http
    config["llm"] = block
    _write_yaml_atomic(config)
    return get_llm_settings()


def require_provider() -> None:
    from ghostbrain.llm.client import LLMError
    from ghostbrain.llm.providers import get_provider
    try:
        probe = get_provider().probe()
    except LLMError as e:
        raise ProviderUnavailable(str(e)) from e
    if not probe.ok:
        raise ProviderUnavailable(probe.reason)
```

Routes: in `routes/settings.py` add `GET /v1/settings/llm` → `get_llm_settings()`, `PUT /v1/settings/llm` → `update_llm_settings(**payload.model_dump(exclude_none=True))` with `ValueError` → 400. New `routes/llm_providers.py`:

```python
router = APIRouter(prefix="/v1/llm", tags=["llm"])

def _probe_all() -> dict[str, ProviderProbe]:
    from ghostbrain.llm.providers import PROVIDER_IDS, get_provider
    from ghostbrain.llm.providers.config import LlmConfig, load_llm_config
    cfg = load_llm_config()
    out = {}
    for pid in PROVIDER_IDS:
        try:
            out[pid] = get_provider(LlmConfig(provider=pid, models=cfg.models, base_url=cfg.base_url, api_key_env=cfg.api_key_env)).probe()
        except LLMError as e:
            out[pid] = ProviderProbe(False, str(e))
    return out

def _active() -> str: ...   # load_llm_config().provider

@router.get("/providers")
def list_providers() -> dict:
    return {"active": _active(), "providers": {k: dataclasses.asdict(v) for k, v in _probe_all().items()}}
```

Register it in `create_app()`. In `repo/answer.py` import `require_provider` as a module-level name and call it at the top of the answer entry point; map `ProviderUnavailable` to `HTTPException(412, detail=str(e))` in `routes/answer.py`. In `repo/chat.py`, before `_stream_turn`, call `require_provider()` inside the try and on `ProviderUnavailable` yield `{"type": "error", "message": str(e)}` and return. Also pass `history=[{"role": m["role"], "text": m["text"]} for m in conv["messages"][-HISTORY_FALLBACK_MESSAGES-1:-1]]` into the turn so the local driver has context — add a `history` parameter to `agent.run_chat_turn` (default None) forwarded into `ChatRequest`.

- [ ] **Step 4: Run tests and ruff**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/llm-providers && .venv/bin/python -m pytest ghostbrain/api/tests/test_llm_settings.py ghostbrain/api/tests/test_chat.py ghostbrain/api/tests/test_routes_llm_run.py ghostbrain/api/tests -q -p no:cacheprovider --deselect ghostbrain/api/tests/test_recorder_capture_settings.py && .venv/bin/python -m ruff check ghostbrain/api/routes/llm_providers.py ghostbrain/api/repo/settings.py ghostbrain/api/models/settings.py`
Expected: PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api ghostbrain/llm/agent.py
git commit -m "feat(api): llm settings endpoints, GET /v1/llm/providers, and 412 gating when the provider is unusable"
```

---

### Task 12: Desktop — AI provider settings panel and chat header

**Files:**
- Modify: `desktop/src/shared/types.ts` (`LlmProvider = 'claude' | 'codex' | 'gemini' | 'local'`), `desktop/src/shared/settings-schema.ts`, `desktop/src/main/settings.ts` (default `'claude'`; migrate stored `'anthropic'→'claude'`, `'openai'→'codex'` on load), `desktop/src/renderer/stores/settings.ts`, `desktop/src/shared/api-types.ts` (`LlmSettings`, `LlmProvidersResponse`), `desktop/src/renderer/lib/api/hooks.ts` (`useLlmSettings`, `useUpdateLlmSettings`, `useLlmProviders`), `desktop/src/renderer/screens/settings.tsx` (move the dropdown out of Privacy into a new "AI provider" section), `desktop/src/renderer/screens/chat.tsx` (active provider label in the header)
- Create: `desktop/src/renderer/components/ProviderSwitcher.tsx`
- Test: `desktop/src/main/__tests__/settings-migration.test.ts`, `desktop/src/renderer/__tests__/AiProviderSettings.test.tsx`

**Interfaces:**
- API mapping: renderer `'local'` ↔ sidecar `'openai_http'` (one helper `toSidecarProvider`/`fromSidecarProvider` in `desktop/src/shared/llm-provider.ts`).
- Hooks: `useLlmSettings()` → `GET /v1/settings/llm`; `useUpdateLlmSettings()` → `PUT /v1/settings/llm` then invalidates both queries and mirrors `provider` into the desktop settings store; `useLlmProviders()` → `GET /v1/llm/providers` (staleTime 30 s, manual refetch via a "re-check" button).
- Panel behavior: dropdown of the four providers; a diagnostics row showing `providers[active].reason` in green/red with "re-check"; when `local` is selected: a base URL input (saved on blur) and three selects (fast/balanced/quality) whose options are `providers.openai_http.detail.models` (free-text fallback when the list is empty).
- Chat header switcher: a shared `ProviderSwitcher` component (`desktop/src/renderer/components/ProviderSwitcher.tsx`) used in the chat header and reused by the settings panel. It renders a `<select aria-label="provider">` with all four providers; providers whose probe is not ok are `disabled` and their option label carries the reason (`codex — not installed`); the current value is `active`; changing it calls `useUpdateLlmSettings` and, until the queries refetch, shows the pending provider. The chat screen keeps its existing behavior otherwise; a turn started after a switch uses the new provider (conversations keep their transcript, so a Claude session id is simply ignored by another driver and history is replayed).

- [ ] **Step 1: Write the failing tests**

```ts
// desktop/src/main/__tests__/settings-migration.test.ts
import { describe, expect, it, vi } from 'vitest';
vi.mock('electron', () => ({ app: { getPath: () => '/tmp/ghostbrain-desktop-test' } }));
import { DEFAULT_SETTINGS, migrateLlmProvider } from '../settings';

describe('llm provider setting', () => {
  it('defaults to claude', () => { expect(DEFAULT_SETTINGS.llmProvider).toBe('claude'); });
  it('migrates legacy values', () => {
    expect(migrateLlmProvider('anthropic')).toBe('claude');
    expect(migrateLlmProvider('openai')).toBe('codex');
    expect(migrateLlmProvider('local')).toBe('local');
    expect(migrateLlmProvider('gemini')).toBe('gemini');
    expect(migrateLlmProvider('garbage')).toBe('claude');
  });
});
```

```tsx
// desktop/src/renderer/__tests__/AiProviderSettings.test.tsx
// Copy the render + window.gb.api.request mock setup from SearchIndexSettings.test.tsx verbatim, then:
import { screen, fireEvent, waitFor } from '@testing-library/react';

it('shows the active provider diagnostics and lets the user switch to local with model pickers', async () => {
  // request mock: GET /v1/settings/llm → { provider: 'claude', models: {fast:null,balanced:null,quality:null}, base_url: 'http://127.0.0.1:11434/v1', api_key_env: 'OPENAI_API_KEY', effective_models: {...} }
  // GET /v1/llm/providers → { active: 'claude', providers: { claude: {ok:true, reason:'2.1.0', detail:{}}, codex: {ok:false, reason:'not installed', detail:{}}, gemini: {...}, openai_http: {ok:false, reason:'not answering', detail:{models:['llama3.2','qwen3']}} } }
  // PUT /v1/settings/llm → echo merged
  renderAiProviderSettings();
  expect(await screen.findByText(/2\.1\.0/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText(/provider/i), { target: { value: 'local' } });
  await waitFor(() => expect(requestMock).toHaveBeenCalledWith(expect.objectContaining({ method: 'PUT', path: '/v1/settings/llm', body: { provider: 'openai_http' } })));
  expect(await screen.findByLabelText(/fast model/i)).toBeInTheDocument();
  expect(screen.getAllByRole('option', { name: 'qwen3' }).length).toBeGreaterThan(0);
});

it('the switcher disables providers whose probe failed and shows the reason', async () => {
  // same request mock as above
  renderProviderSwitcher();   // render <ProviderSwitcher /> with the same providers/QueryClient wrapper
  const codex = await screen.findByRole('option', { name: /codex — not installed/ });
  expect(codex).toBeDisabled();
  expect(screen.getByRole('option', { name: /claude/ })).not.toBeDisabled();
  fireEvent.change(screen.getByLabelText(/provider/i), { target: { value: 'gemini' } });
  // gemini is disabled in the mock, so no PUT must be sent
  expect(requestMock).not.toHaveBeenCalledWith(expect.objectContaining({ method: 'PUT', path: '/v1/settings/llm', body: { provider: 'gemini' } }));
});
```

(Match the real shape of the `window.gb.api.request` mock in `SearchIndexSettings.test.tsx`; the `expect.objectContaining` above assumes `{method, path, body}` — adjust to the real call signature.)

- [ ] **Step 2: Run to verify they fail**

Run: `cd desktop && npx vitest run src/main/__tests__/settings-migration.test.ts src/renderer/__tests__/AiProviderSettings.test.tsx`
Expected: FAIL (`migrateLlmProvider` not exported; component missing).

- [ ] **Step 3: Implement**

- `desktop/src/shared/types.ts`: `export type LlmProvider = 'claude' | 'codex' | 'gemini' | 'local';` and in `settings-schema.ts` `llmProvider: z.enum(['claude', 'codex', 'gemini', 'local'])`.
- `desktop/src/shared/llm-provider.ts`: `toSidecarProvider(p)` (`local → 'openai_http'`, else identity) and `fromSidecarProvider(id)` (`'openai_http' → 'local'`).
- `desktop/src/main/settings.ts`: `DEFAULT_SETTINGS.llmProvider = 'claude'`; `export function migrateLlmProvider(v: unknown): LlmProvider` (`anthropic→claude`, `openai→codex`, valid values pass, anything else `claude`); apply it in `getAll()` when reading the stored object before schema validation.
- `desktop/src/shared/api-types.ts`: `LlmSettings { provider: SidecarProviderId; models: Record<'fast'|'balanced'|'quality', string|null>; base_url: string; api_key_env: string; effective_models: Record<string,string> }`, `LlmProvidersResponse { active: SidecarProviderId; providers: Record<SidecarProviderId, { ok: boolean; reason: string; detail: { models?: string[] } & Record<string, unknown> }> }`.
- `hooks.ts`: the three hooks following the `useRecorderSettings`/`useUpdateRecorderSettings` pattern (`queryKey: ['settings','llm']`, `['llm','providers']`).
- `settings.tsx`: new `AiProviderSettings` section (rendered above Privacy) with `SectionHeader title="AI provider"`, the provider `<select aria-label="provider">`, a diagnostics `SettingRow` (reason text, green when ok, red otherwise, "re-check" button calling `refetch()`), and when `provider === 'local'`: a base URL text input (`aria-label="base URL"`, saves on blur) and three `<select aria-label="fast model">`… populated from `providers.openai_http.detail.models`, each change calling `useUpdateLlmSettings` with `{ models: { [tier]: value } }`. Remove the old "LLM provider" row from Privacy. On a successful provider change also call `setSetting('llmProvider', fromSidecarProvider(provider))`.
- `desktop/src/renderer/components/ProviderSwitcher.tsx`: the component above (props: none; it owns the two hooks). `chat.tsx`: mount `<ProviderSwitcher />` in the header next to the conversation title. `settings.tsx`: the AI-provider section uses the same component for its dropdown.

- [ ] **Step 4: Run gates**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/llm-providers/desktop && npm test && npm run typecheck && npm run lint`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/llm-providers
git add desktop/src
git commit -m "feat(desktop): AI provider settings panel with diagnostics and local model pickers; chat shows the active provider"
```

---

### Task 13: Docs, real fixtures, acceptance, release 1.6.0

**Files:**
- Create: `docs/llm-providers.md`
- Modify: `README.md` (one paragraph under "Why Poltergeist" → "Your existing Claude subscription powers it" becomes "Your existing Claude, ChatGPT, or Gemini subscription — or a local model — powers it", linking the new doc), `tests/fixtures/llm/*` (replace the documented-format fixtures with real captures), `.release-please-manifest.json` / `desktop/package.json` / `desktop/CHANGELOG.md` via `scripts/release.sh`

- [ ] **Step 1: Write `docs/llm-providers.md`** — sections: "Pick a provider" (the `llm:` block with all keys explained, the tier table from the spec, the alias synonyms), one section per provider (install, sign in, what the doctor checks, limitations: Codex no images and no token streaming, Gemini best-effort JSON, local needs three models set and vault tools run in-process), "Chat and vault tools" (how each provider reaches the MCP server; the generated `~/ghostbrain/run/llm/{codex,gemini}` configs; that `~/.codex`/`~/.gemini` are never edited), "Troubleshooting" (`poltergeist doctor` → `llm-provider` row; the 412 message on chat/answer).

- [ ] **Step 2: Replace the fixtures with real captures** — on a machine with the CLI signed in: `codex exec --json --skip-git-repo-check --ephemeral -m gpt-5-mini "reply with the JSON {\"ok\": true}" > tests/fixtures/llm/codex-exec-message.jsonl`; a chat turn against the vault MCP server captured the same way into `codex-exec-chat.jsonl`; `gemini -p "reply with {\"ok\": true}" --output-format json > gemini-json.json` and a `--output-format stream-json` turn with a tool call into `gemini-stream.jsonl`. Redact any account identifiers. Re-run `tests/test_llm_providers_codex*.py tests/test_llm_providers_gemini*.py`; if a field name differs from the documented shape, fix the parser (not the fixture) and note it in the commit body. If no such machine is available, keep the documented-format fixtures and say so in the release notes.

- [ ] **Step 3: Manual acceptance per provider** — for each of Claude, Codex, Gemini, local (Ollama with `qwen3`): set `llm.provider`, run `poltergeist doctor` (llm-provider ✔), run one batch extraction (`ghostbrain-api worker` on a queued event, or `/v1/answer`), and one desktop chat turn that triggers `poltergeist_search`. Record the four results (pass/fail + notes) in the PR description.

- [ ] **Step 4: Full gates**

Run: `cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/llm-providers && .venv/bin/python -m pytest -q -p no:cacheprovider --ignore=tests/test_recorder_wasapi_io.py --deselect ghostbrain/api/tests/test_recorder_capture_settings.py; cd desktop && npm test && npm run typecheck && npm run lint`
Expected: only the known pre-existing failures (numpy/WASAPI, semantic, calendar jxa, joplin, mcp_*, weekly_digest, agent_stream); desktop green. Add the new `tests/test_llm_providers_*.py` files and `ghostbrain/api/tests/test_llm_settings.py` to the CI backend job's pytest list in `.github/workflows/ci.yml`.

- [ ] **Step 5: PR, merge, release**

```bash
git push -u origin feat/llm-providers
gh auth switch -u nikrich
gh pr create --base main --title "feat: LLM providers — Codex CLI, Gemini CLI, and local OpenAI-compatible models alongside Claude" --body-file docs/superpowers/specs/2026-09-14-llm-providers-design.md
gh pr checks --watch
```

After the checks pass and the user confirms: `gh pr merge --merge`, then on a clean `main` checkout `scripts/release.sh 1.6.0`, review, `git push origin HEAD:main`, watch the release run, and run the post-release check from the setup-doctor plan (download the mac zip, `ghostbrain-api doctor` from the bundle must render the `llm-provider` row).
