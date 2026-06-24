"""Tests for image_paths support in ghostbrain.llm.client.run()."""

from ghostbrain.llm import client


def test_image_paths_are_referenced_in_command(monkeypatch):
    captured = {}

    def fake_run_once(cmd, *, timeout_s):
        captured["cmd"] = cmd
        return client.LLMResult(
            text="ok",
            structured=None,
            model="sonnet",
            cost_usd=0.0,
            duration_ms=0,
            session_id="",
            raw={},
        )

    monkeypatch.setattr(client, "_find_claude_binary", lambda: "/usr/bin/claude")
    monkeypatch.setattr(client, "_run_once", fake_run_once)

    client.run("describe", image_paths=["/abs/photo.jpg"], model="sonnet")

    # The absolute path must appear in the final prompt argument.
    prompt_arg = captured["cmd"][-1]
    assert "/abs/photo.jpg" in prompt_arg


def test_no_image_paths_leaves_prompt_unchanged(monkeypatch):
    captured = {}

    def fake_run_once(cmd, *, timeout_s):
        captured["cmd"] = cmd
        return client.LLMResult(
            text="ok",
            structured=None,
            model="sonnet",
            cost_usd=0.0,
            duration_ms=0,
            session_id="",
            raw={},
        )

    monkeypatch.setattr(client, "_find_claude_binary", lambda: "/usr/bin/claude")
    monkeypatch.setattr(client, "_run_once", fake_run_once)

    client.run("describe", model="sonnet")

    prompt_arg = captured["cmd"][-1]
    assert prompt_arg == "describe"
