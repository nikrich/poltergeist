"""Chat folders and locations (chat auto-filing spec §1, §3).

A chat's location is (context, project slug | None, folder | None) stored on
the chat itself. ``folders.json`` next to the chats only keeps EMPTY folders
alive: the folder set is registry ∪ every folder a chat references ∪ their
parents, so losing the registry only loses empty folders.
"""
from __future__ import annotations

from ghostbrain.api.repo import chat_store
from ghostbrain.api.repo import scoped_folders as sf
from ghostbrain.api.repo.scoped_folders import (  # re-exported: callers import these from here
    Entry,
    FolderExists,
    FolderNotEmpty,
    FolderNotFound,
    InvalidLocation,
    check_location,
    clean_path,
)
from ghostbrain.paths import chats_dir

ChatFolderError = sf.FolderError


class ChatNotFound(ChatFolderError):
    status = 404


_REGISTRY = sf.Registry(lambda: chats_dir() / "folders.json", "chat")
_registry = _REGISTRY.load
_save_registry = _REGISTRY.save
_with_parents = sf.with_parents
_under = sf.under


def _all_folders(convs: list[dict] | None = None) -> set[Entry]:
    convs = chat_store.iter_all() if convs is None else convs
    used = {(c["context"], c["project"], c["folder"]) for c in convs if c["context"] and c["folder"]}
    return _with_parents(_registry() | used)


def folder_exists(context: str, project: str | None, path: str) -> bool:
    return (context, project, clean_path(path)) in _all_folders()


def create(context: str, project: str | None, path: str) -> dict:
    cleaned = clean_path(path)
    if not cleaned:
        raise InvalidLocation("folder path is required")
    with chat_store.lock:
        check_location(context, project)
        if (context, project, cleaned) in _all_folders():
            raise FolderExists(f"folder already exists: {cleaned}")
        _save_registry(_registry() | _with_parents({(context, project, cleaned)}))
    return {"context": context, "project": project, "path": cleaned}


def move(src: tuple, dst: tuple) -> dict:
    s_ctx, s_proj, s_raw = src
    d_ctx, d_proj, d_raw = dst
    s_path, d_path = clean_path(s_raw), clean_path(d_raw)
    if not s_path or not d_path:
        raise InvalidLocation("folder path is required")
    with chat_store.lock:
        existing = _all_folders()
        if (s_ctx, s_proj, s_path) not in existing:
            raise FolderNotFound(f"folder not found: {s_path}")
        check_location(d_ctx, d_proj)
        if (s_ctx, s_proj) == (d_ctx, d_proj) and _under(d_path, s_path):
            raise InvalidLocation("cannot move a folder into itself")
        if (d_ctx, d_proj, d_path) in existing:
            raise FolderExists(f"folder already exists: {d_path}")

        def remap(path: str) -> str:
            return d_path + path[len(s_path):]

        reg = set()
        for c, p, path in _registry():
            if (c, p) == (s_ctx, s_proj) and _under(path, s_path):
                reg.add((d_ctx, d_proj, remap(path)))
            else:
                reg.add((c, p, path))
        reg |= _with_parents({(d_ctx, d_proj, d_path)})  # keep the moved folder even if it was only implied

        def fn(conv: dict) -> bool:
            if (conv["context"], conv["project"]) == (s_ctx, s_proj) and conv["folder"] and _under(conv["folder"], s_path):
                conv.update(context=d_ctx, project=d_proj, folder=remap(conv["folder"]))
                return True
            return False

        chat_store.rewrite_all(fn)
        _save_registry(reg)
    return {"context": d_ctx, "project": d_proj, "path": d_path}


def delete(context: str, project: str | None, path: str) -> None:
    cleaned = clean_path(path)
    with chat_store.lock:
        convs = chat_store.iter_all()
        folders = _all_folders(convs)
        if (context, project, cleaned) not in folders:
            raise FolderNotFound(f"folder not found: {cleaned}")
        if any((c, p) == (context, project) and path_ != cleaned and _under(path_, cleaned) for c, p, path_ in folders):
            raise FolderNotEmpty(f"folder is not empty: {cleaned}")
        if any((c["context"], c["project"]) == (context, project) and c["folder"] and _under(c["folder"], cleaned) for c in convs):
            raise FolderNotEmpty(f"folder is not empty: {cleaned}")
        _save_registry(_registry() - {(context, project, cleaned)})


def move_chat(conv_id: str, *, context: str | None, project: str | None, folder: str | None) -> dict:
    with chat_store.lock:
        if chat_store.get(conv_id) is None:
            raise ChatNotFound(conv_id)
        if context is None:
            return chat_store.move(conv_id, context=None, project=None, folder=None)
        check_location(context, project)
        cleaned = clean_path(folder) or None
        if cleaned and (context, project, cleaned) not in _all_folders():
            _save_registry(_registry() | _with_parents({(context, project, cleaned)}))
        return chat_store.move(conv_id, context=context, project=project, folder=cleaned)


def repoint_project(context: str, old_slug: str, new_slug: str) -> None:
    with chat_store.lock:
        def fn(conv: dict) -> bool:
            if conv["context"] == context and conv["project"] == old_slug:
                conv["project"] = new_slug
                return True
            return False

        chat_store.rewrite_all(fn)
        _REGISTRY.repoint(context, old_slug, new_slug)


def _summary(conv: dict, unknown: bool = False) -> dict:
    return {
        "id": conv["id"], "title": conv["title"], "created_at": conv["created_at"],
        "updated_at": conv["updated_at"], "message_count": len(conv.get("messages", [])),
        "context": conv["context"], "project": conv["project"], "folder": conv["folder"],
        "auto_filed": conv["auto_filed"], "unknown_location": unknown,
    }


def tree() -> dict:
    with chat_store.lock:
        convs = chat_store.iter_all()
        folders = _all_folders(convs)
    contexts, known = sf.known_locations()
    unfiled: list[dict] = []
    by_loc: dict[tuple, dict[str, list[dict]]] = {}
    for c in convs:
        ctx, proj = c["context"], c["project"]
        if ctx is None:
            unfiled.append(_summary(c))
        elif ctx not in contexts or (proj is not None and (ctx, proj) not in known):
            unfiled.append(_summary(c, unknown=True))
        else:
            by_loc.setdefault((ctx, proj), {}).setdefault(c["folder"] or "", []).append(_summary(c))
    unfiled.sort(key=lambda s: s["updated_at"], reverse=True)

    return {"unfiled": unfiled, "scopes": sf.build_scopes(folders, by_loc, leaf_key="chats", sort_key="updated_at")}
