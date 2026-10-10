"""Live query blocks (smart templates C2): run a ```query``` block against
the link index, and tick a result done through the single write path."""
from __future__ import annotations

from datetime import date

from ghostbrain.templates.query import parse_query_block, run_query
from ghostbrain.vault_index.links import LinkIndex, get_link_index
from ghostbrain.vault_write import USER, Actor, InvalidPath, write

INDEX_WAIT_S = 0.25


def query_vault(source: str, *, index: LinkIndex | None = None, today: date | None = None) -> dict:
    query, diagnostics = parse_query_block(source, today=today)
    diags = [d.to_json() for d in diagnostics]
    if query is None:
        return {"results": [], "diagnostics": diags, "indexing": False, "partial": False}
    index = index or get_link_index()
    if not index.ensure_fresh(wait=INDEX_WAIT_S):
        return {"results": [], "diagnostics": diags, "indexing": True, "partial": False}
    run = run_query(query, index)
    return {
        "results": [row.to_json() for row in run.rows],
        "diagnostics": diags,
        "indexing": False,
        "partial": run.partial,
    }


def set_note_status(
    path: str, status: str, *, base_etag: str | None, actor: Actor = USER,
) -> dict:
    """One-line frontmatter edit, as the user unless the request says
    otherwise. B1 raises InvalidPath (400), FileMissing (404), WriteConflict
    (409), MalformedNote (422); B2 raises EtagRequired (428) for a non-user
    actor without a base etag."""
    rel = path.strip()
    if not rel.lower().endswith(".md"):
        raise InvalidPath("only markdown notes (.md) have a status")
    result = write(
        rel,
        fields={"status": status},
        actor=actor,
        reason=f"query block: mark {status}",
        base_etag=base_etag,
    )
    return {"path": result.path, "status": status, "etag": result.etag}
