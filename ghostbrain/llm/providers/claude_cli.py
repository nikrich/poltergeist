"""Claude Code adapter: `claude -p` for batch, `claude -p --output-format
stream-json` for chat.
"""
from __future__ import annotations

import json
import logging
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

from ghostbrain.llm import agent
from ghostbrain.llm import client as llm_client
from ghostbrain.llm.client import LLMError, LLMRateLimit, LLMResult, LLMTimeout
from ghostbrain.llm.providers import base
from ghostbrain.llm.providers.stream import stream_subprocess

log = logging.getLogger("ghostbrain.llm.providers.claude")

DEFAULT_MODELS: dict[str, str] = {"fast": "haiku", "balanced": "sonnet", "quality": "opus"}


class ClaudeCli:
    id = "claude"

    def __init__(
        self,
        models: dict[str, str] | None = None,
        *,
        binary: str | None = None,
        mcp_binary: str | list[str] | None = "auto",
    ) -> None:
        self._overrides = {k: v for k, v in (models or {}).items() if v}
        # Chat-only overrides (tests/callers pin a specific binary, or opt out
        # of the vault MCP server with mcp_binary=None). Ignored by complete().
        self._binary = binary
        self._mcp_binary = mcp_binary

    def models(self) -> dict[str, str]:
        return {**DEFAULT_MODELS, **self._overrides}

    # -- batch ---------------------------------------------------------------
    def build_completion_command(self, req: base.CompletionRequest) -> list[str]:
        binary = llm_client._find_claude_binary()
        if binary is None:
            raise LLMError(llm_client.BINARY_MISSING_MESSAGE)
        # When images are referenced, grant Claude Code's Read tool access to
        # their directories. Without this, `--print` sandboxes file access to
        # the cwd and refuses to read a vault asset. `--add-dir` is VARIADIC,
        # so it must be followed by another flag — never the trailing prompt,
        # which it would otherwise swallow as a directory.
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

    # -- chat ------------------------------------------------------------
    def chat(self, req: base.ChatRequest) -> Iterator[dict]:
        binary = self._binary or agent._find_claude_binary()
        if binary is None:
            yield {"type": "error", "message": agent.BINARY_MISSING_MESSAGE}
            return

        mcp_binary = self._mcp_binary
        if mcp_binary == "auto":
            mcp_binary = agent.find_mcp_binary()
            # Auto-detection failed: no vault tools means no useful turn —
            # every answer would be ungrounded. Surface a real error instead
            # of running a toolless turn that lets the model improvise. An
            # explicit mcp_binary=None is a deliberate opt-out (lifecycle
            # tests), so we only guard the auto path.
            if mcp_binary is None:
                yield {"type": "error", "message": agent.MCP_BINARY_MISSING_MESSAGE}
                return

        # User MCP servers ride along only on real chat turns (mcp_binary
        # present); explicit mcp_binary=None is the bare-run opt-out used by
        # lifecycle tests. They arrive on the request — run_chat_turn loads
        # them once per turn for every provider, so this driver never reads
        # mcp-servers.json itself.
        user_servers = list(req.user_servers) if mcp_binary else None

        cmd = agent.build_chat_command(
            binary, req.prompt,
            session_id=req.session_id,
            mcp_binary=mcp_binary,
            system_prompt=req.system_prompt,
            allowed_tools=req.allowed_tools,
            user_servers=user_servers,
        )
        log.info(
            "chat turn: resume=%s mcp=%s user_servers=%d",
            bool(req.session_id), bool(mcp_binary), len(user_servers or []),
        )

        def _on_exit(returncode: int, stderr_tail: str, saw_any: bool) -> list[dict]:
            # cancelled/timed_out are already handled by stream_subprocess;
            # this only runs for a plain (non-cancelled, non-timeout) exit.
            if req.session_id and not saw_any and returncode != 0:
                raise agent.ResumeFailed(stderr_tail or "resume failed")
            return [{
                "type": "error",
                "message": stderr_tail or f"claude exited with code {returncode}",
            }]

        yield from stream_subprocess(
            cmd,
            timeout_s=req.timeout_s,
            turn_key=req.turn_key,
            env={"CLAUDE_CODE_NO_TELEMETRY": "1"},
            parse=agent.parse_stream_line,
            on_exit=_on_exit,
        )

    def probe(self) -> base.ProviderProbe:
        binary = llm_client._find_claude_binary()
        if binary is None:
            return base.ProviderProbe(False, "`claude` CLI not found; install Claude Code and run `claude login`")
        try:
            out = subprocess.run(
                [binary, "--version"], capture_output=True, text=True, timeout=10, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            return base.ProviderProbe(False, f"`claude --version` failed: {e}")
        if out.returncode != 0:
            return base.ProviderProbe(False, "`claude --version` failed; run `claude login`")
        return base.ProviderProbe(True, out.stdout.strip(), {"binary": binary, "models": self.models()})
