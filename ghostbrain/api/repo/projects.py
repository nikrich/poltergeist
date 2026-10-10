"""Project registry: user-defined routing destinations nested under contexts.

Stored at <vault>/90-meta/projects.json so it syncs with the vault. Atomic
writes (tmp+rename); a corrupt registry reads as empty — routing then degrades
to context-only rather than failing.
"""
from __future__ import annotations

import functools
import json
import logging
import os
import re
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path

import yaml

from ghostbrain import routing_config, vault_write
from ghostbrain.paths import vault_path
from ghostbrain.vault_write import USER, MalformedNote, WriteConflict, compute_etag

log = logging.getLogger("ghostbrain.projects")

REGISTRY_REL = "90-meta/projects.json"
PROJECT_DIR_TEMPLATE = "20-contexts/{context}/projects/{slug}"


class UnknownContext(ValueError):
    pass


class ProjectExists(ValueError):
    pass


class UnknownDesignSystem(ValueError):
    pass


# Default for update/rename's ``design_system``: leave it as is (None clears it).
UNSET = object()


def _check_design_system(design_system) -> None:
    if design_system is UNSET or design_system is None:
        return
    from ghostbrain.design import packs  # function-level: keeps registry imports light

    if packs.get_pack(design_system) is None:
        raise UnknownDesignSystem(f"unknown design system: {design_system!r}")


class ProjectBusy(Exception):
    """A doc of the project is being indexed or summarised; renaming now would
    pull its files out from under the background job."""


class MalformedProjectNote(Exception):
    """A note of the project could not be re-stamped (its frontmatter is not
    valid YAML / does not round-trip). The rename was rolled back."""

    def __init__(self, path: str) -> None:
        super().__init__(f"can't rename: {path} has malformed frontmatter")
        self.path = path


# Serialises registry read-modify-write (create / update / rename). Reentrant:
# rename_project calls update_project for a same-slug edit.
_registry_lock = threading.RLock()


def _with_registry_lock(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with _registry_lock:
            return fn(*args, **kwargs)

    return wrapper


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


@_with_registry_lock
def ensure_project_uuids() -> list[dict]:
    """Give every registry entry a permanent `uuid` (the ontology's key; ids
    change on rename). Writes only when something was missing."""
    items = _read()
    changed = False
    for p in items:
        if not p.get("uuid"):
            p["uuid"] = uuid.uuid4().hex
            changed = True
    if changed:
        _write(items)
    return items


def get_project_by_uuid(project_uuid: str) -> dict | None:
    for p in _read():
        if p.get("uuid") == project_uuid:
            return p
    return None


def get_project(context: str, slug: str, *, active_only: bool = False) -> dict | None:
    for p in _read():
        if p["context"] == context and p["slug"] == slug:
            if active_only and p.get("archived"):
                return None
            return p
    return None


@_with_registry_lock
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
        "uuid": uuid.uuid4().hex,
    }
    items = _read()
    items.append(project)
    _write(items)
    folder = vault_path() / PROJECT_DIR_TEMPLATE.format(context=context, slug=slug)
    folder.mkdir(parents=True, exist_ok=True)
    return project


@_with_registry_lock
def update_project(
    context: str,
    slug: str,
    *,
    name: str | None = None,
    description: str | None = None,
    archived: bool | None = None,
    design_system: str | None | object = UNSET,
) -> dict | None:
    _check_design_system(design_system)
    items = _read()
    for p in items:
        if p["context"] == context and p["slug"] == slug:
            if name is not None:
                p["name"] = name.strip()
            if description is not None:
                p["description"] = description.strip()
            if archived is not None:
                p["archived"] = bool(archived)
            if design_system is not UNSET:
                p["design_system"] = design_system
            _write(items)
            return p
    return None


def _rel(p: Path) -> str:
    return p.relative_to(vault_path()).as_posix()


def _front_project(path: Path) -> str | None:
    """The note's frontmatter ``project`` value, or None when unreadable."""
    front = _front_matter(path)
    return front.get("project") if front else None


def _front_matter(path: Path) -> dict | None:
    """The note's frontmatter mapping, or None when absent or unreadable."""
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
    return front if isinstance(front, dict) else None


def _link_pattern(context: str, slug: str) -> re.Pattern[str]:
    """The project folder path as a whole path segment: preceded by nothing
    path-like, followed by '/', ']', '|', '#', ')' or end of line — so
    ``projects/pay`` never matches ``projects/payments``."""
    prefix = re.escape(PROJECT_DIR_TEMPLATE.format(context=context, slug=slug))
    return re.compile(r"(?<![\w.-])" + prefix + r"(?=[/\]|#)]|$)", re.MULTILINE)


