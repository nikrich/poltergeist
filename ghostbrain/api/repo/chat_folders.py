"""Chat folders and locations (chat auto-filing spec §1, §3).

A chat's location is (context, project slug | None, folder | None) stored on
the chat itself. ``folders.json`` next to the chats only keeps EMPTY folders
alive: the folder set is registry ∪ every folder a chat references ∪ their
parents, so losing the registry only loses empty folders.
"""
from __future__ import annotations

import json
import logging

from ghostbrain import routing_config
from ghostbrain.api.repo import chat_store
from ghostbrain.api.repo import projects as projects_repo
from ghostbrain.api.repo.doc_library.scope import InvalidPath, clean_rel
from ghostbrain.paths import chats_dir

log = logging.getLogger("ghostbrain.chat.folders")

Entry = tuple[str, "str | None", str]  # (context, project, path)


class ChatFolderError(Exception):
    status = 422


class InvalidLocation(ChatFolderError):
    status = 422


class FolderNotFound(ChatFolderError):
    status = 404


class FolderExists(ChatFolderError):
    status = 409


class FolderNotEmpty(ChatFolderError):
    status = 409


class ChatNotFound(ChatFolderError):
    status = 404


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


def _registry_path():
    return chats_dir() / "folders.json"


def _registry() -> set[Entry]:
    try:
        raw = json.loads(_registry_path().read_text(encoding="utf-8"))
        return {(f["context"], f.get("project"), f["path"]) for f in raw.get("folders", [])}
    except FileNotFoundError:
        return set()
    except (json.JSONDecodeError, OSError, KeyError, TypeError, AttributeError):
        log.warning("unreadable chat folder registry %s; treating as empty", _registry_path())
        return set()


def _save_registry(entries: set[Entry]) -> None:
    d = chats_dir()
    d.mkdir(parents=True, exist_ok=True)
    target = _registry_path()
    tmp = target.with_name(target.name + ".tmp")
    rows = [{"context": c, "project": p, "path": path} for c, p, path in sorted(entries, key=lambda e: (e[0], e[1] or "", e[2]))]
    tmp.write_text(json.dumps({"folders": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)


def _with_parents(entries) -> set[Entry]:
    out: set[Entry] = set()
    for c, p, path in entries:
        parts = path.split("/")
        for i in range(1, len(parts) + 1):
            out.add((c, p, "/".join(parts[:i])))
    return out


def _all_folders(convs: list[dict] | None = None) -> set[Entry]:
    convs = chat_store.iter_all() if convs is None else convs
    used = {(c["context"], c["project"], c["folder"]) for c in convs if c["context"] and c["folder"]}
    return _with_parents(_registry() | used)


def folder_exists(context: str, project: str | None, path: str) -> bool:
    return (context, project, clean_path(path)) in _all_folders()


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root + "/")


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
        _save_registry({(c, new_slug if (c == context and p == old_slug) else p, path) for c, p, path in _registry()})


def _summary(conv: dict, unknown: bool = False) -> dict:
    return {
        "id": conv["id"], "title": conv["title"], "created_at": conv["created_at"],
        "updated_at": conv["updated_at"], "message_count": len(conv.get("messages", [])),
        "context": conv["context"], "project": conv["project"], "folder": conv["folder"],
        "auto_filed": conv["auto_filed"], "unknown_location": unknown,
    }


def _node(name: str, path: str, entries: set[str], chats_by_folder: dict[str, list[dict]]) -> dict:
    prefix = f"{path}/" if path else ""
    child_names = sorted({e[len(prefix):].split("/", 1)[0] for e in entries if e.startswith(prefix) and e != path and e})
    return {
        "name": name,
        "path": path,
        "folders": [_node(n, f"{prefix}{n}", entries, chats_by_folder) for n in child_names],
        "chats": sorted(chats_by_folder.get(path, []), key=lambda s: s["updated_at"], reverse=True),
    }


def tree() -> dict:
    with chat_store.lock:
        convs = chat_store.iter_all()
        folders = _all_folders(convs)
    contexts = routing_config.contexts()
    projs = projects_repo.list_projects(include_archived=True)
    known = {(p["context"], p["slug"]): p for p in projs}
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

    def scope(ctx: str, proj: str | None, name: str, archived: bool) -> dict:
        entries = {path for c, p, path in folders if (c, p) == (ctx, proj)}
        root = _node(name, "", entries, by_loc.get((ctx, proj), {}))
        return {"context": ctx, "project": proj, "name": name, "archived": archived,
                "folders": root["folders"], "chats": root["chats"]}

    scopes = []
    for ctx in contexts:
        scopes.append(scope(ctx, None, ctx, False))
        for p in sorted((p for p in projs if p["context"] == ctx), key=lambda p: p["name"].lower()):
            s = scope(ctx, p["slug"], p["name"], bool(p.get("archived")))
            if s["archived"] and not s["chats"] and not s["folders"]:
                continue
            scopes.append(s)
    return {"unfiled": unfiled, "scopes": scopes}
