"""Project registry: user-defined routing destinations nested under contexts.

Stored at <vault>/90-meta/projects.json so it syncs with the vault. Atomic
writes (tmp+rename); a corrupt registry reads as empty — routing then degrades
to context-only rather than failing.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from collections.abc import Callable
from pathlib import Path

import yaml

from ghostbrain import routing_config, vault_write
from ghostbrain.paths import vault_path
from ghostbrain.vault_write import USER

log = logging.getLogger("ghostbrain.projects")

REGISTRY_REL = "90-meta/projects.json"
PROJECT_DIR_TEMPLATE = "20-contexts/{context}/projects/{slug}"


class UnknownContext(ValueError):
    pass


class ProjectExists(ValueError):
    pass


def _registry_path() -> Path:
    return vault_path() / REGISTRY_REL


def _read() -> list[dict]:
    path = _registry_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("unreadable projects registry %s: %s", path, exc)
        return []
    return data if isinstance(data, list) else []


def _write(items: list[dict]) -> None:
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def list_projects(*, include_archived: bool = False) -> list[dict]:
    items = _read()
    if not include_archived:
        items = [p for p in items if not p.get("archived")]
    return items


def get_project(context: str, slug: str, *, active_only: bool = False) -> dict | None:
    for p in _read():
        if p["context"] == context and p["slug"] == slug:
            if active_only and p.get("archived"):
                return None
            return p
    return None


def create_project(context: str, name: str, description: str = "") -> dict:
    # Function-level import to avoid the import cycle:
    # projects → notes_manual → router → projects (Task 3 wires router to projects)
    from ghostbrain.api.repo.notes_manual import make_slug  # noqa: PLC0415

    if context not in routing_config.contexts():
        raise UnknownContext(context)
    slug = make_slug(name)
    if not slug:
        raise ValueError("project name produces an empty slug")
    if get_project(context, slug) is not None:
        raise ProjectExists(f"{context}/{slug}")
    project = {
        "id": f"{context}/{slug}",
        "context": context,
        "slug": slug,
        "name": name.strip(),
        "description": description.strip(),
        "archived": False,
        "created_at": time.time(),
    }
    items = _read()
    items.append(project)
    _write(items)
    folder = vault_path() / PROJECT_DIR_TEMPLATE.format(context=context, slug=slug)
    folder.mkdir(parents=True, exist_ok=True)
    return project


def update_project(
    context: str,
    slug: str,
    *,
    name: str | None = None,
    description: str | None = None,
    archived: bool | None = None,
) -> dict | None:
    items = _read()
    for p in items:
        if p["context"] == context and p["slug"] == slug:
            if name is not None:
                p["name"] = name.strip()
            if description is not None:
                p["description"] = description.strip()
            if archived is not None:
                p["archived"] = bool(archived)
            _write(items)
            return p
    return None


_HIDDEN = re.compile(r"(^|/)\.")


def _rel(p: Path) -> str:
    return p.relative_to(vault_path()).as_posix()


def _front_project(path: Path) -> str | None:
    """The note's frontmatter ``project`` value, or None when unreadable."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    try:
        front = yaml.safe_load(text[4:end])
    except yaml.YAMLError:
        return None
    return front.get("project") if isinstance(front, dict) else None


def _link_pattern(context: str, slug: str) -> re.Pattern[str]:
    """The project folder path as a whole path segment: preceded by nothing
    path-like, followed by '/', ']', '|', '#', ')' or end of line — so
    ``projects/pay`` never matches ``projects/payments``."""
    prefix = re.escape(PROJECT_DIR_TEMPLATE.format(context=context, slug=slug))
    return re.compile(r"(?<![\w.-])" + prefix + r"(?=[/\]|#)]|$)", re.MULTILINE)


def _rmdir_tree_if_empty(d: Path) -> None:
    """Remove ``d`` and its subfolders, but only when no file is left anywhere in it."""
    if not d.is_dir() or any(not p.is_dir() or p.is_symlink() for p in d.rglob("*")):
        return
    for sub in sorted((p for p in d.rglob("*")), key=lambda p: len(p.parts), reverse=True):
        sub.rmdir()
    d.rmdir()


def _move_note(src: Path, dst: Path, *, fields: dict | None, reason: str) -> Callable[[], None]:
    """Move one note through vault_write (history follows it) and return its undo.

    The undo moves the file back and, if the move changed its bytes (project
    re-stamp, ``updated`` bump), restores the original bytes exactly."""
    src_rel, dst_rel = _rel(src), _rel(dst)
    original = src.read_bytes()
    vault_write.write(src_rel, op="move", dest=dst_rel, fields=fields, actor=USER, reason=reason)

    def undo() -> None:
        vault_write.write(dst_rel, op="move", dest=src_rel, actor=USER, reason=f"undo {reason}")
        if src.read_bytes() != original:
            vault_write.write(
                src_rel, op="modify", content=original.decode("utf-8"), actor=USER,
                reason=f"undo {reason}",
            )

    return undo


