"""User MCP servers merged into the chat command (spec 2026-07-08-chat-mcp-servers)."""
from __future__ import annotations

import json

from ghostbrain.llm.agent import ALLOWED_TOOLS, build_chat_command

MEMPALACE = {
    "name": "mempalace",
    "command": "npx",
    "args": ["-y", "mempalace-mcp"],
    "env": {"KEY": "v"},
    "enabled": True,
    "tools": "",
}


def _mcp_config(cmd):
    return json.loads(cmd[cmd.index("--mcp-config") + 1])["mcpServers"]


def _allowed(cmd):
    return cmd[cmd.index("--allowedTools") + 1]


def test_no_user_servers_is_byte_identical():
    base = build_chat_command("/bin/claude", "hi", mcp_binary="/bin/gb-mcp")
    with_none = build_chat_command(
        "/bin/claude", "hi", mcp_binary="/bin/gb-mcp", user_servers=None
    )
    with_empty = build_chat_command(
        "/bin/claude", "hi", mcp_binary="/bin/gb-mcp", user_servers=[]
    )
    assert base == with_none == with_empty


def test_user_server_merges_config_env_and_allowed_tools():
    cmd = build_chat_command(
        "/bin/claude", "hi", mcp_binary="/bin/gb-mcp", user_servers=[MEMPALACE]
    )
    servers = _mcp_config(cmd)
    assert servers["poltergeist"] == {"command": "/bin/gb-mcp"}
    assert servers["mempalace"] == {
        "command": "npx",
        "args": ["-y", "mempalace-mcp"],
        "env": {"KEY": "v"},
    }
    assert "--strict-mcp-config" in cmd
    allowed = _allowed(cmd).split(",")
    assert "mcp__mempalace" in allowed
    for tool in ALLOWED_TOOLS.split(","):
        assert tool in allowed  # vault tools still granted


def test_tools_restriction_expands_per_tool():
    server = {**MEMPALACE, "tools": "mempalace_search, mempalace_get_drawer"}
    cmd = build_chat_command(
        "/bin/claude", "hi", mcp_binary="/bin/gb-mcp", user_servers=[server]
    )
    allowed = _allowed(cmd).split(",")
    assert "mcp__mempalace__mempalace_search" in allowed
    assert "mcp__mempalace__mempalace_get_drawer" in allowed
    assert "mcp__mempalace" not in allowed


def test_poltergeist_name_collision_loses_to_vault_server():
    rogue = {**MEMPALACE, "name": "poltergeist"}
    cmd = build_chat_command(
        "/bin/claude", "hi", mcp_binary="/bin/gb-mcp", user_servers=[rogue]
    )
    assert _mcp_config(cmd)["poltergeist"] == {"command": "/bin/gb-mcp"}


def test_user_servers_without_vault_binary_still_pinned():
    cmd = build_chat_command(
        "/bin/claude", "hi", mcp_binary=None, user_servers=[MEMPALACE]
    )
    servers = _mcp_config(cmd)
    assert "poltergeist" not in servers
    assert "mempalace" in servers
    assert "--strict-mcp-config" in cmd
    assert _allowed(cmd) == "mcp__mempalace"


def test_empty_args_env_omitted_from_config():
    bare = {**MEMPALACE, "args": [], "env": {}}
    cmd = build_chat_command(
        "/bin/claude", "hi", mcp_binary="/bin/gb-mcp", user_servers=[bare]
    )
    assert _mcp_config(cmd)["mempalace"] == {"command": "npx"}
