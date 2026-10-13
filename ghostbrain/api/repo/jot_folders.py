"""Jot folders (jot folders spec §1–2).

A jot's location is its (context, project) plus a ``folder`` frontmatter path
relative to it. ``jot-folders.json`` in the state dir only keeps EMPTY folders
alive: the folder set is registry ∪ every folder a routed jot references ∪
their parents, so losing the registry only loses empty folders.
"""
from __future__ import annotations

import logging
import threading

from ghostbrain.api.repo import notes_manual
from ghostbrain.api.repo import scoped_folders as sf
from ghostbrain.paths import state_dir
from ghostbrain.vault_write import USER, Actor, WriteConflict

log = logging.getLogger("ghostbrain.jot.folders")

lock = threading.RLock()  # every registry read-modify-write + multi-jot folder op

JotFolderError = sf.FolderError


class JotMissing(JotFolderError):
    status = 404


class JotConflict(JotFolderError):
    status = 409


class FolderMoveIncomplete(JotFolderError):
    status = 409


_REGISTRY = sf.Registry(lambda: state_dir() / "jot-folders.json", "jot")
_registry = _REGISTRY.load
_save_registry = _REGISTRY.save


def _jots() -> list[dict]:
    return notes_manual.list_jots(limit=1_000_000)["items"]


def _folder_of(row: dict) -> str:
    """The row's folder, cleaned; a hand-edited invalid value counts as the root."""
    value = row.get("folder")
    if not isinstance(value, str):
        return ""
    try:
        return sf.clean_path(value)
    except sf.InvalidLocation:
        return ""


def _filed(row: dict) -> bool:
    return row.get("routingStatus") == "routed" and bool(row.get("context"))


def _all_folders(rows: list[dict] | None = None) -> set[sf.Entry]:
    rows = _jots() if rows is None else rows
    used = {(r["context"], r.get("project"), f) for r in rows if _filed(r) and (f := _folder_of(r))}
    return sf.with_parents(_registry() | used)


def create(context: str, project: str | None, path: str) -> dict:
    cleaned = sf.clean_path(path)
    if not cleaned:
        raise sf.InvalidLocation("folder path is required")
    with lock:
        sf.check_location(context, project)
        if (context, project, cleaned) in _all_folders():
            raise sf.FolderExists(f"folder already exists: {cleaned}")
        _save_registry(_registry() | sf.with_parents({(context, project, cleaned)}))
    return {"context": context, "project": project, "path": cleaned}


def delete(context: str, project: str | None, path: str) -> None:
    cleaned = sf.clean_path(path)
    with lock:
        rows = _jots()
        folders = _all_folders(rows)
        if (context, project, cleaned) not in folders:
            raise sf.FolderNotFound(f"folder not found: {cleaned}")
        if any((c, p) == (context, project) and f != cleaned and sf.under(f, cleaned) for c, p, f in folders):
            raise sf.FolderNotEmpty(f"folder is not empty: {cleaned}")
        if any(_filed(r) and (r["context"], r.get("project")) == (context, project)
               and _folder_of(r) and sf.under(_folder_of(r), cleaned) for r in rows):
            raise sf.FolderNotEmpty(f"folder is not empty: {cleaned}")
        _save_registry(_registry() - {(context, project, cleaned)})


def move_folder(src: tuple, dst: tuple, *, actor: Actor = USER) -> dict:
    """Rename or move a folder with every jot inside it. Jots that fail to move
    are reported after the rest have moved; each move is its own atomic write."""
    s_ctx, s_proj, s_raw = src
    d_ctx, d_proj, d_raw = dst
    s_path, d_path = sf.clean_path(s_raw), sf.clean_path(d_raw)
    if not s_path or not d_path:
        raise sf.InvalidLocation("folder path is required")
    with lock:
        rows = _jots()
        existing = _all_folders(rows)
        if (s_ctx, s_proj, s_path) not in existing:
            raise sf.FolderNotFound(f"folder not found: {s_path}")
        sf.check_location(d_ctx, d_proj)
        if (s_ctx, s_proj) == (d_ctx, d_proj) and sf.under(d_path, s_path):
            raise sf.InvalidLocation("cannot move a folder into itself")
        if (d_ctx, d_proj, d_path) in existing:
            raise sf.FolderExists(f"folder already exists: {d_path}")

        def remap(path: str) -> str:
            return d_path + path[len(s_path):]

        reg = set()
        for c, p, path in _registry():
            if (c, p) == (s_ctx, s_proj) and sf.under(path, s_path):
                reg.add((d_ctx, d_proj, remap(path)))
            else:
                reg.add((c, p, path))
        reg |= sf.with_parents({(d_ctx, d_proj, d_path)})  # keep the moved folder even if it was only implied
        _save_registry(reg)

        failed: list[str] = []
        for r in rows:
            f = _folder_of(r)
            if not (_filed(r) and (r["context"], r.get("project")) == (s_ctx, s_proj) and f and sf.under(f, s_path)):
                continue
            try:
                notes_manual.move_jot(
                    r["id"], to_context=d_ctx, to_project=d_proj, folder=remap(f),
                    confidence=1.0, method="user", reasoning="moved with its folder", actor=actor,
                )
            except Exception:
                log.exception("jot %s did not move with folder %s", r["id"], s_path)
                failed.append(r["id"])
        if failed:
            raise FolderMoveIncomplete(f"{len(failed)} jot(s) did not move: {', '.join(failed)}")
    return {"context": d_ctx, "project": d_proj, "path": d_path}


def move_jot_to(jot_id: str, *, context: str, project: str | None, folder: str | None, actor: Actor = USER) -> dict:
    """File a jot at (context, project, folder). Files pending / manual-review jots too."""
    with lock:
        sf.check_location(context, project)
        cleaned = sf.clean_path(folder) or None
        try:
            result = notes_manual.move_jot(
                jot_id, to_context=context, to_project=project, folder=cleaned,
                confidence=1.0, method="user", reasoning="moved by user", actor=actor,
            )
        except notes_manual.JotNotFound:
            raise JotMissing(f"jot not found: {jot_id}") from None
        except WriteConflict as e:
            raise JotConflict(f"jot changed underneath the move: {jot_id}") from e
        if cleaned and (context, project, cleaned) not in _registry():
            _save_registry(_registry() | sf.with_parents({(context, project, cleaned)}))
        return result


def repoint_project(context: str, old_slug: str, new_slug: str) -> None:
    with lock:
        _REGISTRY.repoint(context, old_slug, new_slug)


def _item(row: dict, unknown: bool = False) -> dict:
    return {**row, "folder": _folder_of(row) or None, "unknownLocation": unknown}


def tree() -> dict:
    with lock:
        rows = _jots()
        folders = _all_folders(rows)
    contexts, known = sf.known_locations()
    inbox: list[dict] = []
    unrouted: list[dict] = []
    by_loc: dict[tuple, dict[str, list[dict]]] = {}
    for r in rows:  # list_jots is already newest-first
        if r["routingStatus"] == "pending":
            inbox.append(_item(r))
        elif not _filed(r):
            unrouted.append(_item(r))
        elif r["context"] not in contexts or (r.get("project") and (r["context"], r["project"]) not in known):
            unrouted.append(_item(r, unknown=True))
        else:
            by_loc.setdefault((r["context"], r.get("project")), {}).setdefault(_folder_of(r), []).append(_item(r))
    return {
        "inbox": inbox,
        "unrouted": unrouted,
        "scopes": sf.build_scopes(folders, by_loc, leaf_key="jots", sort_key="created"),
    }
