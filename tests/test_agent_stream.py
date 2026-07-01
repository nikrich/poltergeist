"""parse_stream_line: claude stream-json lines → SSE-ready event dicts."""
from __future__ import annotations

import json

from ghostbrain.llm.agent import parse_stream_line


def line(obj: dict) -> str:
    return json.dumps(obj)


def test_blank_and_non_json_lines_ignored():
    assert parse_stream_line("") == []
    assert parse_stream_line("   ") == []
    assert parse_stream_line("not json") == []


def test_init_yields_session_event():
    events = parse_stream_line(
        line({"type": "system", "subtype": "init", "session_id": "s-1"})
    )
    assert events == [{"type": "session", "session_id": "s-1"}]


def test_text_delta_yields_delta():
    events = parse_stream_line(
        line(
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "hel"},
                },
            }
        )
    )
    assert events == [{"type": "delta", "text": "hel"}]


def test_non_text_delta_ignored():
    events = parse_stream_line(
        line(
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "input_json_delta", "partial_json": "{"},
                },
            }
        )
    )
    assert events == []


def test_assistant_tool_use_yields_tool_event_with_summary():
    events = parse_stream_line(
        line(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "let me look"},
                        {
                            "type": "tool_use",
                            "name": "mcp__poltergeist__poltergeist_search",
                            "input": {"query": "standup notes"},
                        },
                    ]
                },
            }
        )
    )
    assert events == [
        {"type": "tool", "name": "search", "summary": "searched vault: standup notes"}
    ]


def test_unknown_tool_falls_back_to_raw_name():
    events = parse_stream_line(
        line(
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "tool_use", "name": "WebSearch", "input": {}}]
                },
            }
        )
    )
    assert events == [{"type": "tool", "name": "WebSearch", "summary": "WebSearch"}]


def test_result_success_yields_done():
    events = parse_stream_line(
        line(
            {
                "type": "result",
                "subtype": "success",
                "result": "the answer",
                "session_id": "s-1",
            }
        )
    )
    assert events == [{"type": "done", "text": "the answer", "session_id": "s-1"}]


def test_result_error_yields_error():
    events = parse_stream_line(
        line(
            {
                "type": "result",
                "subtype": "error_max_budget_usd",
                "is_error": True,
                "result": "budget exceeded",
            }
        )
    )
    assert events == [{"type": "error", "message": "budget exceeded"}]


from ghostbrain.llm.agent import ALLOWED_TOOLS, CHAT_SYSTEM_PROMPT, build_chat_command


def test_build_chat_command_first_turn_with_mcp():
    cmd = build_chat_command(
        "/bin/claude", "hello", mcp_binary="/venv/bin/ghostbrain-mcp"
    )
    assert cmd[0] == "/bin/claude"
    assert cmd[-1] == "hello"
    # `--` must precede the prompt: variadic --allowedTools eats it otherwise
    assert cmd[-2] == "--"
    assert "--print" in cmd
    assert "--include-partial-messages" in cmd
    assert "--verbose" in cmd
    assert "--resume" not in cmd
    assert "--no-session-persistence" not in cmd  # we NEED sessions for resume
    i = cmd.index("--output-format")
    assert cmd[i + 1] == "stream-json"
    i = cmd.index("--mcp-config")
    mcp = json.loads(cmd[i + 1])
    assert mcp == {"mcpServers": {"poltergeist": {"command": "/venv/bin/ghostbrain-mcp"}}}
    assert "--strict-mcp-config" in cmd
    i = cmd.index("--allowedTools")
    assert cmd[i + 1] == ALLOWED_TOOLS
    assert "poltergeist_search" in ALLOWED_TOOLS


def test_build_chat_command_resume_and_no_mcp():
    cmd = build_chat_command("/bin/claude", "again", session_id="s-9", mcp_binary=None)
    i = cmd.index("--resume")
    assert cmd[i + 1] == "s-9"
    # No poltergeist server when the binary is missing, and no allowlist...
    assert "--allowedTools" not in cmd


def test_build_chat_command_mcp_argv_list_emits_command_and_args():
    """Frozen builds re-use the api exe via a subcommand, so the MCP binary is an
    argv list. The server JSON must split it into command + args."""
    cmd = build_chat_command(
        "/bin/claude", "hi", mcp_binary=["/app/ghostbrain-api", "mcp"]
    )
    i = cmd.index("--mcp-config")
    assert json.loads(cmd[i + 1]) == {
        "mcpServers": {
            "poltergeist": {"command": "/app/ghostbrain-api", "args": ["mcp"]}
        }
    }


def test_find_mcp_binary_frozen_reuses_api_exe_with_subcommand(monkeypatch):
    """In a PyInstaller bundle there is no separate ghostbrain-mcp executable —
    the api exe (sys.executable) serves the MCP server via its `mcp` subcommand."""
    monkeypatch.setattr(agent_mod.sys, "frozen", True, raising=False)
    monkeypatch.setattr(agent_mod.sys, "executable", "/app/ghostbrain-api")
    assert agent_mod.find_mcp_binary() == ["/app/ghostbrain-api", "mcp"]


def test_build_chat_command_no_mcp_still_locks_out_global_servers():
    """Even without the poltergeist binary we must pass --strict-mcp-config with
    an empty server set, or claude inherits the user's global ~/.claude.json MCP
    servers (e.g. mempalace) and runs them with no allowlist — the exact failure
    that made chat reach for mcp__mempalace__* tools behind a dead permission wall."""
    cmd = build_chat_command("/bin/claude", "hi", mcp_binary=None)
    assert "--strict-mcp-config" in cmd
    i = cmd.index("--mcp-config")
    assert json.loads(cmd[i + 1]) == {"mcpServers": {}}


def test_system_prompt_mentions_wikilink_citations():
    assert "[[" in CHAT_SYSTEM_PROMPT
    i = build_chat_command("/bin/claude", "x").index("--system-prompt")
    assert build_chat_command("/bin/claude", "x")[i + 1] == CHAT_SYSTEM_PROMPT


from ghostbrain.llm import agent as agent_mod
from ghostbrain.llm.agent import MCP_BINARY_MISSING_MESSAGE, run_chat_turn


def test_run_chat_turn_errors_when_mcp_binary_missing(monkeypatch):
    """A missing vault-tool binary must surface a real error, not silently run a
    toolless turn that lets the model improvise a fake permission prompt."""
    monkeypatch.setattr(agent_mod, "_find_claude_binary", lambda: "/bin/claude")
    monkeypatch.setattr(agent_mod, "find_mcp_binary", lambda: None)
    # If the guard works we never reach Popen — make it explode if we do.
    monkeypatch.setattr(
        agent_mod.subprocess,
        "Popen",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("spawned despite missing MCP binary")),
    )

    events = list(run_chat_turn("what's new?"))

    assert events == [{"type": "error", "message": MCP_BINARY_MISSING_MESSAGE}]
