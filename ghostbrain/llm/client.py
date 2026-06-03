"""Thin wrapper around `claude -p` for programmatic LLM calls.

Why subprocess: Jannik runs on Claude Max (OAuth). The Anthropic SDK requires
an API key. Shelling out to the local `claude` binary inherits the OAuth
session — calls bill against Max quota.

Cost-shaping: by default `claude` injects the global CLAUDE.md, all skills,
auto-memory, etc. into every call (~35k tokens of system prompt). We strip
that with ``--system-prompt`` so each call is just our prompt.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("ghostbrain.llm.client")

DEFAULT_TIMEOUT_S = 120
DEFAULT_BUDGET_USD = 0.50  # safety cap per call; raise via env if needed
DEFAULT_MODEL = "haiku"
RETRY_DELAYS_S = (5, 30, 120)


def _find_claude_binary() -> str | None:
    """Locate the `claude` CLI, tolerant of the stripped PATH macOS hands
    Finder/Spotlight-launched apps.

    Lookup order:
    1. ``GHOSTBRAIN_CLAUDE_BIN`` — explicit override for non-standard installs.
    2. ``shutil.which("claude")`` — honors PATH when it's been augmented.
    3. Well-known install locations checked in order — the desktop sidecar
       inherits a bare ``/usr/bin:/bin:/usr/sbin:/sbin`` from launchd when
       the app is opened from Finder, so a regular PATH search misses
       claude even when it's installed.
    """
    override = os.environ.get("GHOSTBRAIN_CLAUDE_BIN")
    if override and Path(override).is_file():
        return override

    found = shutil.which("claude")
    if found:
        return found

    home = Path.home()
    candidates = (
        home / ".local" / "bin" / "claude",
        Path("/opt/homebrew/bin/claude"),
        Path("/usr/local/bin/claude"),
        home / ".claude" / "bin" / "claude",
    )
    for c in candidates:
        if c.is_file():
            return str(c)
    return None

MINIMAL_SYSTEM_PROMPT = (
    "You are an automation backend, not a chat assistant. The user's prompts "
    "are machine-generated and your output is parsed programmatically. "
    "RULES:\n"
    "1. Never include conversational preamble ('Sure', 'Done', 'Here is...').\n"
    "2. Never wrap output in markdown code fences (no ```json blocks).\n"
    "3. Never explain your reasoning unless the prompt asks for a "
    "'reasoning' field in JSON.\n"
    "4. When the prompt asks for JSON, your ENTIRE response must be a "
    "single valid JSON value — nothing before, nothing after.\n"
    "5. Match the requested schema exactly. Do not add extra fields."
)


class LLMError(RuntimeError):
    """Raised when the `claude` subprocess fails or returns an error."""


class LLMTimeout(LLMError):
    pass


class LLMRateLimit(LLMError):
    pass


@dataclasses.dataclass
class LLMResult:
    text: str
    structured: Any  # already-parsed object when --json-schema was used; else None
    model: str
    cost_usd: float
    duration_ms: int
    session_id: str
    raw: dict[str, Any]

    def as_json(self) -> Any:
        """Return the response as a parsed JSON value.

        When ``--json-schema`` was passed, ``structured`` already holds the
        parsed object — we return it directly. Otherwise we tolerantly parse
        ``text`` (strip markdown fences, extract first JSON value).
        """
        if self.structured is not None:
            return self.structured
        return _parse_json_tolerant(self.text)


def run(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    json_schema: dict | None = None,
    system_prompt: str | None = None,
    budget_usd: float | None = None,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> LLMResult:
    """Run a single Claude prompt and return the result.

    Parameters
    ----------
    prompt: the user prompt to send.
    model: ``"haiku"`` (default; cheap routing/classification),
        ``"sonnet"`` (extraction/digest), ``"opus"`` (rarely needed).
    json_schema: if provided, passed to ``--json-schema`` for structured
        output validation. Highly recommended for any prompt expecting JSON.
    system_prompt: override the default minimal system prompt.
    budget_usd: hard cap for this call. Defaults to ``DEFAULT_BUDGET_USD``.
    timeout_s: subprocess timeout.
    """
    binary = _find_claude_binary()
    if binary is None:
        raise LLMError(
            "`claude` binary not found. Install Claude Code "
            "(`npm i -g @anthropic-ai/claude-code`), or set "
            "`GHOSTBRAIN_CLAUDE_BIN` to its absolute path. "
            "Common install locations (~/.local/bin, /opt/homebrew/bin, "
            "/usr/local/bin) are searched automatically."
        )

    cmd: list[str] = [
        binary,
        "--print",
        "--output-format", "json",
        "--model", model,
        "--system-prompt", system_prompt or MINIMAL_SYSTEM_PROMPT,
        "--no-session-persistence",
        "--max-budget-usd", f"{budget_usd or DEFAULT_BUDGET_USD:.4f}",
        "--exclude-dynamic-system-prompt-sections",
    ]
    if json_schema is not None:
        cmd.extend(["--json-schema", json.dumps(json_schema)])

    cmd.append(prompt)

    last_err: Exception | None = None
    for attempt, delay in enumerate((0,) + RETRY_DELAYS_S):
        if delay:
            log.warning("LLM retry %d after %ds (last error: %s)",
                        attempt, delay, last_err)
            time.sleep(delay)
        try:
            return _run_once(cmd, timeout_s=timeout_s)
        except LLMRateLimit as e:
            last_err = e
            continue
        except LLMTimeout as e:
            last_err = e
            continue
    raise LLMError(f"LLM call failed after {len(RETRY_DELAYS_S)} retries: {last_err}")


def _run_once(cmd: list[str], *, timeout_s: int) -> LLMResult:
    log.debug("running: %s", _redact(cmd))
    try:
        proc = subprocess.run(
            cmd,
            # Close stdin explicitly. Otherwise claude-cli waits 3s for piped
            # input, prints a "no stdin data received" warning to stderr, and
            # that warning then masks the real error in our exception text.
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env={**os.environ, "CLAUDE_CODE_NO_TELEMETRY": "1"},
        )
    except subprocess.TimeoutExpired as e:
        raise LLMTimeout(f"`claude -p` timed out after {timeout_s}s") from e

    # Try to parse stdout as JSON before deciding what kind of failure (if
    # any) this is. claude emits structured error info on stdout — including
    # `error_max_budget_usd` and rate-limit subtypes — even when it exits
    # non-zero. Surfacing that JSON gives us actionable error messages
    # instead of whatever happened to land on stderr.
    payload: dict | None = None
    if proc.stdout:
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            payload = None

    if isinstance(payload, dict) and payload.get("is_error"):
        errors = payload.get("errors") or []
        subtype = str(payload.get("subtype") or "")
        msg = "; ".join(str(e) for e in errors) or str(payload.get("result") or subtype)
        haystack = (msg + " " + subtype).lower()
        if "rate" in haystack and "limit" in haystack:
            raise LLMRateLimit(msg)
        raise LLMError(f"claude reported error ({subtype or 'unknown'}): {msg}")

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        if "rate" in stderr.lower() and "limit" in stderr.lower():
            raise LLMRateLimit(stderr)
        # No parseable error JSON — surface stderr (and stdout as fallback)
        # so the operator sees whatever claude actually printed.
        detail = stderr or stdout[:300]
        raise LLMError(f"`claude -p` exited {proc.returncode}: {detail}")

    if payload is None:
        raise LLMError(
            f"could not parse claude -p stdout as JSON: {proc.stdout[:300]!r}"
        )

    return LLMResult(
        text=str(payload.get("result") or ""),
        structured=payload.get("structured_output"),
        model=_pick_model(payload),
        cost_usd=float(payload.get("total_cost_usd", 0.0)),
        duration_ms=int(payload.get("duration_ms", 0)),
        session_id=str(payload.get("session_id", "")),
        raw=payload,
    )


def _pick_model(payload: dict) -> str:
    usage = payload.get("modelUsage") or {}
    if usage:
        return next(iter(usage.keys()))
    return ""


_FENCE_RE = re.compile(r"^\s*```(?:json|js)?\s*\n?(.*?)\n?\s*```\s*$",
                       re.DOTALL | re.IGNORECASE)


def _parse_json_tolerant(text: str) -> Any:
    """Pull a JSON value out of a possibly-prose response."""
    if not text:
        raise LLMError("LLM returned empty response")

    candidate = text.strip()

    # Strip a wrapping ```json ... ``` block if present.
    fence_match = _FENCE_RE.match(candidate)
    if fence_match:
        candidate = fence_match.group(1).strip()

    # Fast path: the whole thing is JSON.
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # Slow path: find the first '{' or '[' and try progressively longer
    # prefixes. JSONDecoder.raw_decode returns the longest valid JSON value
    # starting at the given offset.
    decoder = json.JSONDecoder()
    for i, ch in enumerate(candidate):
        if ch in "{[":
            try:
                value, _ = decoder.raw_decode(candidate[i:])
                return value
            except json.JSONDecodeError:
                continue

    raise LLMError(
        f"could not extract JSON from LLM output: {text[:300]!r}"
    )


def _redact(cmd: list[str]) -> list[str]:
    """Trim long arg values for log readability."""
    out: list[str] = []
    for x in cmd:
        out.append(x if len(x) <= 80 else x[:77] + "...")
    return out
