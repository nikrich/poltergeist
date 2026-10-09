"""The single vault write path: lock → etag check → minimal-diff bytes →
atomic replace (spec B §1).

B2 adds the history snapshot + change record and B3 the risk hold, both at
the marked hook point inside ``write``. That is why ``actor`` is required and
``reason`` accepted now, though B1 stores neither.
"""
from __future__ import annotations

import contextlib
import logging
import os
import stat
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Literal, Mapping

import ghostbrain.paths as _paths
from ghostbrain.vault_write.actor import Actor, parse_actor
from ghostbrain.vault_write.errors import FileMissing, InvalidPath, MalformedNote, WriteConflict
from ghostbrain.vault_write.etag import compute_etag
from ghostbrain.vault_write.text import (
    ParsedNote,
    apply_fields,
    find_key_block,
    lines_of,
    load_metadata,
    parse_note,
    splice_body,
)

log = logging.getLogger("ghostbrain.vault_write")

Op = Literal["create", "modify", "delete", "move"]
_OPS = ("create", "modify", "delete", "move")
WRITABLE_SUFFIXES: tuple[str, ...] = (".md", ".html")
NEW_FILE_MODE = 0o644


@dataclass(frozen=True)
class WriteResult:
    status: Literal["applied", "pending"]
    change_id: str | None
    etag: str | None
    path: str
    updated: str | None


@dataclass(frozen=True)
class NoteSnapshot:
    path: str
    etag: str
    parsed: ParsedNote

    @property
    def body(self) -> str:
        return self.parsed.body.strip()

    def metadata(self) -> dict[str, Any]:
        return load_metadata(self.parsed)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _root() -> Path:
    return _paths.vault_path().resolve()


def resolve_safe(rel_path: str, *, suffixes: tuple[str, ...] = WRITABLE_SUFFIXES) -> Path:
    """The house guard: vault-relative, no traversal, stays under the root,
    allowed suffix."""
    if not rel_path or rel_path.startswith("/") or "\x00" in rel_path:
        raise InvalidPath("path must be vault-relative")
    candidate = Path(rel_path)
    if candidate.is_absolute() or any(part == ".." for part in candidate.parts):
        raise InvalidPath("path must not contain '..' or be absolute")
    root = _root()
    target = (root / candidate).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise InvalidPath("path escapes the vault root") from None
    if target.suffix.lower() not in suffixes:
        raise InvalidPath(f"only {', '.join(suffixes)} files are allowed")
    return target


def _rel(path: Path) -> str:
    return path.relative_to(_root()).as_posix()


# Per-path locks. One sidecar process owns all writes (scheduler + worker run
# in-process), so a threading.Lock per resolved path is the whole story. The
# map only grows by paths actually written — small.
_registry_lock = threading.Lock()
_path_locks: dict[str, threading.Lock] = {}


@contextlib.contextmanager
def _locked(*paths: Path) -> Iterator[None]:
    keys = sorted({os.path.normcase(str(p)) for p in paths})  # fixed order: no deadlock on move
    with _registry_lock:
        locks = [_path_locks.setdefault(k, threading.Lock()) for k in keys]
    for lock in locks:
        lock.acquire()
    try:
        yield
    finally:
        for lock in reversed(locks):
            lock.release()


def _read_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise MalformedNote(f"file is not valid UTF-8: {e}") from None


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        mode = NEW_FILE_MODE
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)  # mkstemp creates 0600; keep the note's own mode
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def _content_bytes(path: Path, content: str) -> bytes:
    if path.suffix.lower() == ".md" and not content.endswith("\n"):
        content += "\n"
    return content.encode("utf-8")


def _edit_bytes(
    current: bytes, *, body: str | None, fields: Mapping[str, Any] | None, suffix: str
) -> tuple[bytes, str | None]:
    parsed = parse_note(_decode(current))
    edits = dict(fields or {})
    updated = edits["updated"] if isinstance(edits.get("updated"), str) else None
    if (
        "updated" not in edits
        and parsed.has_frontmatter
        and find_key_block(lines_of(parsed.fm_inner), "updated") is not None
    ):
        try:
            load_metadata(parsed)
        except MalformedNote:
            log.warning("skipping `updated` bump: frontmatter is not valid YAML")
        else:
            updated = _now_iso()
            edits["updated"] = updated
    if body is not None:
        parsed = splice_body(parsed, body, ensure_newline=suffix.lower() == ".md")
    if edits:
        parsed = apply_fields(parsed, edits)
    return parsed.render().encode("utf-8"), updated


