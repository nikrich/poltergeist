# ghostbrain/mcp/__main__.py
"""Poltergeist MCP server. Run via the `ghostbrain-mcp` console script.

Thin stdio shell over ghostbrain.mcp.tools, which forward to the running
sidecar through ghostbrain.mcp.client. Tool descriptions are written for an
agent audience — they steer Claude toward the right tool and good chaining.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ghostbrain.mcp import tools
from ghostbrain.mcp.client import SidecarClient


def build_server(client: SidecarClient | None = None) -> FastMCP:
    client = client or SidecarClient()
    mcp = FastMCP("poltergeist")

    @mcp.tool()
    def poltergeist_ask(question: str, limit: int = 8) -> str:
        """Ask a natural-language question about the user's own work, history,
        and decisions across all their contexts. Returns a synthesized answer
        with citations. Costs an LLM call (~5-15s) — prefer poltergeist_search
        when you only need to locate notes."""
        return tools.ask(client, question, limit=limit)

    @mcp.tool()
    def poltergeist_search(query: str, limit: int = 10) -> str:
        """Semantic search across the user's vault. Cheap and fast (no LLM).
        Returns ranked note paths with snippets; follow up with
        poltergeist_get_note to read a full note."""
        return tools.search(client, query, limit=limit)

    @mcp.tool()
    def poltergeist_get_note(path: str) -> str:
        """Fetch the full content and metadata of one vault note by its
        vault-relative path (as returned by poltergeist_search or a citation
        from poltergeist_ask)."""
        return tools.get_note(client, path)

    @mcp.tool()
    def poltergeist_write_doc(title: str, html: str) -> str:
        """Save a document the user asked you to write. Pass a COMPLETE,
        self-contained HTML document (its own <style>; print-friendly layout
        when appropriate) as `html`. Returns the vault-relative path of the
        saved doc — cite it back to the user as a wikilink. Use this ONLY when
        the user asks you to write/draft/create a document."""
        return tools.write_doc(client, title, html)

    return mcp


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
