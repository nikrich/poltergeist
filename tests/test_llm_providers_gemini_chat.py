from __future__ import annotations

import json
from pathlib import Path

from ghostbrain.llm.client import LLMTimeout
from ghostbrain.llm.providers import base
from ghostbrain.llm.providers import gemini_cli as gm

FIX = Path(__file__).parent / "fixtures" / "llm"
M = {"fast": "gemini-2.5-flash", "balanced": "gemini-2.5-pro", "quality": "gemini-2.5-pro"}


def test_parse_stream_line_maps_events():
    events = [e for line in (FIX / "gemini-stream.jsonl").read_text().splitlines() for e in gm.parse_stream_line(line)]
    assert events[0] == {"type": "session", "session_id": "gs-1"}
    # OVERRIDE (task-9 dispatch): providers emit the SHORT tool name via
    # vault_tools.short_name_for, matching codex/claude — not the raw MCP name.
    assert {"type": "tool", "name": "search", "summary": "searched vault: budget"} in events
    assert {"type": "delta", "text": "The budget was approved."} in events
    assert events[-1]["type"] == "done"


def test_parse_stream_line_error():
    assert gm.parse_stream_line(json.dumps({"type": "error", "message": "quota"})) == [{"type": "error", "message": "quota"}]


def test_write_gemini_workspace(tmp_path: Path):
    root = gm.write_gemini_workspace(tmp_path / "ws", mcp_argv=["/app/ghostbrain-api", "mcp"],
                                     user_servers=[{"name": "mem", "command": "npx", "args": ["mem"], "env": {}, "tools": ""}],
                                     auth_type="oauth-personal")
    doc = json.loads((root / ".gemini" / "settings.json").read_text())
    assert doc["security"]["auth"]["selectedType"] == "oauth-personal"
    pol = doc["mcpServers"]["poltergeist"]
    assert pol["command"] == "/app/ghostbrain-api" and pol["args"] == ["mcp"] and pol["trust"] is True
    assert set(pol["includeTools"]) == {"poltergeist_search", "poltergeist_get_note", "poltergeist_ask", "poltergeist_write_doc"}
    assert doc["mcpServers"]["mem"]["trust"] is True


def test_write_gemini_workspace_disables_every_core_tool(tmp_path: Path):
    """`--approval-mode=yolo` auto-approves whatever gemini exposes, so the
    generated settings must leave ONLY the MCP servers: gemini's built-in
    run_shell_command/write_file/read_file/web_fetch are switched off via both
    the current nested `tools.core` key and the legacy flat `coreTools` one
    (older CLIs only honour the latter)."""
    root = gm.write_gemini_workspace(tmp_path / "ws", mcp_argv=["/app/ghostbrain-api", "mcp"],
                                     user_servers=[], auth_type=None)
    doc = json.loads((root / ".gemini" / "settings.json").read_text())
    assert doc["tools"]["core"] == []
    assert doc["coreTools"] == []
    assert doc["mcpServers"]["poltergeist"]["includeTools"] == gm.VAULT_TOOL_NAMES


def test_chat_command_cwd_and_events(monkeypatch, tmp_path: Path):
    captured = {}
    def fake_stream(cmd, **kw):
        captured["cmd"] = cmd; captured["kw"] = kw
        for line in (FIX / "gemini-stream.jsonl").read_text().splitlines():
            yield from gm.parse_stream_line(line)
    monkeypatch.setattr(gm, "stream_subprocess", fake_stream)
    monkeypatch.setattr(gm, "find_gemini_binary", lambda: "/g")
    monkeypatch.setattr(gm, "supports_resume", lambda binary: True)
    monkeypatch.setattr(gm, "read_gemini_auth", lambda: "oauth-personal")
    monkeypatch.setattr(gm, "_run_root", lambda: tmp_path / "run")
    events = list(gm.GeminiCli(M).chat(base.ChatRequest(prompt="q", tier="balanced", session_id="gs-0", turn_key="c1", system_prompt="sys")))
    cmd = captured["cmd"]
    assert cmd[0] == "/g" and cmd[cmd.index("--output-format") + 1] == "stream-json"
    assert "--approval-mode=yolo" in cmd and cmd[cmd.index("-m") + 1] == "gemini-2.5-pro"
    assert cmd[cmd.index("--resume") + 1] == "gs-0"
    assert cmd[cmd.index("-p") + 1].startswith("sys\n\n")
    assert captured["kw"]["cwd"] == str(tmp_path / "run" / "gemini")
    assert events[-1] == {"type": "done", "text": "The budget was approved.", "session_id": "gs-1"}


