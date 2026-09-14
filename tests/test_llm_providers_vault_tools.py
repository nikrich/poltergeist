from __future__ import annotations

from ghostbrain.llm.providers import vault_tools as vt


def test_schemas_cover_the_four_tools_with_required_params():
    names = {t["function"]["name"] for t in vt.TOOL_SCHEMAS}
    assert names == {"poltergeist_search", "poltergeist_get_note", "poltergeist_ask", "poltergeist_write_doc"}
    by = {t["function"]["name"]: t["function"]["parameters"] for t in vt.TOOL_SCHEMAS}
    assert by["poltergeist_search"]["required"] == ["query"]
    assert set(by["poltergeist_write_doc"]["required"]) == {"title", "html"}


def test_call_tool_dispatches_to_mcp_tools(monkeypatch):
    from ghostbrain.mcp import tools
    monkeypatch.setattr(tools, "search", lambda client, query, limit=10, days=None: f"hits for {query} ({limit},{days})")
    assert vt.call_tool("poltergeist_search", {"query": "budget", "days": 7}, client=object()) == "hits for budget (10,7)"
    assert vt.call_tool("nope", {}, client=object()).startswith("error: unknown tool")


def test_summary_matches_claude_tool_summaries():
    assert vt.summary_for("poltergeist_search", {"query": "q"}) == "searched vault: q"
    assert vt.summary_for("poltergeist_get_note", {"path": "a/b.md"}) == "read note: a/b.md"


def test_short_name_matches_claude_tool_summaries():
    assert vt.short_name_for("poltergeist_search") == "search"
    assert vt.short_name_for("poltergeist_get_note") == "get_note"
    assert vt.short_name_for("poltergeist_ask") == "ask"
    assert vt.short_name_for("poltergeist_write_doc") == "write_doc"
    assert vt.short_name_for("nope") == "nope"


def test_descriptions_are_verbatim_from_the_mcp_server():
    """vault_tools.TOOL_SCHEMAS is the local (non-MCP) mirror of the four
    tools registered by ghostbrain.mcp.__main__.build_server — their
    descriptions must match exactly, not be paraphrased, since they steer
    tool selection for whichever model is behind the local chat loop."""
    import asyncio

    from ghostbrain.mcp.__main__ import build_server

    server = build_server(client=object())
    registered = {t.name: t.description for t in asyncio.run(server.list_tools())}

    by_schema_name = {t["function"]["name"]: t["function"]["description"] for t in vt.TOOL_SCHEMAS}
    assert by_schema_name.keys() == registered.keys()
    for name, description in registered.items():
        assert by_schema_name[name] == description, f"{name} description diverged from mcp/__main__.py"


def test_summary_for_falls_back_to_the_short_name_on_any_format_error():
    """agent._tool_event catches everything when formatting a chip summary; the
    local driver's equivalent must too, or a tool argument that upsets str.format
    (an unexpected type, a stray brace) takes down the whole turn."""
    assert vt.summary_for("poltergeist_search", {"query": object()}) == "search"
    assert vt.summary_for("poltergeist_get_note", None) == "get_note"
    assert vt.summary_for("not_a_vault_tool", {"x": 1}) == "not_a_vault_tool"
