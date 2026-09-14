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
        raise LLMError("gemini chat lands in Task 9")
