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
        if not text.strip():
            raise LLMError("codex returned no output (no agent_message in the exec event stream)")
        structured = _parse_json_tolerant(text) if req.json_schema is not None else None
        return LLMResult(text=text, structured=structured, model=self._models[req.tier], cost_usd=0.0,
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
        return base.ProviderProbe(True, last_line, {"binary": b, "models": self.models()})

    def chat(self, req: base.ChatRequest) -> Iterator[dict]:
        raise LLMError("codex chat lands in Task 7")
