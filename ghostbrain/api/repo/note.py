"""Single-note read for the in-app markdown viewer.

Strict path validation: rejects absolute paths and `..` segments, then
resolves against the vault root and requires the result to live under it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import frontmatter

from ghostbrain.paths import vault_path


class NoteNotFound(Exception):
    pass


class NoteInvalidPath(Exception):
    pass


def _resolve_safe(rel: str) -> Path:
    if not rel or rel.startswith("/") or "\x00" in rel:
        raise NoteInvalidPath("path must be vault-relative")
    candidate = Path(rel)
    if candidate.is_absolute() or any(part == ".." for part in candidate.parts):
        raise NoteInvalidPath("path must not contain '..' or be absolute")
    root = vault_path().resolve()
    target = (root / candidate).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise NoteInvalidPath("path escapes the vault root")
    if target.suffix.lower() != ".md":
        raise NoteInvalidPath("only .md files can be read")
    return target


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)  # dates, datetimes, anything else


def get_note(rel_path: str) -> dict:
    target = _resolve_safe(rel_path)
    if not target.exists() or not target.is_file():
        raise NoteNotFound(rel_path)
    try:
        post = frontmatter.load(target)
    except Exception as e:
        raise NoteNotFound(f"could not parse: {e}")
    fm = _jsonable(dict(post.metadata))
    title = str(fm.get("title") or target.stem)
    return {
        "path": rel_path,
        "title": title,
        "body": post.content or "",
        "frontmatter": fm,
    }
