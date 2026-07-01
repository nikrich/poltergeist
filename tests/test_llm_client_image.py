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


def test_image_paths_grant_add_dir_access(monkeypatch):
    """Without --add-dir, `claude --print` sandboxes file access to the cwd and
    refuses to read the vault image. The flag must be present, point at the
    image's directory, and (being variadic) be followed by another flag so it
    can't swallow the trailing prompt."""
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
    cmd = captured["cmd"]

    assert "--add-dir" in cmd
    i = cmd.index("--add-dir")
    assert cmd[i + 1] == "/abs"  # the image's parent directory
    # The token after the granted dir must be a flag, never the prompt — guards
    # the variadic --add-dir from eating the trailing prompt argument.
    assert cmd[i + 2].startswith("--")
    assert cmd[-1] != "/abs"  # the prompt, not a directory, is last


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
