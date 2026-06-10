"""Docs assistant: agent overrides, prompt building, assist orchestration."""
from ghostbrain.llm import agent


def test_build_chat_command_default_system_prompt():
    cmd = agent.build_chat_command("claude", "hi")
    i = cmd.index("--system-prompt")
    assert cmd[i + 1] == agent.CHAT_SYSTEM_PROMPT


def test_build_chat_command_system_prompt_override():
    cmd = agent.build_chat_command("claude", "hi", system_prompt="DOCS MODE")
    i = cmd.index("--system-prompt")
    assert cmd[i + 1] == "DOCS MODE"


def test_build_chat_command_allowed_tools_override():
    cmd = agent.build_chat_command(
        "claude", "hi", mcp_binary="/bin/mcp",
        allowed_tools="mcp__poltergeist__poltergeist_search",
    )
    i = cmd.index("--allowedTools")
    assert cmd[i + 1] == "mcp__poltergeist__poltergeist_search"