def test_chat_without_resume_support_prefixes_history(monkeypatch, tmp_path: Path):
    captured = {}
    def fake_stream(cmd, **kw):
        captured["cmd"] = cmd
        yield {"type": "done", "text": "ok", "session_id": ""}
    monkeypatch.setattr(gm, "stream_subprocess", fake_stream)
    monkeypatch.setattr(gm, "find_gemini_binary", lambda: "/g")
    monkeypatch.setattr(gm, "supports_resume", lambda binary: False)
    monkeypatch.setattr(gm, "read_gemini_auth", lambda: "oauth-personal")
    monkeypatch.setattr(gm, "_run_root", lambda: tmp_path / "run")
    list(gm.GeminiCli(M).chat(base.ChatRequest(prompt="next", tier="fast", session_id="gs-0", turn_key="c2",
                                                 history=[{"role": "user", "text": "first"}, {"role": "assistant", "text": "reply"}])))
    assert "--resume" not in captured["cmd"]
    prompt = captured["cmd"][captured["cmd"].index("-p") + 1]
    assert "user: first" in prompt and "assistant: reply" in prompt and prompt.rstrip().endswith("user: next")


def test_chat_not_signed_in_is_clean_error(monkeypatch, tmp_path: Path):
    called = {"stream": False}
    def fake_stream(cmd, **kw):
        called["stream"] = True
        yield {"type": "done", "text": "ok", "session_id": ""}
    monkeypatch.setattr(gm, "stream_subprocess", fake_stream)
    monkeypatch.setattr(gm, "find_gemini_binary", lambda: "/g")
    monkeypatch.setattr(gm, "read_gemini_auth", lambda: None)
    monkeypatch.setattr(gm, "_run_root", lambda: tmp_path / "run")
    events = list(gm.GeminiCli(M).chat(base.ChatRequest(prompt="q", tier="fast", session_id=None, turn_key="c3")))
    assert events == [{"type": "error", "message": "gemini is not signed in — run `gemini` and use /auth, or set GEMINI_API_KEY"}]
    assert called["stream"] is False
    assert not (tmp_path / "run" / "gemini").exists()


# --- supports_resume routes through the file's _run seam -------------------

def test_supports_resume_true_when_help_mentions_resume(monkeypatch):
    gm._resume_cache.clear()
    monkeypatch.setattr(gm, "_run", lambda cmd, timeout_s: ("usage: gemini [...] --resume <id>\n", "", 0))
    assert gm.supports_resume("/g") is True


def test_supports_resume_false_when_help_lacks_resume(monkeypatch):
    gm._resume_cache.clear()
    monkeypatch.setattr(gm, "_run", lambda cmd, timeout_s: ("usage: gemini [...]\n", "", 0))
    assert gm.supports_resume("/g") is False


def test_supports_resume_false_on_run_failure_no_raise(monkeypatch):
    gm._resume_cache.clear()
    def fake_run(cmd, timeout_s):
        raise LLMTimeout("gemini timed out after 10s")
    monkeypatch.setattr(gm, "_run", fake_run)
    assert gm.supports_resume("/g") is False


def test_supports_resume_caches_per_binary(monkeypatch):
    gm._resume_cache.clear()
    calls = []
    def fake_run(cmd, timeout_s):
        calls.append(cmd)
        return ("--resume\n", "", 0)
    monkeypatch.setattr(gm, "_run", fake_run)
    assert gm.supports_resume("/g") is True
    assert gm.supports_resume("/g") is True
    assert len(calls) == 1