def _rmdir_tree_if_empty(d: Path) -> None:
    """Remove ``d`` and its subfolders, but only when no file is left anywhere in it."""
    if not d.is_dir():
        return
    left = [p for p in d.rglob("*") if not p.is_dir() or p.is_symlink()]
    if left:
        log.warning("%d file(s) left in %s; keeping the folder", len(left), d)
        return
    for sub in sorted((p for p in d.rglob("*")), key=lambda p: len(p.parts), reverse=True):
        sub.rmdir()
    d.rmdir()


def _move_note(
    src: Path, dst: Path, *, fields: dict | None, reason: str, etags: dict[str, str | None]
) -> Callable[[], None]:
    """Move one note through vault_write (history follows it) and return its undo.

    The undo moves the file back and, if the move changed its bytes (project
    re-stamp, ``updated`` bump), restores the original bytes exactly."""
    src_rel, dst_rel = _rel(src), _rel(dst)
    original = src.read_bytes()
    try:
        moved = vault_write.write(
            src_rel, op="move", dest=dst_rel, fields=fields, actor=USER, reason=reason,
            base_etag=compute_etag(original),
        )
    except MalformedNote as exc:
        raise MalformedProjectNote(src_rel) from exc
    etags[dst_rel] = moved.etag

    def undo() -> None:
        # base_etag = the last bytes the rename itself wrote there: a note edited
        # since then stays where it is (the user's edit wins; the conflict is logged).
        back = vault_write.write(
            dst_rel, op="move", dest=src_rel, actor=USER, reason=f"undo {reason}",
            base_etag=etags.get(dst_rel),
        )
        etags[src_rel] = back.etag
        if back.etag != compute_etag(original):
            _restore(src_rel, original, etags=etags, reason=f"undo {reason}")

    return undo


def _restore(rel: str, original: bytes, *, etags: dict[str, str | None], reason: str) -> None:
    """Put back a note's original bytes unless someone changed it since the
    rename last wrote it (``etags[rel]``)."""
    try:
        res = vault_write.write(
            rel, op="modify", content=original.decode("utf-8"), actor=USER, reason=reason,
            base_etag=etags.get(rel),
        )
    except WriteConflict:
        log.warning("not restoring %s: it was edited during the project rename", rel)
        return
    etags[rel] = res.etag


def _iter_vault_notes(root: Path):
    """Every ``.md`` (any case) under the vault, pruning dot-folders and dot-files
    (.obsidian, .trash, writer temp files) and never following symlinks."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for f in sorted(filenames):
            if f.startswith(".") or not f.lower().endswith(".md"):
                continue
            p = Path(dirpath) / f
            if p.is_symlink() or not p.is_file():
                continue
            yield p


def _claimed_originals(old_dir: Path, new_dir: Path) -> frozenset[Path]:
    """Realpaths of every doc-library original in the vault, with those inside
    ``old_dir`` also listed at their post-move location under ``new_dir``.

    Read before the move: the library resolves project scopes through the
    registry, which still names the old slug until the rename's last step."""
    from ghostbrain.api.repo.doc_library import index as library_index

    library_index.invalidate()
    claims = set(library_index.claimed_originals())
    old_real = old_dir.resolve()
    new_real = old_real.parent / new_dir.name
    for c in list(claims):
        if old_real in c.parents:
            claims.add(new_real / c.relative_to(old_real))
    return frozenset(claims)


def _check_not_busy(old_dir: Path) -> None:
    """Refuse when any doc of the project is being indexed or summarised.

    Membership is the folder on disk (doc notes under ``old_dir``). An indexing
    doc the library cannot place yet (an upload whose note is not written) has
    an unknown project, so it blocks too — that window is milliseconds."""
    from ghostbrain.api.repo.doc_library import ai_summary
    from ghostbrain.api.repo.doc_library import index as library_index

    project_ids: set[str] = set()
    if old_dir.is_dir():
        for note in old_dir.rglob("*"):
            if note.suffix.lower() != ".md" or note.is_symlink() or not note.is_file():
                continue
            front = _front_matter(note)
            doc_id = front.get("doc_id") if front else None
            if isinstance(doc_id, str) and doc_id:
                project_ids.add(doc_id)
    active = library_index.active_doc_ids()
    if active - set(library_index.all_docs()):
        raise ProjectBusy("a doc upload is still being indexed")
    for doc_id in project_ids:
        if doc_id in active or ai_summary.is_summarising(doc_id):
            raise ProjectBusy(f"doc {doc_id} is still being indexed or summarised")


