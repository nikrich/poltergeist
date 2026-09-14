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


def test_complete_raises_on_empty_response_without_schema(monkeypatch):
    """Override: empty/whitespace response must raise LLMError even with no json_schema."""
    monkeypatch.setattr(gm, "_run", lambda cmd, timeout_s: (json.dumps({"response": ""}), "", 0))
    with pytest.raises(LLMError):
        gm.GeminiCli(M, binary="/g").complete(base.CompletionRequest(prompt="x", tier="fast"))


def test_probe_missing_binary_gives_install_hint(monkeypatch):
    monkeypatch.setattr(gm, "find_gemini_binary", lambda: None)
    pr = gm.GeminiCli(M).probe()
    assert pr.ok is False and "npm install -g @google/gemini-cli" in pr.reason


def test_probe_no_auth_gives_sign_in_hint(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(gm, "find_gemini_binary", lambda: "/g")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(gm, "_settings_path", lambda: tmp_path / "settings.json")
    pr = gm.GeminiCli(M).probe()
    assert pr.ok is False and "gemini" in pr.reason and "/auth" in pr.reason


def test_probe_run_failure_returns_ok_false(monkeypatch, tmp_path: Path):
    """Override: probe() must never raise -- LLMTimeout from the subprocess seam becomes ok=False."""
    monkeypatch.setattr(gm, "find_gemini_binary", lambda: "/g")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(gm, "_settings_path", lambda: tmp_path / "settings.json")
    (tmp_path / "settings.json").write_text(json.dumps({"security": {"auth": {"selectedType": "oauth-personal"}}}))

    def fake(cmd, timeout_s):
        raise gm.LLMTimeout("gemini --version timed out after 15s")

    monkeypatch.setattr(gm, "_run", fake)
    pr = gm.GeminiCli(M).probe()
    assert pr.ok is False and "failed" in pr.reason


def test_probe_auth_detection(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(gm, "find_gemini_binary", lambda: "/g")
    monkeypatch.setattr(gm, "_run", lambda cmd, timeout_s: ("gemini-cli 1.2.3", "", 0))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(gm, "_settings_path", lambda: tmp_path / "settings.json")
    assert gm.GeminiCli(M).probe().ok is False
    (tmp_path / "settings.json").write_text(json.dumps({"security": {"auth": {"selectedType": "oauth-personal"}}}))
    pr = gm.GeminiCli(M).probe()
    assert pr.ok is True and pr.detail["auth"] == "oauth-personal"
