# ghostbrain/api/repo/doc_library/index.py
"""In-memory doc index, rebuilt when any docs-root directory mtime changes (spec §2)."""
from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from ghostbrain.api.repo import projects
from ghostbrain.api.repo.doc_library import notes, scope
from ghostbrain.api.repo.doc_library.errors import NotFound
from ghostbrain.paths import vault_path

_EXCERPT_CHARS = 240


@dataclass(frozen=True)
class DocEntry:
    doc_id: str
    note: Path
    original: Path
    front: dict
    body: str
    context: str
    project: str | None
    folder: str


_lock = threading.Lock()
_cache: dict = {"sig": None, "docs": {}, "orphans": {}, "attention": [], "claims": frozenset()}


def invalidate() -> None:
    with _lock:
        _cache["sig"] = None


# doc_ids whose extraction is running in THIS process. A `pending` note not in this
# set was orphaned by a dead sidecar and is reported as `failed` (retry via reindex).
_active: set[str] = set()
_active_lock = threading.Lock()


def mark_active(doc_id: str) -> None:
    with _active_lock:
        _active.add(doc_id)
    invalidate()


def unmark_active(doc_id: str) -> None:
    with _active_lock:
        _active.discard(doc_id)
    invalidate()


def _is_active(doc_id: str) -> bool:
    with _active_lock:
        return doc_id in _active


