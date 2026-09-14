from __future__ import annotations

import json
from pathlib import Path

import pytest

from ghostbrain.llm.client import LLMError, LLMTimeout
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


def test_complete_raises_on_empty_output_even_without_schema(monkeypatch):
    p = cx.CodexCli(M, binary="/c")
    monkeypatch.setattr(cx, "_run", lambda cmd, stdin_text, timeout_s: ("", "", 0))
    with pytest.raises(LLMError):
        p.complete(base.CompletionRequest(prompt="x", tier="fast"))


def test_probe_never_raises_when_run_raises(monkeypatch):
    monkeypatch.setattr(cx, "find_codex_binary", lambda: "/c")

    def _raise(cmd, stdin_text, timeout_s):
        raise LLMTimeout("codex exec timed out after 15s")

    monkeypatch.setattr(cx, "_run", _raise)
    pr = cx.CodexCli(M).probe()
    assert pr.ok is False and "codex login status failed" in pr.reason


def test_probe_handles_whitespace_only_stdout(monkeypatch):
    monkeypatch.setattr(cx, "find_codex_binary", lambda: "/c")
    monkeypatch.setattr(cx, "_run", lambda cmd, stdin_text, timeout_s: ("   \n", "", 0))
    pr = cx.CodexCli(M).probe()
    assert pr.ok is True
