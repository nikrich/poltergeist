# ghostbrain/mcp/tools.py
"""Format sidecar responses into agent-facing markdown text.

These are plain functions taking a client object (any object exposing
.answer/.search/.get_note). The MCP transport wrapper in __main__ is a thin
shell over them; keeping the logic here makes it unit-testable without the
MCP runtime.
"""
from __future__ import annotations

from typing import Protocol


class _Client(Protocol):
    def answer(self, q: str, limit: int = 8) -> dict: ...
    def search(self, q: str, limit: int = 10, days: int | None = None) -> dict: ...
    def get_note(self, path: str) -> dict: ...
    def write_doc(self, title: str, html: str) -> dict: ...


def ask(client: _Client, question: str, limit: int = 8) -> str:
    data = client.answer(question, limit=limit)
    answer = (data.get("answer") or "").strip()
    error = data.get("error")
    sources = data.get("sources") or []

    if not answer and error:
        return f"Poltergeist could not answer: {error}"
    if not answer:
        return "The vault has no notes matching this question yet."

    lines = [answer, "", "Sources:"]
    if sources:
        for i, s in enumerate(sources, start=1):
            lines.append(f"[{i}] {s.get('title') or s.get('path')} — {s.get('path')}")
    else:
        lines.append("(none)")
    return "\n".join(lines)


def search(client: _Client, query: str, limit: int = 10, days: int | None = None) -> str:
    data = client.search(query, limit=limit, days=days)
    items = data.get("items") or []
    if not items:
        return "No matching notes found in the vault."

    lines = [f"{len(items)} matches:"]
    for i, hit in enumerate(items, start=1):
        score = hit.get("score")
        score_str = f"{score:.2f}" if isinstance(score, (int, float)) else "?"
        lines.append(f"[{i}] {hit.get('title') or hit.get('path')}  (score {score_str})")
        lines.append(f"    {hit.get('path')}")
        snippet = (hit.get("snippet") or "").strip().replace("\n", " ")
        if snippet:
            lines.append(f"    {snippet}")
    return "\n".join(lines)


def get_note(client: _Client, path: str) -> str:
    data = client.get_note(path)
    title = data.get("title") or data.get("path") or path
    fm = data.get("frontmatter") or {}
    body = data.get("body") or ""
    context = fm.get("context")
    header = f"# {title}\n`{data.get('path', path)}`"
    if context:
        header += f"  ·  context: {context}"
    return f"{header}\n\n{body}"


def write_doc(client: _Client, title: str, html: str) -> str:
    """Save an agent-generated HTML document to the vault; return its path."""
    try:
        data = client.write_doc(title, html)
    except Exception as e:  # noqa: BLE001 — surface failure as text, never raise
        return f"Poltergeist could not save the document: {e}"
    return str(data.get("path") or "")