def rename_project(
    context: str,
    slug: str,
    *,
    name: str | None = None,
    description: str | None = None,
    archived: bool | None = None,
) -> dict | None:
    """Edit a project; a name whose slug differs is a full rename.

    A full rename moves every file of the project folder to the new slug's
    folder (notes through vault_write so page history follows them, other
    files with os.replace), re-stamps ``project:`` on notes that carried the
    old slug, rewrites vault links into the old folder, repoints chats scoped
    to the project, and updates the registry last. Any failure undoes the
    completed steps in reverse and re-raises.

    Returns the updated project, or None when it is unknown. Raises
    ProjectExists when the new slug is taken (registry or folder on disk) and
    ValueError for a blank name.
    """
    current = get_project(context, slug)
    if current is None:
        return None
    from ghostbrain.api.repo.notes_manual import make_slug  # function-level: import cycle

    if name is not None and not name.strip():
        raise ValueError("project name must not be blank")
    new_name = name.strip() if name is not None else current["name"]
    new_slug = make_slug(new_name) if name is not None else slug
    if not new_slug:
        raise ValueError("project name produces an empty slug")
    if new_slug == slug:
        return update_project(context, slug, name=name, description=description, archived=archived)

    root = vault_path()
    old_dir = root / PROJECT_DIR_TEMPLATE.format(context=context, slug=slug)
    new_dir = root / PROJECT_DIR_TEMPLATE.format(context=context, slug=new_slug)
    if get_project(context, new_slug) is not None or new_dir.exists() or new_dir.is_symlink():
        raise ProjectExists(f"{context}/{new_slug}")

    old_id, new_id = f"{context}/{slug}", f"{context}/{new_slug}"
    reason = f"rename project {slug} → {new_slug}"
    undo: list[Callable[[], None]] = []  # run in reverse on failure
    result: dict | None = None
    try:
        # 1. Move the folder's contents. Symlinks move as links (os.replace),
        #    never through vault_write, which would resolve and move the target.
        entries = sorted(old_dir.rglob("*")) if old_dir.is_dir() else []
        new_dir.mkdir(parents=True)
        undo.append(lambda: _rmdir_tree_if_empty(new_dir))
        for src in entries:
            dst = new_dir / src.relative_to(old_dir)
            if src.is_dir() and not src.is_symlink():
                dst.mkdir(parents=True, exist_ok=True)  # keeps empty subfolders
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not src.is_symlink() and src.suffix.lower() in vault_write.WRITABLE_SUFFIXES:
                stamp = {"project": new_slug} if _front_project(src) == slug else None
                undo.append(_move_note(src, dst, fields=stamp, reason=reason))
            else:
                os.replace(src, dst)
                undo.append(lambda a=dst, b=src: os.replace(a, b))

        # 2. Rewrite inbound links anywhere in the vault (incl. self-links in
        #    the moved notes); dot-folders (.obsidian, .trash, …) are left alone.
        pattern = _link_pattern(context, slug)
        replacement = PROJECT_DIR_TEMPLATE.format(context=context, slug=new_slug)
        for note in sorted(root.rglob("*.md")):
            rel = _rel(note)
            if _HIDDEN.search(rel) or note.is_symlink() or not note.is_file():
                continue
            try:
                text = note.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            updated = pattern.sub(replacement, text)
            if updated != text:
                original = note.read_bytes()
                vault_write.write(rel, op="modify", content=updated, actor=USER, reason=reason)
                undo.append(lambda r=rel, b=original: vault_write.write(
                    r, op="modify", content=b.decode("utf-8"), actor=USER, reason=f"undo {reason}"))

        # 3. Chats scoped to the project.
        from ghostbrain.api.repo import chat_store

        for conv in chat_store.list_all():
            if conv.get("project") == old_id:
                chat_store.update(conv["id"], project=new_id)
                undo.append(lambda cid=conv["id"]: chat_store.update(cid, project=old_id))

        # 4. Registry last.
        items = _read()
        for p in items:
            if p["context"] == context and p["slug"] == slug:
                p.update(slug=new_slug, id=new_id, name=new_name)
                if description is not None:
                    p["description"] = description.strip()
                if archived is not None:
                    p["archived"] = bool(archived)
                result = dict(p)
        if result is None:
            raise LookupError(f"project {old_id} vanished from the registry mid-rename")
        _write(items)
    except Exception:
        for fn in reversed(undo):
            try:
                fn()
            except Exception:  # best-effort rollback; the original error wins
                log.exception("project rename rollback step failed")
        raise
    finally:
        from ghostbrain.api.repo.doc_library import index as library_index

        library_index.invalidate()

    _rmdir_tree_if_empty(old_dir)
    return result


def active_destinations() -> list[str]:
    """Routing destinations: bare contexts + 'context/slug' for active projects."""
    dests = list(routing_config.contexts())
    dests.extend(p["id"] for p in list_projects())
    return dests


def project_prompt_lines() -> list[str]:
    """'context/slug — Name: description' lines for the router prompt."""
    out = []
    for p in list_projects():
        desc = f": {p['description']}" if p["description"] else ""
        out.append(f"{p['id']} — {p['name']}{desc}")
    return out
