"""Docs roots (where each scope's tree lives) and the path guard (spec §1, §7)."""
from __future__ import annotations

import re
from pathlib import Path

from ghostbrain import routing_config
from ghostbrain.api.repo import projects
from ghostbrain.api.repo.doc_library.errors import Conflict, InvalidPath, NotFound
from ghostbrain.paths import vault_path

DOCS_DIR = "docs"
_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def scope_root(context: str, project: str | None, *, for_write: bool = False) -> Path:
    if context not in routing_config.contexts():
        raise NotFound(f"unknown context: {context}")
    base = vault_path() / "20-contexts" / context
    if not project:
        return base / DOCS_DIR
    p = projects.get_project(context, project)
    if p is None:
        raise NotFound(f"unknown project: {context}/{project}")
    if for_write and p.get("archived"):
        raise Conflict(f"project is archived: {context}/{project}")
    return base / "projects" / project / DOCS_DIR


def clean_rel(rel: str) -> str:
    raw = (rel or "").replace("\\", "/")
    if raw.startswith("/") or _DRIVE_RE.match(raw):
        raise InvalidPath(f"absolute path not allowed: {rel}")
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    for p in parts:
        if p.startswith("."):  # covers ".." and hidden dirs (.keep, .git, tmp files)
            raise InvalidPath(f"invalid path segment: {p!r}")
    return "/".join(parts)


def resolve_in(root: Path, rel: str) -> Path:
    cleaned = clean_rel(rel)
    target = root / cleaned if cleaned else root
    root_r = root.resolve()
    target_r = target.resolve()
    if target_r != root_r and root_r not in target_r.parents:
        raise InvalidPath(f"path escapes docs root: {rel}")
    return target


def rel_folder(root: Path, folder: Path) -> str:
    rel = folder.relative_to(root).as_posix()
    return "" if rel == "." else rel


def all_scopes() -> list[tuple[str, str | None, Path]]:
    base = vault_path() / "20-contexts"
    out: list[tuple[str, str | None, Path]] = [
        (ctx, None, base / ctx / DOCS_DIR) for ctx in routing_config.contexts()
    ]
    out += [
        (p["context"], p["slug"], base / p["context"] / "projects" / p["slug"] / DOCS_DIR)
        for p in projects.list_projects(include_archived=True)
    ]
    return out
