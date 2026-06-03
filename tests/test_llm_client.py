"""Tests for ghostbrain.llm.client. Subprocess calls are mocked."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest

from ghostbrain.llm import client as llm_client
from ghostbrain.llm.client import (
    LLMError,
    LLMRateLimit,
    LLMResult,
    _parse_json_tolerant,
    _run_once,
)


def _result(text: str) -> LLMResult:
    return LLMResult(text=text, structured=None, model="haiku",
                     cost_usd=0.0, duration_ms=0, session_id="s", raw={})


def test_parse_clean_json_object() -> None:
    assert _parse_json_tolerant('{"a": 1}') == {"a": 1}


def test_parse_clean_json_array() -> None:
    assert _parse_json_tolerant('[1, 2, 3]') == [1, 2, 3]


def test_parse_strips_markdown_fence() -> None:
    text = '```json\n{"context": "codeship", "confidence": 0.9}\n```'
    assert _parse_json_tolerant(text) == {"context": "codeship", "confidence": 0.9}


def test_parse_strips_lowercase_fence_without_lang() -> None:
    text = '```\n[]\n```'
    assert _parse_json_tolerant(text) == []


def test_parse_finds_json_after_preamble() -> None:
    text = 'Here is the result:\n\n{"context": "personal", "confidence": 0.85}'
    assert _parse_json_tolerant(text) == {"context": "personal", "confidence": 0.85}


def test_parse_ignores_trailing_chatter() -> None:
    text = '{"a": 1}\n\nLet me know if you need anything else.'
    assert _parse_json_tolerant(text) == {"a": 1}


def test_parse_array_with_preamble_and_trailing() -> None:
    text = "Sure! Here you go:\n\n[{\"x\": 1}, {\"x\": 2}]\n\nThat's all."
    assert _parse_json_tolerant(text) == [{"x": 1}, {"x": 2}]


def test_parse_raises_when_no_json() -> None:
    with pytest.raises(LLMError):
        _parse_json_tolerant("I cannot do that.")


def test_parse_raises_on_empty() -> None:
    with pytest.raises(LLMError):
        _parse_json_tolerant("")


def test_llmresult_as_json_uses_tolerant_parser() -> None:
    r = _result('Done. Result: {"context": "codeship", "confidence": 0.9}')
    assert r.as_json() == {"context": "codeship", "confidence": 0.9}


def test_llmresult_prefers_structured_over_text() -> None:
    """When --json-schema was used, `structured` is already a parsed object."""
    r = LLMResult(
        text="", structured={"context": "sanlam", "confidence": 0.9},
        model="haiku", cost_usd=0.0, duration_ms=0, session_id="s", raw={},
    )
    assert r.as_json() == {"context": "sanlam", "confidence": 0.9}


def test_llmresult_falls_back_to_text_when_no_structured() -> None:
    r = LLMResult(
        text='{"x": 1}', structured=None,
        model="haiku", cost_usd=0.0, duration_ms=0, session_id="s", raw={},
    )
    assert r.as_json() == {"x": 1}


# ---------------------------------------------------------------------------
# _run_once: subprocess invocation + error surfacing
# ---------------------------------------------------------------------------


class _FakeProc:
    def __init__(self, *, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _ok_payload() -> str:
    return json.dumps({
        "result": "hi",
        "total_cost_usd": 0.01,
        "duration_ms": 100,
        "session_id": "s",
        "modelUsage": {"claude-haiku-4-5-20251001": {}},
    })


def test_run_once_closes_stdin() -> None:
    """Without stdin=DEVNULL, claude-cli waits 3s for piped data and prints
    a misleading 'no stdin data received' warning to stderr — which then
    masks the real error in the wrapper's exception text."""
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["kwargs"] = kwargs
        return _FakeProc(stdout=_ok_payload())

    with patch.object(llm_client.subprocess, "run", side_effect=fake_run):
        _run_once(["claude"], timeout_s=10)

    assert captured["kwargs"].get("stdin") == subprocess.DEVNULL


