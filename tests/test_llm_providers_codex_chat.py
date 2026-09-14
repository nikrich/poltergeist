from __future__ import annotations

import tomllib
from pathlib import Path

from ghostbrain.llm.providers import base
from ghostbrain.llm.providers import codex_cli as cx

FIX = Path(__file__).parent / "fixtures" / "llm"
M = {"fast": "gpt-5-mini", "balanced": "gpt-5", "quality": "gpt-5"}


def test_parse_chat_line_maps_events():
    lines = (FIX / "codex-exec-chat.jsonl").read_text().splitlines()
    events = [e for line in lines for e in cx.parse_chat_line(line)]
    assert events[0] == {"type": "session", "session_id": "thr_chat1"}
    assert {"type": "tool", "name": "search", "summary": "searched vault: budget"} in events
    assert events[-2]["type"] == "delta" and "budget was approved" in events[-2]["text"]
    assert events[-1]["type"] == "done" and events[-1]["session_id"] == "thr_chat1"


def test_write_codex_home_config_and_auth_symlink(tmp_path: Path):
    real = tmp_path / "real-codex"; real.mkdir(); (real / "auth.json").write_text("{}")
    root = cx.write_codex_home(tmp_path / "gen", model="gpt-5", mcp_argv=["/app/ghostbrain-api", "mcp"],
                               user_servers=[{"name": "mem", "command": "npx", "args": ["-y", "mem-mcp"], "env": {"TOKEN": "t"}}],
                               real_home=real)
    cfg = tomllib.loads((root / "config.toml").read_text())
    assert cfg["model"] == "gpt-5" and cfg["sandbox_mode"] == "read-only" and cfg["approval_policy"] == "never"
    assert cfg["mcp_servers"]["poltergeist"] == {"command": "/app/ghostbrain-api", "args": ["mcp"], "required": True}
    assert cfg["mcp_servers"]["mem"]["command"] == "npx" and cfg["mcp_servers"]["mem"]["env"] == {"TOKEN": "t"}
    assert (root / "auth.json").is_symlink() and (root / "auth.json").resolve() == (real / "auth.json").resolve()


def test_chat_command_and_env(monkeypatch, tmp_path: Path):
    captured = {}
    def fake_stream(cmd, **kw):
        captured["cmd"] = cmd; captured["kw"] = kw
        for line in (FIX / "codex-exec-chat.jsonl").read_text().splitlines():
            yield from cx.parse_chat_line(line)
    monkeypatch.setattr(cx, "stream_subprocess", fake_stream)
    monkeypatch.setattr(cx, "find_codex_binary", lambda: "/c")
    monkeypatch.setattr(cx, "_run_root", lambda: tmp_path / "run")
    monkeypatch.setattr(cx, "_real_codex_home", lambda: tmp_path / "nohome")
    p = cx.CodexCli(M)
    events = list(p.chat(base.ChatRequest(prompt="q", tier="balanced", session_id=None, turn_key="c1", system_prompt="sys")))
    assert events[-1]["type"] == "done"
    assert captured["cmd"][:3] == ["/c", "exec", "--json"] and captured["cmd"][-1] == "-"
    assert captured["kw"]["env"]["CODEX_HOME"] == str(tmp_path / "run" / "codex")
    assert captured["kw"]["stdin_text"].startswith("<instructions>\nsys")
    assert (tmp_path / "run" / "codex" / "config.toml").exists()


def test_chat_resume_uses_exec_resume(monkeypatch, tmp_path: Path):
    captured = {}
    def fake_stream(cmd, **kw):
        captured["cmd"] = cmd
        yield {"type": "done", "text": "ok", "session_id": "thr_chat1"}
    monkeypatch.setattr(cx, "stream_subprocess", fake_stream)
    monkeypatch.setattr(cx, "find_codex_binary", lambda: "/c")
    monkeypatch.setattr(cx, "_run_root", lambda: tmp_path / "run")
    monkeypatch.setattr(cx, "_real_codex_home", lambda: tmp_path / "nohome")
    list(cx.CodexCli(M).chat(base.ChatRequest(prompt="more", tier="fast", session_id="thr_chat1", turn_key="c2")))
    assert captured["cmd"][1:4] == ["exec", "resume", "thr_chat1"]


def test_chat_missing_binary_is_error_event(monkeypatch):
    monkeypatch.setattr(cx, "find_codex_binary", lambda: None)
    events = list(cx.CodexCli(M).chat(base.ChatRequest(prompt="q", tier="fast", session_id=None, turn_key=None)))
    assert events == [{"type": "error", "message": events[0]["message"]}] and "codex" in events[0]["message"]
