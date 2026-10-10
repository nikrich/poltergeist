"""Single-note read for the in-app markdown viewer.

Strict path validation: rejects absolute paths and `..` segments, then
resolves against the vault root and requires the result to live under it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ghostbrain import vault_write
from ghostbrain.vault_write import USER, Actor


class NoteNotFound(Exception):
    pass


class NoteInvalidPath(Exception):
    pass


def _resolve_safe(rel: str) -> Path:
    try:
        return vault_write.resolve_safe(rel, suffixes=(".md",))
    except vault_write.InvalidPath as e:
        raise NoteInvalidPath(str(e)) from None


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)  # dates, datetimes, anything else


def get_note(rel_path: str) -> dict:
    """Read a note. The body comes from the same parser the write path splices
    with, so a save can never duplicate frontmatter into the body (BOM files,
    leading blank lines)."""
    target = _resolve_safe(rel_path)
    if not target.exists() or not target.is_file():
        raise NoteNotFound(rel_path)
    try:
        snap = vault_write.read(rel_path, suffixes=(".md",))
    except (vault_write.MalformedNote, vault_write.FileMissing) as e:
        raise NoteNotFound(f"could not parse: {e}")
    try:
        meta = snap.metadata()
    except vault_write.MalformedNote:
        # Frontmatter that is not valid YAML or not a mapping (e.g. a paragraph
        # between two rules): still open the note, with no metadata.
        meta = {}
    fm = _jsonable(dict(meta))
    title = str(fm.get("title") or target.stem)
    return {
        "path": rel_path,
        "title": title,
        "body": snap.body,
        "frontmatter": fm,
        "etag": snap.etag,
    }


def save_note_body(
    rel_path: str, body: str, *, actor: Actor = USER, base_etag: str | None = None
) -> dict:
    """Rewrite only the markdown body; the frontmatter block's bytes are kept
    exactly (spec B1). ``updated`` is bumped only when the key already exists.
    A stale ``base_etag`` raises WriteConflict (→ 409)."""
    target = _resolve_safe(rel_path)
    if not target.exists() or not target.is_file():
        raise NoteNotFound(rel_path)
    res = vault_write.write(
        rel_path, body=body, actor=actor, base_etag=base_etag, reason="edited in the editor",
    )
    return {"path": rel_path, "updated": res.updated, "etag": res.etag,
            "historyOk": res.history_ok}


def save_note_at_path(
    rel_path: str, content: str, *, actor: Actor = USER, base_etag: str | None = None
) -> dict:
    """Create or fully replace a note (plugin write-back). The caller owns the
    whole file; a trailing newline is ensured."""
    target = _resolve_safe(rel_path)
    created = not target.exists()
    res = vault_write.write(
        rel_path,
        content=content,
        op="create" if created else "modify",
        actor=actor,
        base_etag=base_etag,
        reason="plugin write-back",
    )
    return {"path": rel_path, "created": created, "etag": res.etag}
