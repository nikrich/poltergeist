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

# Module import (not `from ... import stream_subprocess as _`) so tests can monkeypatch gm.stream_subprocess.
from ghostbrain.llm.providers.stream import stream_subprocess

log = logging.getLogger("ghostbrain.llm.providers.gemini")
SCHEMA_INSTRUCTION = "Respond with JSON matching this schema, and nothing else:\n{schema}"
STRICT_INSTRUCTION = "Output ONLY the JSON object — no prose, no markdown fences, no explanation.\n"
VAULT_TOOL_NAMES = ["poltergeist_search", "poltergeist_get_note", "poltergeist_ask", "poltergeist_write_doc"]
_resume_cache: dict[str, bool] = {}


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
    """Seam: (stdout, stderr, returncode). Own process group so a hung CLI can be killed."""
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


def _run_root() -> Path:
    from ghostbrain.api.runtime import run_dir
    return run_dir() / "llm"


def supports_resume(binary: str) -> bool:
    """Whether this `gemini` binary's CLI supports `--resume <session_id>`.

    Routed through the file's `_run` seam (own process group, killed on
    timeout) rather than a bare `subprocess.run` — a hung `gemini --help`
    must not be left running. Cached per binary path — `gemini --help` is a
    real subprocess spawn, so checking it once per turn would be wasteful;
    older CLIs that lack the flag default to False on any failure (missing
    binary, timeout, non-zero exit, etc.).
    """
    if binary not in _resume_cache:
        try:
            out, _err, _rc = _run([binary, "--help"], 10)
        except (LLMError, OSError):
            out = ""
        _resume_cache[binary] = "--resume" in out
    return _resume_cache[binary]


def write_gemini_workspace(root: Path, *, mcp_argv: list[str], user_servers: list[dict], auth_type: str | None) -> Path:
    """Regenerate a per-turn workspace (`root/.gemini/settings.json`) fresh each turn.

    Never writes into the user's real ~/.gemini — root is a run-dir scratch
    directory dedicated to this provider; `chat()` runs `gemini` with this
    root as `cwd` so the CLI picks up the workspace settings file.
    """
    (root / ".gemini").mkdir(parents=True, exist_ok=True)
    servers: dict[str, dict] = {}
    for s in user_servers:
        entry: dict = {"command": s["command"], "args": list(s.get("args") or []), "trust": True}
        if s.get("env"):
            entry["env"] = dict(s["env"])
        if s.get("tools"):
            entry["includeTools"] = [t.strip() for t in s["tools"].split(",") if t.strip()]
        servers[s["name"]] = entry
    servers["poltergeist"] = {"command": mcp_argv[0], "args": list(mcp_argv[1:]), "trust": True,
                              "includeTools": list(VAULT_TOOL_NAMES)}
    # Disable every built-in gemini tool (run_shell_command, write_file,
    # read_file, web_fetch, …): chat() runs with --approval-mode=yolo, which
    # auto-approves whatever is exposed, and a second brain has no business
    # holding a shell. Only the MCP servers above survive. Written under BOTH
    # keys — current CLIs read the nested `tools.core`, older ones only the
    # flat `coreTools` — so the restriction holds whichever is installed.
    doc: dict = {"mcpServers": servers, "tools": {"core": []}, "coreTools": []}
    if auth_type:
        doc["security"] = {"auth": {"selectedType": auth_type}}
    (root / ".gemini" / "settings.json").write_text(json.dumps(doc, indent=2))
    return root


def parse_stream_line(line: str) -> list[dict]:
    """One stdout line from `gemini --output-format stream-json` → zero or more
    renderer events, matching the vocabulary in ghostbrain/llm/agent.py exactly:
      {"type": "session", "session_id"}      — CLI turn started (from `init`)
      {"type": "delta", "text"}              — streamed assistant text
      {"type": "tool", "name", "summary"}    — tool call started
      {"type": "done", "text", "session_id"} — terminal success (text/session_id filled in by chat())
      {"type": "error", "message"}           — terminal failure

    Stateless: no per-turn state lives here (session id is threaded through
    by GeminiCli.chat()'s local `session` variable, same as the codex driver).
    """
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
        return [{"type": "tool", "name": vault_tools.short_name_for(name),
                 "summary": vault_tools.summary_for(name, ev.get("parameters") or {})}]
    if t == "message" and ev.get("role") == "assistant" and ev.get("content"):
        return [{"type": "delta", "text": str(ev["content"])}]
    if t == "result":
        if ev.get("status") not in (None, "success"):
            return [{"type": "error", "message": str(ev.get("error") or ev.get("status"))}]
        return [{"type": "done", "text": "", "session_id": ""}]
    if t == "error":
        return [{"type": "error", "message": str(ev.get("message") or "gemini error")}]
    return []


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
            raise LLMError("`gemini` CLI not found; install it (`npm install -g @google/gemini-cli`) and sign in, or set GHOSTBRAIN_GEMINI_BIN")
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
                structured = _parse_json_tolerant(text)  # raises LLMError if still not JSON
        if not text.strip():
            raise LLMError("gemini returned an empty response")
        return LLMResult(text=text, structured=structured, model=self._models[req.tier], cost_usd=0.0,
                         duration_ms=int((time.monotonic() - started) * 1000), session_id="", raw=doc)

    def probe(self) -> base.ProviderProbe:
        b = self._binary or find_gemini_binary()
        if b is None:
            return base.ProviderProbe(False, "`gemini` CLI not found; install with `npm install -g @google/gemini-cli`, then sign in (`gemini` then `/auth`)")
        auth = read_gemini_auth()
        if auth is None:
            return base.ProviderProbe(False, "gemini is not signed in; run `gemini` then `/auth` (or set GEMINI_API_KEY)", {"binary": b})
        try:
            _run([b, "--version"], 15)
        except (LLMError, OSError) as e:
            return base.ProviderProbe(False, f"gemini --version failed: {e}", {"binary": b, "auth": auth})
        return base.ProviderProbe(True, f"gemini ({auth})", {"binary": b, "auth": auth, "models": self.models()})

    def chat(self, req: base.ChatRequest) -> Iterator[dict]:
        from ghostbrain.llm.agent import CHAT_SYSTEM_PROMPT, find_mcp_binary
        b = self._binary or find_gemini_binary()
        if b is None:
            yield {"type": "error", "message": "`gemini` CLI not found; install it and sign in"}
            return
        mcp = find_mcp_binary()
        if mcp is None:
            yield {"type": "error", "message": "Vault tools are unavailable: the ghostbrain-api mcp helper could not be found"}
            return
        auth = read_gemini_auth()
        if auth is None:
            yield {"type": "error", "message": "gemini is not signed in — run `gemini` and use /auth, or set GEMINI_API_KEY"}
            return
        ws = write_gemini_workspace(_run_root() / "gemini", mcp_argv=list(mcp), user_servers=req.user_servers,
                                    auth_type=auth)
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
