# ghostbrain/api/repo/doc_library/folders.py
"""Folder operations inside docs roots (spec §2). Folders are plain directories."""
from __future__ import annotations

import shutil
from pathlib import Path

from ghostbrain.api.repo.doc_library import index, notes, scope
from ghostbrain.api.repo.doc_library.errors import Conflict, InvalidRequest, NotFound

# OS/sync-tool droppings that never count as content: a folder holding only these is empty.
_JUNK = frozenset({notes.KEEP, ".DS_Store", "Thumbs.db", "desktop.ini"})


def _ref(context: str, project: str | None, path: str) -> dict:
    return {"context": context, "project": project or None, "path": path}


def create(context: str, project: str | None, path: str) -> dict:
    root = scope.scope_root(context, project, for_write=True)
    cleaned = scope.clean_rel(path)
    if not cleaned:
        raise InvalidRequest("folder path is required")
    d = scope.resolve_in(root, cleaned)
    if d.exists():
        raise Conflict(f"folder already exists: {cleaned}")
    d.mkdir(parents=True)
    (d / notes.KEEP).touch()  # keeps empty folders alive through sync tools
    index.invalidate()
    return _ref(context, project, cleaned)


def _restamp(folder: Path, context: str, project: str | None) -> None:
    for p in folder.rglob("*.md"):
        parsed = notes.read_note(p)
        if parsed is None:
            continue
        front, body = parsed
        front = {k: v for k, v in front.items() if k != "project"}
        front["context"] = context
        if project:
            front["project"] = project
        notes.write_atomic(p, notes.render(front, body))


def move(src: tuple[str, str | None, str], dst: tuple[str, str | None, str]) -> dict:
    s_ctx, s_proj, s_path = src
    d_ctx, d_proj, d_path = dst
    s_root = scope.scope_root(s_ctx, s_proj, for_write=True)
    d_root = scope.scope_root(d_ctx, d_proj, for_write=True)
    s_clean, d_clean = scope.clean_rel(s_path), scope.clean_rel(d_path)
    if not s_clean or not d_clean:
        raise InvalidRequest("a docs root itself cannot be moved")
    s_dir = scope.resolve_in(s_root, s_clean)
    d_dir = scope.resolve_in(d_root, d_clean)
    if not s_dir.is_dir():
        raise NotFound(f"folder not found: {s_clean}")
    sr, dr = s_dir.resolve(), d_dir.resolve()
    if dr == sr or sr in dr.parents:
        raise InvalidRequest("cannot move a folder into itself")
    if d_dir.exists():
        raise Conflict(f"folder already exists: {d_clean}")
    d_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(s_dir), str(d_dir))
    if (s_ctx, s_proj or None) != (d_ctx, d_proj or None):
        _restamp(d_dir, d_ctx, d_proj or None)
    index.invalidate()
    moved = [p for p in d_dir.rglob("*.md") if p.is_file()]
    notes.notify_index(*moved, *(s_dir / p.relative_to(d_dir) for p in moved))
    return _ref(d_ctx, d_proj, d_clean)


def delete(context: str, project: str | None, path: str) -> None:
    root = scope.scope_root(context, project, for_write=True)
    cleaned = scope.clean_rel(path)
    if not cleaned:
        raise InvalidRequest("a docs root itself cannot be deleted")
    d = scope.resolve_in(root, cleaned)
    if not d.is_dir():
        raise NotFound(f"folder not found: {cleaned}")
    entries = list(d.iterdir())
    if any(c.name not in _JUNK or not c.is_file() for c in entries):
        raise Conflict(f"folder is not empty: {cleaned}")
    for c in entries:
        c.unlink(missing_ok=True)
    d.rmdir()
    index.invalidate()
