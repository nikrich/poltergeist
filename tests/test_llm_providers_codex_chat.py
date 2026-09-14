from __future__ import annotations

import tomllib
from pathlib import Path

from ghostbrain.llm.providers import base
from ghostbrain.llm.providers import codex_cli as cx

FIX = Path(__file__).parent / "fixtures" / "llm"
M = {"fast": "gpt-5-mini", "balanced": "gpt-5", "quality": "gpt-5"}


def test_parse_chat_line_maps_events():
    lines = (FIX / "codex-exec-chat.jsonl").read_text().splitlines()
    parser = cx.CodexChatParser()
    events = [e for line in lines for e in parser.feed(line)]
    assert events[0] == {"type": "session", "session_id": "thr_chat1"}
    assert {"type": "tool", "name": "search", "summary": "searched vault: budget"} in events
    assert events[-2]["type"] == "delta" and "budget was approved" in events[-2]["text"]
    assert events[-1]["type"] == "done" and events[-1]["session_id"] == "thr_chat1"


def test_parser_instances_do_not_share_state():
    a = cx.CodexChatParser()
    b = cx.CodexChatParser()
    list(a.feed('{"type":"thread.started","thread_id":"thr_A"}'))
    events = b.feed('{"type":"turn.completed","usage":{}}')
    assert events == [{"type": "done", "text": "", "session_id": ""}]


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


def test_write_codex_home_accepts_non_bmp_unicode(tmp_path: Path):
    root = cx.write_codex_home(tmp_path / "gen", model="gpt-5\U0001f642", mcp_argv=["/app/ghostbrain-api", "mcp"],
                               user_servers=[], real_home=tmp_path / "nohome")
    cfg = tomllib.loads((root / "config.toml").read_text())
    assert cfg["model"] == "gpt-5\U0001f642"


def test_chat_command_and_env(monkeypatch, tmp_path: Path):
    captured = {}
    def fake_stream(cmd, **kw):
        captured["cmd"] = cmd; captured["kw"] = kw
        for line in (FIX / "codex-exec-chat.jsonl").read_text().splitlines():
            yield from kw["parse"](line)
    monkeypatch.setattr(cx, "stream_subprocess", fake_stream)
    monkeypatch.setattr(cx, "find_codex_binary", lambda: "/c")
    monkeypatch.setattr(cx, "find_mcp_binary", lambda: ["/app/ghostbrain-api", "mcp"])
    monkeypatch.setattr(cx, "_run_root", lambda: tmp_path / "run")
    monkeypatch.setattr(cx, "_real_codex_home", lambda: tmp_path / "nohome")
    p = cx.CodexCli(M)
    events = list(p.chat(base.ChatRequest(
        prompt="q", tier="balanced", session_id=None, turn_key="c1", system_prompt="sys",
        user_servers=[{"name": "mem", "command": "npx", "args": ["-y", "mem-mcp"], "env": {}, "tools": ""}])))
    assert events[-1]["type"] == "done"
    assert captured["cmd"][:3] == ["/c", "exec", "--json"] and captured["cmd"][-1] == "-"
    assert captured["kw"]["env"]["CODEX_HOME"] == str(tmp_path / "run" / "codex")
    assert captured["kw"]["stdin_text"].startswith("<instructions>\nsys")
    # The servers the user opted into (run_chat_turn loads them onto the
    # request) must land in the generated CODEX_HOME, not just poltergeist.
    cfg = tomllib.loads((tmp_path / "run" / "codex" / "config.toml").read_text())
    assert cfg["mcp_servers"]["mem"]["command"] == "npx"
    assert "poltergeist" in cfg["mcp_servers"]


def test_chat_resume_uses_exec_resume(monkeypatch, tmp_path: Path):
    captured = {}
    def fake_stream(cmd, **kw):
        captured["cmd"] = cmd
        yield {"type": "done", "text": "ok", "session_id": "thr_chat1"}
    monkeypatch.setattr(cx, "stream_subprocess", fake_stream)
    monkeypatch.setattr(cx, "find_codex_binary", lambda: "/c")
    monkeypatch.setattr(cx, "find_mcp_binary", lambda: ["/app/ghostbrain-api", "mcp"])
    monkeypatch.setattr(cx, "_run_root", lambda: tmp_path / "run")
    monkeypatch.setattr(cx, "_real_codex_home", lambda: tmp_path / "nohome")
    list(cx.CodexCli(M).chat(base.ChatRequest(prompt="more", tier="fast", session_id="thr_chat1", turn_key="c2")))
    assert captured["cmd"][1:4] == ["exec", "resume", "thr_chat1"]


def test_chat_missing_binary_is_error_event(monkeypatch):
    monkeypatch.setattr(cx, "find_codex_binary", lambda: None)
    events = list(cx.CodexCli(M).chat(base.ChatRequest(prompt="q", tier="fast", session_id=None, turn_key=None)))
    assert events == [{"type": "error", "message": events[0]["message"]}] and "codex" in events[0]["message"]


def test_chat_resume_rejected_raises_resume_failed(monkeypatch, tmp_path: Path):
    """A stale `codex exec resume <id>` exits non-zero having streamed nothing.
    Raising ResumeFailed (exactly as the Claude driver does) is what lets
    repo/chat.py retry the turn fresh — returning an error event instead left
    the conversation permanently broken."""
    import pytest

    from ghostbrain.llm import agent

    def fake_stream(cmd, **kw):
        yield from kw["on_exit"](1, "no such session", False)

    monkeypatch.setattr(cx, "stream_subprocess", fake_stream)
    monkeypatch.setattr(cx, "find_codex_binary", lambda: "/c")
    monkeypatch.setattr(cx, "find_mcp_binary", lambda: ["/app/ghostbrain-api", "mcp"])
    monkeypatch.setattr(cx, "_run_root", lambda: tmp_path / "run")
    monkeypatch.setattr(cx, "_real_codex_home", lambda: tmp_path / "nohome")
    gen = cx.CodexCli(M).chat(base.ChatRequest(prompt="q", tier="fast", session_id="thr_stale", turn_key=None))
    with pytest.raises(agent.ResumeFailed):
        list(gen)


def test_chat_nonzero_exit_without_session_is_an_error_event(monkeypatch, tmp_path: Path):
    def fake_stream(cmd, **kw):
        yield from kw["on_exit"](1, "boom", False)

    monkeypatch.setattr(cx, "stream_subprocess", fake_stream)
    monkeypatch.setattr(cx, "find_codex_binary", lambda: "/c")
    monkeypatch.setattr(cx, "find_mcp_binary", lambda: ["/app/ghostbrain-api", "mcp"])
    monkeypatch.setattr(cx, "_run_root", lambda: tmp_path / "run")
    monkeypatch.setattr(cx, "_real_codex_home", lambda: tmp_path / "nohome")
    events = list(cx.CodexCli(M).chat(base.ChatRequest(prompt="q", tier="fast", session_id=None, turn_key=None)))
    assert events[-1]["type"] == "error" and "boom" in events[-1]["message"]
