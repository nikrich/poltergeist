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


def test_probe_detail_names_the_tier_map_under_tiers(monkeypatch):
    """ProviderProbe.detail["models"] is a list[str] of server-side model ids
    for openai_http but was a dict[tier, model] for the CLI adapters — two
    shapes under one key, which the desktop types as string[]. The CLI adapters
    report their tier map under "tiers" instead."""
    import subprocess

    from ghostbrain.llm import client as llm_client
    from ghostbrain.llm.providers.claude_cli import ClaudeCli

    monkeypatch.setattr(llm_client, "_find_claude_binary", lambda: "/fake/claude")
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "2.1.0\n", ""))
    probe = ClaudeCli().probe()
    assert probe.ok is True
    assert "models" not in probe.detail
    assert probe.detail["tiers"] == {"fast": "haiku", "balanced": "sonnet", "quality": "opus"}