def _walk_dirs(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        yield Path(dirpath), sorted(f for f in filenames if not f.startswith("."))


def _inside(real_vault: Path, p: Path) -> bool:
    """True when `p`'s realpath lives inside the vault's realpath (symlink guard)."""
    try:
        real = p.resolve()
    except (OSError, RuntimeError):
        return False
    return real == real_vault or real_vault in real.parents


def _usable_root(real_vault: Path, root: Path) -> bool:
    return root.is_dir() and _inside(real_vault, root)


def _signature() -> tuple:
    sig: list = [str(vault_path())]
    real_vault = vault_path().resolve()
    for ctx, proj, root in scope.all_scopes():
        sig.append((ctx, proj))
        if _usable_root(real_vault, root):
            sig.extend((str(d), d.stat().st_mtime_ns) for d, _ in _walk_dirs(root))
    return tuple(sig)


def _is_bare_name(name: str) -> bool:
    """A companion note's `original` must be a plain filename inside its own folder."""
    return (
        bool(name)
        and not name.startswith(".")
        and "/" not in name
        and "\\" not in name
        and name == Path(name).name
    )


def _as_int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _scan() -> tuple[dict[str, DocEntry], dict[str, Path], list[dict], frozenset[Path]]:
    """docs, orphan notes, attention items, and the realpaths of every original any
    note (doc or orphan) names — adopt must never hand one of those to a second note."""
    docs: dict[str, DocEntry] = {}
    orphans: dict[str, Path] = {}
    attention: list[dict] = []
    claims: set[Path] = set()
    real_vault = vault_path().resolve()
    for ctx, proj, root in scope.all_scopes():
        if not _usable_root(real_vault, root):
            continue  # missing, or a symlink resolving outside the vault
        claimed: set[Path] = set()
        others: list[tuple[Path, str]] = []
        for d, files in _walk_dirs(root):
            folder = scope.rel_folder(root, d)
            for name in files:
                p = d / name
                inside = _inside(real_vault, p)
                parsed = notes.read_note(p) if name.endswith(".md") else None
                if parsed is None:
                    if inside:  # a symlink out of the vault is not a library file
                        others.append((p, folder))
                    continue
                front, body = parsed
                doc_id = str(front.get("doc_id") or "")
                if not doc_id:
                    continue
                item = {"context": ctx, "project": proj, "folder": folder, "doc_id": doc_id}
                name_ = str(front.get("original") or "")
                original = d / name_ if _is_bare_name(name_) else None
                if original is not None and original.is_file() and _inside(real_vault, original):
                    claims.add(original.resolve())
                else:
                    original = None
                if (
                    original is None
                    or not inside
                    or doc_id in docs
                    or original in claimed
                ):
                    # Unusable original, a note outside the vault, a duplicate doc_id or
                    # a second note naming an already-claimed original (first-seen wins):
                    # this note is an orphan and claims nothing new.
                    orphans[doc_id] = p
                    attention.append({"kind": "orphan_note", "name": p.name, **item})
                    continue
                claimed.add(original)
                if front.get("index_status") == "pending" and not _is_active(doc_id):
                    front = {**front, "index_status": "failed"}  # stale: nothing is finishing it
                docs[doc_id] = DocEntry(doc_id, p, original, front, body, ctx, proj, folder)
                if front.get("index_status") == "failed":
                    attention.append({"kind": "index_failed", "name": original.name, **item})
        for p, folder in others:
            try:
                taken = p.resolve() in claims
            except (OSError, RuntimeError):
                taken = False
            if p not in claimed and not taken:
                attention.append({
                    "kind": "unclaimed_original", "context": ctx, "project": proj,
                    "folder": folder, "name": p.name, "doc_id": None,
                })
    return docs, orphans, attention, frozenset(claims)


def _state() -> dict:
    with _lock:
        sig = _signature()
        if _cache["sig"] != sig:
            docs, orphans, attention, claims = _scan()
            _cache.update(sig=sig, docs=docs, orphans=orphans, attention=attention, claims=claims)
        return dict(_cache)


def all_docs() -> dict[str, DocEntry]:
    return _state()["docs"]


def orphans() -> dict[str, Path]:
    return _state()["orphans"]


def attention() -> list[dict]:
    return _state()["attention"]


def claimed_originals() -> frozenset[Path]:
    """Realpaths of originals named by any companion note, including orphan notes."""
    return _state()["claims"]


def get(doc_id: str) -> DocEntry:
    e = all_docs().get(doc_id)
    if e is None:
        raise NotFound(f"doc not found: {doc_id}")
    return e


def _vault_rel(p: Path) -> str:
    # The scan only admits paths inside the vault, but this feeds /tree and /search,
    # so it must never raise: fall back to the lexical path, then the bare name.
    try:
        return p.resolve().relative_to(vault_path().resolve()).as_posix()
    except (OSError, RuntimeError, ValueError):
        try:
            return p.relative_to(vault_path()).as_posix()
        except ValueError:
            return p.name


def summary(e: DocEntry) -> dict:
    from ghostbrain.api.repo.doc_library import ai_summary  # noqa: PLC0415 — avoids an import cycle

    f = e.front
    created = f.get("created", "")
    raw = f.get("summary")
    text = str(raw).strip() if isinstance(raw, str) and raw.strip() else None
    state = "pending" if ai_summary.is_summarising(e.doc_id) else ("done" if text else "none")
    return {
        "doc_id": e.doc_id,
        "title": str(f.get("title") or e.original.stem),
        "kind": str(f.get("kind") or "opaque"),
        "mime": str(f.get("mime") or ""),
        "size": _as_int(f.get("size")) or 0,
        "created": created.isoformat() if hasattr(created, "isoformat") else str(created),
        "context": e.context,
        "project": e.project,
        "folder": e.folder,
        "original": e.original.name,
        "original_path": _vault_rel(e.original),
        "note_path": _vault_rel(e.note),
        "index_status": str(f.get("index_status") or "ok"),
        "pages": _as_int(f.get("pages")),
        "excerpt": re.sub(r"\s+", " ", e.body).strip()[:_EXCERPT_CHARS],
        "summary": text,
        "summary_state": state,
    }


def detail(e: DocEntry) -> dict:
    return {**summary(e), "body": e.body}


def _folder_node(
    root: Path, rel: str, name: str, by_folder: dict[str, list[dict]], real_vault: Path
) -> dict:
    d = root / rel if rel else root
    children = []
    if d.is_dir() and _inside(real_vault, d):
        subdirs = sorted(
            (c for c in d.iterdir() if c.is_dir() and not c.name.startswith(".")),
            key=lambda c: c.name.lower(),
        )
        for c in subdirs:
            crel = f"{rel}/{c.name}" if rel else c.name
            children.append(_folder_node(root, crel, c.name, by_folder, real_vault))
    docs = sorted(by_folder.get(rel, []), key=lambda s: s["title"].lower())
    return {"name": name, "path": rel, "folders": children, "docs": docs}


def tree(context: str | None = None, project: str | None = None) -> dict:
    state = _state()
    real_vault = vault_path().resolve()
    scopes = []
    for ctx, proj, root in scope.all_scopes():
        if context and ctx != context:
            continue
        if project and proj != project:
            continue
        by_folder: dict[str, list[dict]] = {}
        for e in state["docs"].values():
            if e.context == ctx and e.project == proj:
                by_folder.setdefault(e.folder, []).append(summary(e))
        meta = projects.get_project(ctx, proj) if proj else None
        node = _folder_node(root, "", "", by_folder, real_vault)
        scopes.append({
            "context": ctx,
            "project": proj,
            "name": meta["name"] if meta else "unfiled",
            "archived": bool(meta and meta.get("archived")),
            "folders": node["folders"],
            "docs": node["docs"],
        })
    keep = {(s["context"], s["project"]) for s in scopes}
    items = [a for a in state["attention"] if (a["context"], a["project"]) in keep]
    return {"scopes": scopes, "attention": items}
