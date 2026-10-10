"""Vault context for inline AI's "draft from my vault" (spec A5).

Retrieval happens here, server-side, so a draft is grounded with every LLM
provider (claude, codex, gemini, local), not only those that run the MCP
search tools. Order: semantic-search hits for the instruction, then the
note's own link neighbourhood from the A2 link index. Never raises: no index,
no model or an unreadable note just means less context.
"""
from __future__ import annotations

import logging

from ghostbrain.api.repo import note as note_repo

log = logging.getLogger("ghostbrain.docs_context")

MAX_NOTES = 6
PER_NOTE_CHARS = 1500
TOTAL_CHARS = 9000
SEARCH_LIMIT = 8


def _search_paths(query: str) -> list[str]:
    if not query.strip():
        return []
    try:
        from ghostbrain.api.repo import search as search_repo

        items = search_repo.search(query, limit=SEARCH_LIMIT).get("items", [])
    except Exception:  # noqa: BLE001 — no index / no model: draft without it
        log.warning("docs context: semantic search unavailable", exc_info=True)
        return []
    return [h["path"] for h in items if isinstance(h, dict) and isinstance(h.get("path"), str)]


def _neighbour_paths(current_path: str | None) -> list[str]:
    if not current_path:
        return []
    try:
        from ghostbrain.vault_index.links import get_link_index

        index = get_link_index()
        index.ensure_fresh(wait=0.5)
        out = [e.target for e in index.outgoing(current_path) if e.exists]
        out += [e.source for e in index.backlinks(current_path)]
        return out
    except Exception:  # noqa: BLE001
        log.warning("docs context: link index unavailable", exc_info=True)
        return []


def _block(rel: str) -> str | None:
    try:
        n = note_repo.get_note(rel)
    except (note_repo.NoteNotFound, note_repo.NoteInvalidPath):
        return None
    except Exception:  # noqa: BLE001 — one bad note must not sink the draft
        log.warning("docs context: could not read %s", rel, exc_info=True)
        return None
    body = (n.get("body") or "").strip()
    if not body:
        return None
    if len(body) > PER_NOTE_CHARS:
        body = body[:PER_NOTE_CHARS].rstrip() + " …"
    return f"### {n['title']} ({rel})\n{body}"


def gather(query: str, *, current_path: str | None) -> str:
    if current_path:  # link-index keys and search hits are posix
        current_path = current_path.replace("\\", "/")
    seen: set[str] = {current_path} if current_path else set()
    blocks: list[str] = []
    total = 0
    for rel in _search_paths(query) + _neighbour_paths(current_path):
        if rel in seen:
            continue
        seen.add(rel)
        block = _block(rel)
        if block is None:
            continue
        cost = len(block) + (2 if blocks else 0)
        if total + cost > TOTAL_CHARS:
            break
        blocks.append(block)
        total += cost
        if len(blocks) >= MAX_NOTES:
            break
    return "\n\n".join(blocks)
