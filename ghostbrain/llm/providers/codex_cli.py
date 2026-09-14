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

from ghostbrain.llm import agent
from ghostbrain.llm.agent import CHAT_SYSTEM_PROMPT, find_mcp_binary
from ghostbrain.llm.client import LLMError, LLMResult, LLMTimeout, _parse_json_tolerant
from ghostbrain.llm.providers import base, vault_tools

# Module import (not `from ... import stream_subprocess as _`) so tests can monkeypatch cx.stream_subprocess.
from ghostbrain.llm.providers.stream import stream_subprocess

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


def _run_root() -> Path:
    from ghostbrain.api.runtime import run_dir
    return run_dir() / "llm"


def _real_codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))


def _toml_str(s: str) -> str:
    # JSON string escaping is valid TOML basic-string escaping for our values,
    # EXCEPT json.dumps' default ensure_ascii=True emits \uXXXX surrogate-pair
    # escapes for non-BMP characters (e.g. emoji) that tomllib's TOML parser
    # rejects as "not a Unicode scalar value" — TOML basic strings accept raw
    # unicode directly, so keep it unescaped and only quote/backslash/control
    # chars get escaped.
    return json.dumps(s, ensure_ascii=False)


REASONING_EFFORT = {"fast": "low", "balanced": "medium", "quality": "high"}


