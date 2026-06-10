"""Docs assistant: agent overrides, prompt building, assist orchestration."""
from unittest.mock import patch

from ghostbrain.api.repo import docs_assist
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


# ---------------------------------------------------------------------------
# docs_assist repo
# ---------------------------------------------------------------------------


def test_build_prompt_polish_selection():
    p = docs_assist.build_prompt(
        body="# Doc\n\nintro text", instruction=None, selection="intro text", mode="polish",
    )
    assert "intro text" in p
    assert docs_assist.CANNED_INSTRUCTIONS["polish"] in p
    assert "ONLY the replacement markdown for the SELECTION" in p


def test_build_prompt_draft_whole_doc_uses_instruction():
    p = docs_assist.build_prompt(
        body="", instruction="Write an RFC about the activity heatmap",
        selection=None, mode="draft",
    )
    assert "Write an RFC about the activity heatmap" in p
    assert "ONLY the full replacement document" in p


def test_run_assist_streams_and_uses_docs_prompt(vault):
    from ghostbrain.api.repo import notes_manual
    rec = notes_manual.write_inbox_jot("# My doc\n\nhello")
    captured = {}

    def fake_turn(prompt, **kw):
        captured.update(kw, prompt=prompt)
        yield {"type": "delta", "text": "polished"}
        yield {"type": "done", "text": "polished", "session_id": "s1"}

    with patch.object(docs_assist.agent, "run_chat_turn", fake_turn):
        events = list(docs_assist.run_assist(rec["id"], instruction=None, selection=None, mode="polish"))
    assert [e["type"] for e in events] == ["delta", "done"]
    assert captured["system_prompt"] == docs_assist.DOCS_SYSTEM_PROMPT
    assert captured["allowed_tools"] == docs_assist.DOCS_ALLOWED_TOOLS
    assert captured["turn_key"] == f"docs:{rec['id']}"
    assert "hello" in captured["prompt"]


def test_run_assist_unknown_jot_yields_error(tmp_path, monkeypatch):
    # Isolate the vault: without this the jot lookup walks the developer's
    # real vault under ~/ghostbrain/vault.
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    events = list(docs_assist.run_assist("manual-nope", instruction=None, selection=None, mode="polish"))
    assert events == [{"type": "error", "message": "jot not found"}]
