"""The four Poltergeist vault tools as OpenAI-style function definitions, for
providers that have no MCP client (local models). Descriptions mirror the MCP
server in ghostbrain/mcp/__main__.py; execution calls the same implementations."""
from __future__ import annotations

import json
import logging

from ghostbrain.llm.agent import TOOL_SUMMARIES
from ghostbrain.mcp import tools

log = logging.getLogger("ghostbrain.llm.providers.vault_tools")
MAX_TOOL_ROUNDS = 8


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required}}}


# Descriptions below are copied VERBATIM from the docstrings of the
# @mcp.tool()-decorated functions in ghostbrain/mcp/__main__.py — they steer
# tool selection for whichever model is behind the local chat loop the same
# way they steer Claude over MCP, so they must stay in lockstep with that
# module (tests/test_llm_providers_vault_tools.py enforces this by comparing
# against the descriptions FastMCP actually registers).
TOOL_SCHEMAS: list[dict] = [
    _fn("poltergeist_search",
        "Semantic search across the user's vault. Cheap and fast (no LLM).\n"
        "Returns ranked note paths with snippets; follow up with\n"
        "poltergeist_get_note to read a full note. For time-anchored questions\n"
        "pass days to only match recent notes (today → days=1, \"this week\" →\n"
        "days=7) — without it, ranking is content-similarity with only a mild\n"
        "recency preference.",
        {"query": {"type": "string"}, "limit": {"type": "integer", "default": 10}, "days": {"type": "integer"}}, ["query"]),
    _fn("poltergeist_get_note",
        "Fetch the full content and metadata of one vault note by its\n"
        "vault-relative path (as returned by poltergeist_search or a citation\n"
        "from poltergeist_ask).",
        {"path": {"type": "string"}}, ["path"]),
    _fn("poltergeist_ask",
        "Ask a natural-language question about the user's own work, history,\n"
        "and decisions across all their contexts. Returns a synthesized answer\n"
        "with citations. Costs an LLM call (~5-15s) — prefer poltergeist_search\n"
        "when you only need to locate notes.",
        {"question": {"type": "string"}, "limit": {"type": "integer", "default": 8}}, ["question"]),
    _fn("poltergeist_write_doc",
        "Save a document the user asked you to write. Pass a COMPLETE,\n"
        "self-contained HTML document (its own <style>; print-friendly layout\n"
        "when appropriate) as `html`. Returns the vault-relative path of the\n"
        "saved doc — cite it back to the user as a wikilink. Use this ONLY when\n"
        "the user asks you to write/draft/create a document.",
        {"title": {"type": "string"}, "html": {"type": "string"}}, ["title", "html"]),
]

_DISPATCH = {
    "poltergeist_search": lambda c, a: tools.search(c, a["query"], limit=int(a.get("limit", 10)), days=a.get("days")),
    "poltergeist_get_note": lambda c, a: tools.get_note(c, a["path"]),
    "poltergeist_ask": lambda c, a: tools.ask(c, a["question"], limit=int(a.get("limit", 8))),
    "poltergeist_write_doc": lambda c, a: tools.write_doc(c, a["title"], a["html"]),
}


def call_tool(name: str, arguments: dict, client=None) -> str:
    fn = _DISPATCH.get(name)
    if fn is None:
        return f"error: unknown tool {name}"
    if client is None:
        from ghostbrain.mcp.client import SidecarClient
        client = SidecarClient()
    try:
        return str(fn(client, arguments or {}))
    except Exception as e:  # noqa: BLE001 — the model must see the failure, not the loop
        log.warning("vault tool %s failed: %s", name, e)
        return f"error: {e}"


def _tool_summary_entry(name: str) -> tuple[str, str] | None:
    return TOOL_SUMMARIES.get(f"mcp__poltergeist__{name}") or TOOL_SUMMARIES.get(name)


def short_name_for(name: str) -> str:
    """The chip label agent.py's Claude path shows for this tool (e.g.
    "search" for "poltergeist_search") — same TOOL_SUMMARIES short names,
    so a `tool` event looks identical regardless of which provider ran it."""
    entry = _tool_summary_entry(name)
    return entry[0] if entry else name


def summary_for(name: str, arguments: dict) -> str:
    entry = _tool_summary_entry(name)
    if not entry:
        return name
    _, template = entry
    try:
        return template.format(**{k: (v if isinstance(v, str) else json.dumps(v)) for k, v in (arguments or {}).items()})
    except (KeyError, IndexError):
        return template
