"""Folder plumbing shared by chat and jot folders (jot folders spec §1).

A folder lives at a location — (context, project slug | None) — and is a
slash path relative to it. A registry file only keeps EMPTY folders alive;
callers union it with the folders their items reference.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path

from ghostbrain import routing_config
from ghostbrain.api.repo import projects as projects_repo
from ghostbrain.api.repo.doc_library.scope import InvalidPath, clean_rel

log = logging.getLogger("ghostbrain.folders")

Entry = tuple[str, "str | None", str]  # (context, project, path)


class FolderError(Exception):
    status = 422


class InvalidLocation(FolderError):
    status = 422


class FolderNotFound(FolderError):
    status = 404


class FolderExists(FolderError):
    status = 409


class FolderNotEmpty(FolderError):
    status = 409


def clean_path(path: str | None) -> str:
    try:
        return clean_rel(path or "")
    except InvalidPath as e:
        raise InvalidLocation(str(e)) from None


def check_location(context: str, project: str | None, *, for_write: bool = True) -> None:
    if context not in routing_config.contexts():
        raise InvalidLocation(f"unknown context: {context}")
    if project is None:
        return
    p = projects_repo.get_project(context, project)
    if p is None:
        raise InvalidLocation(f"unknown project: {context}/{project}")
    if for_write and p.get("archived"):
        raise InvalidLocation(f"project is archived: {context}/{project}")


def with_parents(entries) -> set[Entry]:
    out: set[Entry] = set()
    for c, p, path in entries:
        parts = path.split("/")
        for i in range(1, len(parts) + 1):
            out.add((c, p, "/".join(parts[:i])))
    return out


def under(path: str, root: str) -> bool:
    return path == root or path.startswith(root + "/")


class Registry:
    def __init__(self, path_fn: Callable[[], Path], label: str) -> None:
        self._path_fn = path_fn
        self._label = label

    def load(self) -> set[Entry]:
        path = self._path_fn()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return {(f["context"], f.get("project"), f["path"]) for f in raw.get("folders", [])}
        except FileNotFoundError:
            return set()
        except (json.JSONDecodeError, OSError, KeyError, TypeError, AttributeError):
            log.warning("unreadable %s folder registry %s; treating as empty", self._label, path)
            return set()

    def save(self, entries: set[Entry]) -> None:
        target = self._path_fn()
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        rows = [{"context": c, "project": p, "path": path}
                for c, p, path in sorted(entries, key=lambda e: (e[0], e[1] or "", e[2]))]
        tmp.write_text(json.dumps({"folders": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(target)

    def repoint(self, context: str, old_slug: str, new_slug: str) -> None:
        self.save({(c, new_slug if (c == context and p == old_slug) else p, path) for c, p, path in self.load()})


def _node(name: str, path: str, entries: set[str], by_folder: dict[str, list[dict]], leaf_key: str, sort_key: str) -> dict:
    prefix = f"{path}/" if path else ""
    child_names = sorted({e[len(prefix):].split("/", 1)[0] for e in entries if e.startswith(prefix) and e != path and e})
    return {
        "name": name,
        "path": path,
        "folders": [_node(n, f"{prefix}{n}", entries, by_folder, leaf_key, sort_key) for n in child_names],
        leaf_key: sorted(by_folder.get(path, []), key=lambda s: s[sort_key], reverse=True),
    }


def build_scopes(folders: set[Entry], by_loc: dict, *, leaf_key: str, sort_key: str) -> list[dict]:
    """Contexts in routing order; each bare context then its projects by name.
    Archived projects with nothing in them are left out."""
    contexts = routing_config.contexts()
    projs = projects_repo.list_projects(include_archived=True)

    def scope(ctx: str, proj: str | None, name: str, archived: bool) -> dict:
        entries = {path for c, p, path in folders if (c, p) == (ctx, proj)}
        root = _node(name, "", entries, by_loc.get((ctx, proj), {}), leaf_key, sort_key)
        return {"context": ctx, "project": proj, "name": name, "archived": archived,
                "folders": root["folders"], leaf_key: root[leaf_key]}

    scopes = []
    for ctx in contexts:
        scopes.append(scope(ctx, None, ctx, False))
        for p in sorted((p for p in projs if p["context"] == ctx), key=lambda p: p["name"].lower()):
            s = scope(ctx, p["slug"], p["name"], bool(p.get("archived")))
            if s["archived"] and not s[leaf_key] and not s["folders"]:
                continue
            scopes.append(s)
    return scopes


def known_locations() -> tuple[list[str], set[tuple[str, str]]]:
    """(contexts, {(context, slug)} of every project incl. archived)."""
    projs = projects_repo.list_projects(include_archived=True)
    return routing_config.contexts(), {(p["context"], p["slug"]) for p in projs}
