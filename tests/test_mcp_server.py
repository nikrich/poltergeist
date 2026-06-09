# tests/test_mcp_server.py
import asyncio


def test_server_registers_three_tools():
    from ghostbrain.mcp.__main__ import build_server

    server = build_server()
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert names == {"poltergeist_ask", "poltergeist_search", "poltergeist_get_note"}


def test_tools_have_nonempty_descriptions():
    from ghostbrain.mcp.__main__ import build_server

    server = build_server()
    tools = asyncio.run(server.list_tools())
    for t in tools:
        assert t.description and len(t.description) > 20