def test_run_once_surfaces_budget_error_from_stdout_json() -> None:
    """claude exits 1 with a structured `is_error: true` JSON on stdout
    when --max-budget-usd is exceeded. The wrapper must surface that real
    cause, not the unrelated stdin warning that happens to be in stderr."""
    stdout = json.dumps({
        "is_error": True,
        "subtype": "error_max_budget_usd",
        "errors": ["Reached maximum budget ($0.05)"],
        "result": "",
    })
    stderr = "Warning: no stdin data received in 3s, proceeding without it."
    proc = _FakeProc(returncode=1, stdout=stdout, stderr=stderr)

    with patch.object(llm_client.subprocess, "run", return_value=proc):
        with pytest.raises(LLMError) as exc_info:
            _run_once(["claude"], timeout_s=10)

    msg = str(exc_info.value)
    assert "budget" in msg.lower()
    assert "$0.05" in msg
    assert "stdin" not in msg.lower()  # the irrelevant warning is suppressed


def test_run_once_detects_rate_limit_in_structured_json() -> None:
    """Rate-limit detection must work when the message comes through
    claude's structured error JSON, not only when it shows up in stderr."""
    stdout = json.dumps({
        "is_error": True,
        "errors": ["API rate limit exceeded; retry after 30s"],
    })
    proc = _FakeProc(returncode=1, stdout=stdout, stderr="")

    with patch.object(llm_client.subprocess, "run", return_value=proc):
        with pytest.raises(LLMRateLimit):
            _run_once(["claude"], timeout_s=10)


def test_run_once_falls_back_to_stderr_when_no_json() -> None:
    """When stdout has no parseable JSON at all (e.g. claude crashed before
    emitting structured output), use stderr text in the error message."""
    proc = _FakeProc(returncode=2, stdout="", stderr="cli launch failure foo")

    with patch.object(llm_client.subprocess, "run", return_value=proc):
        with pytest.raises(LLMError) as exc_info:
            _run_once(["claude"], timeout_s=10)

    assert "cli launch failure foo" in str(exc_info.value)


def test_run_once_succeeds_with_valid_payload() -> None:
    """The happy path still works after the error-handling refactor."""
    proc = _FakeProc(returncode=0, stdout=_ok_payload())

    with patch.object(llm_client.subprocess, "run", return_value=proc):
        result = _run_once(["claude"], timeout_s=10)

    assert result.text == "hi"
    assert result.cost_usd == pytest.approx(0.01)


# ---------------------------------------------------------------------------
# _find_claude_binary: PATH lookup with fallback to known install locations
# ---------------------------------------------------------------------------


def test_find_claude_prefers_env_override(monkeypatch, tmp_path) -> None:
    """An explicit env var beats everything — operators need an escape hatch
    when claude lives in a non-standard place."""
    fake = tmp_path / "my-claude"
    fake.touch()
    monkeypatch.setenv("GHOSTBRAIN_CLAUDE_BIN", str(fake))
    # which() should NOT be consulted when the override is valid.
    with patch.object(llm_client.shutil, "which", return_value="/should/not/win"):
        assert llm_client._find_claude_binary() == str(fake)


def test_find_claude_uses_path_when_present(monkeypatch) -> None:
    monkeypatch.delenv("GHOSTBRAIN_CLAUDE_BIN", raising=False)
    with patch.object(llm_client.shutil, "which", return_value="/opt/homebrew/bin/claude"):
        assert llm_client._find_claude_binary() == "/opt/homebrew/bin/claude"


def test_find_claude_falls_back_to_local_bin(monkeypatch, tmp_path) -> None:
    """When PATH is bare (Finder launch on macOS strips it), `shutil.which`
    misses `claude` even though it's installed under ~/.local/bin. The
    fallback must find it there before giving up."""
    monkeypatch.delenv("GHOSTBRAIN_CLAUDE_BIN", raising=False)
    fake_home = tmp_path
    (fake_home / ".local" / "bin").mkdir(parents=True)
    fake_claude = fake_home / ".local" / "bin" / "claude"
    fake_claude.touch()
    monkeypatch.setattr(llm_client.Path, "home", classmethod(lambda cls: fake_home))
    with patch.object(llm_client.shutil, "which", return_value=None):
        assert llm_client._find_claude_binary() == str(fake_claude)


def test_find_claude_returns_none_when_truly_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("GHOSTBRAIN_CLAUDE_BIN", raising=False)
    monkeypatch.setattr(llm_client.Path, "home", classmethod(lambda cls: tmp_path))
    with patch.object(llm_client.shutil, "which", return_value=None):
        assert llm_client._find_claude_binary() is None
