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