@_with_registry_lock
def rename_project(
    context: str,
    slug: str,
    *,
    name: str | None = None,
    description: str | None = None,
    archived: bool | None = None,
    design_system: str | None | object = UNSET,
) -> dict | None:
    """Edit a project; a name whose slug differs is a full rename.

    A full rename moves every file of the project folder to the new slug's
    folder (notes through vault_write so page history follows them, other
    files with os.replace), re-stamps ``project:`` on notes that carried the
    old slug, rewrites vault links into the old folder, repoints chats scoped
    to the project, and updates the registry last. Any failure undoes the
    completed steps in reverse and re-raises.

    Notes edited concurrently keep the user's edit: link rewrites and rollback
    restores carry a base etag and skip the note on WriteConflict.

    Doc-library originals (files a companion note names) keep their bytes:
    they are never re-stamped nor link-rewritten (the library dedupes by hash).

    Returns the updated project, or None when it is unknown. Raises
    ProjectExists when the new slug is taken (registry or folder on disk),
    ProjectBusy when a doc of the project is being indexed or summarised,
    MalformedProjectNote when a note cannot be re-stamped, and ValueError for
    a name without letters or digits. Holds the registry lock throughout.
    """
    current = get_project(context, slug)
    if current is None:
        return None
    _check_design_system(design_system)
    from ghostbrain.api.repo.notes_manual import make_slug  # function-level: import cycle

    if name is not None and not name.strip():
        raise ValueError("project name must not be blank")
    new_name = name.strip() if name is not None else current["name"]
    new_slug = make_slug(new_name) if name is not None else slug
    if not new_slug or (name is not None and not re.search(r"[a-z0-9]", new_name.lower())):
        # make_slug falls back to "untitled" for names with no a-z/0-9.
        raise ValueError("project name must contain a letter or digit")
    if new_slug == slug:
        return update_project(
            context, slug, name=name, description=description, archived=archived,
            design_system=design_system,
        )

    root = vault_path()
    old_dir = root / PROJECT_DIR_TEMPLATE.format(context=context, slug=slug)
    new_dir = root / PROJECT_DIR_TEMPLATE.format(context=context, slug=new_slug)
    if get_project(context, new_slug) is not None or new_dir.exists() or new_dir.is_symlink():
        raise ProjectExists(f"{context}/{new_slug}")
    _check_not_busy(old_dir)
    originals = _claimed_originals(old_dir, new_dir)

    old_id, new_id = f"{context}/{slug}", f"{context}/{new_slug}"
    reason = f"rename project {slug} → {new_slug}"
    undo: list[Callable[[], None]] = []  # run in reverse on failure
    etags: dict[str, str | None] = {}  # rel → etag of the last bytes this rename wrote there
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
                restamp = src.resolve() not in originals and _front_project(src) == slug
                stamp = {"project": new_slug} if restamp else None
                undo.append(_move_note(src, dst, fields=stamp, reason=reason, etags=etags))
            else:
                os.replace(src, dst)
                undo.append(lambda a=dst, b=src: os.replace(a, b))

        # 2. Rewrite inbound links anywhere in the vault (incl. self-links in
        #    the moved notes); dot-folders (.obsidian, .trash, …) are left alone.
        pattern = _link_pattern(context, slug)
        replacement = PROJECT_DIR_TEMPLATE.format(context=context, slug=new_slug)
        for note in _iter_vault_notes(root):
            if note.resolve() in originals:
                continue  # an uploaded .md original keeps its exact bytes
            rel = _rel(note)
            try:
                original = note.read_bytes()
                text = original.decode("utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            updated = pattern.sub(replacement, text)
            if updated == text:
                continue
            try:
                # base_etag = the bytes just read: an edit made in between wins.
                wrote = vault_write.write(
                    rel, op="modify", content=updated, actor=USER, reason=reason,
                    base_etag=compute_etag(original),
                )
            except WriteConflict:
                log.warning("skipped link rewrite in %s: it changed during the project rename", rel)
                continue
            etags[rel] = wrote.etag
            undo.append(lambda r=rel, b=original: _restore(r, b, etags=etags, reason=f"undo {reason}"))

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
                if design_system is not UNSET:
                    p["design_system"] = design_system
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

    try:
        _rmdir_tree_if_empty(old_dir)  # keeps (and warns) if a writer filed into it meanwhile
    except OSError:
        log.exception("could not remove old project folder %s", old_dir)
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