def _check_args(
    op: str, content: str | None, body: str | None, fields: Mapping[str, Any] | None, dest: str | None
) -> None:
    if op not in _OPS:
        raise ValueError(f"unknown op: {op!r}")
    if content is not None and (body is not None or fields):
        raise ValueError("content is a full replacement; do not combine it with body/fields")
    if (dest is not None) != (op == "move"):
        raise ValueError("dest is required for op='move' and only allowed there")
    if op == "create" and content is None:
        raise ValueError("op='create' needs content")
    if op == "delete" and (content is not None or body is not None or fields):
        raise ValueError("op='delete' takes no content/body/fields")
    if op == "move" and content is not None:
        raise ValueError("op='move' takes body/fields, not content")
    if op == "modify" and content is None and body is None and not fields:
        raise ValueError("op='modify' needs content, body or fields")


def write(
    rel_path: str,
    *,
    actor: Actor,
    content: str | None = None,
    body: str | None = None,
    fields: Mapping[str, Any] | None = None,
    op: Op = "modify",
    dest: str | None = None,
    reason: str = "",
    base_etag: str | None = None,
) -> WriteResult:
    result = _write(
        rel_path, actor=actor, content=content, body=body, fields=fields,
        op=op, dest=dest, reason=reason, base_etag=base_etag,
    )
    _reindex(result.path, *([rel_path] if dest is not None else []))
    return result


def _reindex(*rel_paths: str) -> None:
    """Tell the in-memory link index (A2) about a finished write, outside the
    file lock. Only touches an index this process already built; never raises."""
    try:
        from ghostbrain.vault_index.links import note_written

        for rel in rel_paths:
            note_written(rel)
    except Exception:  # noqa: BLE001 — indexing must never fail a write
        log.exception("link index update failed after write")


def _write(
    rel_path: str,
    *,
    actor: Actor,
    content: str | None = None,
    body: str | None = None,
    fields: Mapping[str, Any] | None = None,
    op: Op = "modify",
    dest: str | None = None,
    reason: str = "",
    base_etag: str | None = None,
) -> WriteResult:
    actor = parse_actor(actor)
    _check_args(op, content, body, fields, dest)
    src = resolve_safe(rel_path)
    dst = resolve_safe(dest) if dest is not None else None
    if dst is not None and dst == src:
        raise ValueError("move destination equals the source")
    log.debug("vault write op=%s path=%s actor=%s reason=%s", op, rel_path, actor, reason)
    with _locked(src, *([dst] if dst is not None else [])):
        current = _read_bytes(src)
        etag_now = compute_etag(current) if current is not None else None
        if base_etag is not None and base_etag != etag_now:
            raise WriteConflict(etag_now)
        # B2/B3 hook point: risk check (→ pending), history snapshot, change row.
        if op == "create":
            if current is not None:
                raise WriteConflict(etag_now)
            assert content is not None
            data = _content_bytes(src, content)
            _atomic_write(src, data)
            return WriteResult("applied", None, compute_etag(data), _rel(src), None)
        if current is None:
            raise FileMissing(rel_path)
        if op == "delete":
            src.unlink()
            return WriteResult("applied", None, None, _rel(src), None)
        updated: str | None = None
        if content is not None:
            data = _content_bytes(src, content)
        elif body is not None or fields:
            data, updated = _edit_bytes(current, body=body, fields=fields, suffix=src.suffix)
        else:
            data = current  # plain move
        if dst is not None:
            existing = _read_bytes(dst)
            if existing is not None:
                raise WriteConflict(compute_etag(existing))
            _atomic_write(dst, data)
            src.unlink()
            return WriteResult("applied", None, compute_etag(data), _rel(dst), updated)
        if data != current:
            _atomic_write(src, data)
        return WriteResult("applied", None, compute_etag(data), _rel(src), updated)


def write_new(
    rel_path: str, content: str, *, actor: Actor, reason: str = "", max_attempts: int = 100
) -> WriteResult:
    """Create ``rel_path``; if taken, ``<stem>-2<suffix>``, ``-3``, … Never
    overwrites (generated docs, chat attachments)."""
    p = PurePosixPath(rel_path)
    for n in range(1, max_attempts + 1):
        candidate = rel_path if n == 1 else str(p.with_name(f"{p.stem}-{n}{p.suffix}"))
        try:
            return write(candidate, content=content, op="create", actor=actor, reason=reason)
        except WriteConflict:
            continue
    raise WriteConflict(None, f"no free file name near {rel_path!r} after {max_attempts} attempts")


def current_etag(rel_path: str, *, suffixes: tuple[str, ...] = WRITABLE_SUFFIXES) -> str | None:
    data = _read_bytes(resolve_safe(rel_path, suffixes=suffixes))
    return compute_etag(data) if data is not None else None


def read(rel_path: str, *, suffixes: tuple[str, ...] = WRITABLE_SUFFIXES) -> NoteSnapshot:
    path = resolve_safe(rel_path, suffixes=suffixes)
    data = _read_bytes(path)
    if data is None:
        raise FileMissing(rel_path)
    return NoteSnapshot(_rel(path), compute_etag(data), parse_note(_decode(data)))