def _error_message(stderr_tail: str, fallback: str) -> str:
    """Pull `error.message` out of a JSON error line codex printed, else the fallback.

    codex reports API rejections as one JSON object on stderr/stdout
    (`{"type":"error","status":400,"error":{"type":..,"message":..}}`); the
    user should see the sentence, not the envelope.
    """
    for line in reversed(stderr_tail.strip().splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = ((ev.get("error") or {}).get("message")) or ev.get("message")
        if msg:
            return str(msg)
    return fallback


def write_codex_home(root: Path, *, model: str | None, mcp_argv: list[str], user_servers: list[dict], real_home: Path,
                     reasoning_effort: str | None = None, enabled_tools: list[str] | None = None) -> Path:
    """Regenerate an isolated CODEX_HOME (config.toml + auth.json symlink) fresh each turn.

    Never writes into the user's real ~/.codex — root is a run-dir scratch
    directory dedicated to this provider.

    ``enabled_tools`` is codex's per-server allowlist (the counterpart of
    gemini's ``includeTools``); it carries ``ChatRequest.allowed_tools`` so
    docs-assist runs without poltergeist_ask on codex too.
    """
    root.mkdir(parents=True, exist_ok=True)
    lines = []
    if model:
        lines.append(f"model = {_toml_str(model)}")
    if reasoning_effort:
        lines.append(f"model_reasoning_effort = {_toml_str(reasoning_effort)}")
    lines += ['sandbox_mode = "read-only"', 'approval_policy = "never"', ""]
    # approval_policy = "never" makes codex DENY (not skip) any MCP tool call
    # that would normally prompt; "approve" pre-approves the server's tools
    # (valid modes: auto, prompt, writes, approve). enabled_tools is the
    # per-server allowlist that carries ChatRequest.allowed_tools.
    lines += ["[mcp_servers.poltergeist]", f"command = {_toml_str(mcp_argv[0])}",
              "args = [" + ", ".join(_toml_str(a) for a in mcp_argv[1:]) + "]", "required = true",
              'default_tools_approval_mode = "approve"']
    if enabled_tools is not None:
        lines.append("enabled_tools = [" + ", ".join(_toml_str(t) for t in enabled_tools) + "]")
    lines.append("")
    for s in user_servers:
        lines += [f"[mcp_servers.{s['name']}]", f"command = {_toml_str(s['command'])}",
                  'default_tools_approval_mode = "approve"',
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


class CodexChatParser:
    """Stateful `codex exec --json` line parser for one chat turn.

    `thread_id` is recorded from the `thread.started` event and stamped onto
    the terminal `done` event's `session_id` — state that must live per turn,
    not on the module, so two chat turns running concurrently (two
    subprocesses, each fed through its own `stream_subprocess` generator)
    never see each other's thread id. `CodexCli.chat()` constructs a fresh
    instance per turn and passes `.feed` as the `parse` callable.
    """

    def __init__(self) -> None:
        self.thread_id = ""

    def feed(self, line: str) -> list[dict]:
        line = line.strip()
        if not line:
            return []
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            return []
        t, item = ev.get("type"), ev.get("item") or {}
        if t == "thread.started":
            self.thread_id = str(ev.get("thread_id") or "")
            return [{"type": "session", "session_id": self.thread_id}]
        if t == "item.started" and item.get("type") == "mcp_tool_call":
            name = str(item.get("tool") or "")
            return [{"type": "tool", "name": vault_tools.short_name_for(name),
                     "summary": vault_tools.summary_for(name, item.get("arguments") or {})}]
        if t == "item.completed" and item.get("type") == "agent_message":
            return [{"type": "delta", "text": str(item.get("text") or "")}]
        if t == "turn.completed":
            return [{"type": "done", "text": "", "session_id": self.thread_id}]
        if t in ("turn.failed", "error"):
            return [{"type": "error", "message": str(((ev.get("error") or {}).get("message")) or ev.get("message") or "codex turn failed")}]
        return []


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
        cmd = [self._bin(), "exec", "--json", "--sandbox", "read-only", "--skip-git-repo-check", "--ephemeral"]
        model = self._models.get(req.tier)
        if model:
            cmd += ["-m", model]
        cmd += ["-c", f'model_reasoning_effort="{REASONING_EFFORT[req.tier]}"']
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
            raise LLMError(f"codex exec failed: {error or _error_message(err, err.strip()[-500:] or f'exit {rc}')}")
        if not text.strip():
            raise LLMError("codex returned no output (no agent_message in the exec event stream)")
        structured = _parse_json_tolerant(text) if req.json_schema is not None else None
        return LLMResult(text=text, structured=structured, model=self._models.get(req.tier) or "codex-default",
                         cost_usd=0.0,
                         duration_ms=int((time.monotonic() - started) * 1000), session_id=thread or "", raw={"cmd": cmd})

    def probe(self) -> base.ProviderProbe:
        b = self._binary or find_codex_binary()
        if b is None:
            return base.ProviderProbe(False, "`codex` CLI not found; install with `npm i -g @openai/codex`, then `codex login`")
        try:
            out, err, rc = _run([b, "login", "status"], None, 15)
        except (LLMError, OSError) as e:
            return base.ProviderProbe(False, f"codex login status failed: {e}", {"binary": b})
        if rc != 0:
            return base.ProviderProbe(False, "codex is not logged in; run `codex login` (ChatGPT account)", {"binary": b, "stderr": err[-300:]})
        lines = out.strip().splitlines()
        last_line = lines[-1] if lines else "logged in"
        return base.ProviderProbe(True, last_line, {"binary": b, "tiers": self.models()})

    def chat(self, req: base.ChatRequest) -> Iterator[dict]:
        b = self._binary or find_codex_binary()
        if b is None:
            yield {"type": "error", "message": "`codex` CLI not found; install it (`npm i -g @openai/codex`) and run `codex login`"}
            return
        mcp = find_mcp_binary()
        if mcp is None:
            yield {"type": "error", "message": "Vault tools are unavailable: the ghostbrain-api mcp helper could not be found"}
            return
        home = write_codex_home(_run_root() / "codex", model=self._models.get(req.tier), mcp_argv=list(mcp),
                                user_servers=req.user_servers, real_home=_real_codex_home(),
                                reasoning_effort=REASONING_EFFORT.get(req.tier),
                                enabled_tools=(vault_tools.allowed_vault_tool_names(req.allowed_tools)
                                               if req.allowed_tools else None))
        cmd = [b, "exec"]
        if req.session_id:
            cmd += ["resume", req.session_id]
        cmd += ["--json", "--skip-git-repo-check", "-"]
        stdin = f"<instructions>\n{req.system_prompt or CHAT_SYSTEM_PROMPT}\n</instructions>\n\n{req.prompt}"
        session = req.session_id or ""
        text_parts: list[str] = []
        parser = CodexChatParser()

        def _on_exit(rc: int, err: str, saw_any: bool) -> list[dict]:
            # A rejected `exec resume <id>` exits non-zero having streamed
            # nothing. Raise (same contract as the Claude driver) so
            # repo/chat.py retries the turn fresh instead of dead-ending the
            # conversation on a stale thread id.
            if req.session_id and not saw_any and rc != 0:
                raise agent.ResumeFailed(err[-300:] or "resume failed")
            # codex can exit 0 after its agent_message without ever emitting
            # turn.completed. The reply is already in hand — hand it over
            # rather than replacing it with an empty "codex exited 0: ".
            if rc == 0 and text_parts:
                return [{"type": "done", "text": "".join(text_parts), "session_id": session}]
            return [{"type": "error", "message": _error_message(err, f"codex exited {rc}: {err[-300:]}")}]

        for ev in stream_subprocess(cmd, timeout_s=req.timeout_s, turn_key=req.turn_key, parse=parser.feed,
                                    on_exit=_on_exit,
                                    env={"CODEX_HOME": str(home)}, stdin_text=stdin):
            if ev["type"] == "session":
                session = ev["session_id"]
            elif ev["type"] == "delta":
                text_parts.append(ev["text"])
            elif ev["type"] == "done":
                ev = {"type": "done", "text": "".join(text_parts), "session_id": session}
            yield ev
