"""The single vault write path: lock → etag check → minimal-diff bytes →
hold check → history snapshot → atomic replace → change row (spec B §1;
snapshot from spec A3, change log from slice B2).

Every write by an actor other than ``user`` / ``restore`` gets a row in the
change log (``ghostbrain.changes``), except a ``worker:*`` create, which is
connector ingest and stays audit-only (user decision 2026-10-09). The B3 risk
rules (``risk.evaluate``) are the default hold policy; a held
change is stored as a pending row and nothing is written.
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
from typing import Any, Callable, Iterator, Literal, Mapping

import ghostbrain.paths as _paths
from ghostbrain.changes import log as _changes
from ghostbrain.history import store as _history_store
from ghostbrain.history.store import HistoryUnavailable, Snapshot
from ghostbrain.vault_write.actor import RESTORE, USER, Actor, parse_actor
from ghostbrain.vault_write.errors import (
    EtagRequired,
    FileMissing,
    InvalidPath,
    MalformedNote,
    WriteConflict,
)
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
    # False only when a *user* write went through without its history
    # snapshot (spec A3: the save proceeds, the renderer toasts once).
    history_ok: bool = True


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


def _content_bytes(path: Path, content: str, *, verbatim: bool = False) -> bytes:
    if not verbatim and path.suffix.lower() == ".md" and not content.endswith("\n"):
        content += "\n"
    return content.encode("utf-8")


def _edit_bytes(
    current: bytes,
    *,
    body: str | None,
    fields: Mapping[str, Any] | None,
    suffix: str,
    bump_updated: bool = True,
) -> tuple[bytes, str | None]:
    parsed = parse_note(_decode(current))
    edits = dict(fields or {})
    updated = edits["updated"] if isinstance(edits.get("updated"), str) else None
    if (
        bump_updated
        and "updated" not in edits
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
    verbatim: bool = False,
    bump_updated: bool = True,
    approved_change: int | None = None,
) -> WriteResult:
    result = _write(
        rel_path, actor=actor, content=content, body=body, fields=fields,
        op=op, dest=dest, reason=reason, base_etag=base_etag, verbatim=verbatim,
        bump_updated=bump_updated,
        approved_change=approved_change,
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


@dataclass(frozen=True)
class ProposedChange:
    """What a non-user write is about to do (spec B §3 input; B3 reads it)."""

    actor: Actor
    op: Op
    rel_path: str
    dest_path: str | None
    before: bytes | None
    after: bytes | None
    reason: str
    # The caller's own spelling of the paths, before symlinks are resolved: a
    # protected name that is a symlink to a plain note is still judged by it.
    requested: tuple[str, ...] = ()


HoldPolicy = Callable[[ProposedChange], list[str]]


def _risk_rules(change: ProposedChange) -> list[str]:
    from ghostbrain.vault_write.risk import evaluate  # risk imports this module

    return evaluate(change)


_hold_policy: HoldPolicy = _risk_rules


def set_hold_policy(policy: HoldPolicy | None) -> None:
    """Swap the hold policy (tests). ``None`` restores the default: the B3
    risk rules (spec B §3). A reset can never leave the vault unguarded."""
    global _hold_policy
    _hold_policy = policy or _risk_rules


# Derived metadata refreshed in bulk (semantic `related:` links, every 15
# minutes). Listing each would bury the Changes screen, the same reason
# connector ingest is unlisted (decision 1); page history still keeps them.
UNLISTED_ACTORS: frozenset[str] = frozenset({"worker:semantic-refresh"})


def records_change(actor: Actor, op: Op) -> bool:
    """Spec B §1 step 7: user (and restore) writes get no row. A worker
    *creating* a note is connector ingest: audit log only (decision 1).
    Unlisted derived-metadata jobs get page history only (slice B4)."""
    if actor in (USER, RESTORE) or actor in UNLISTED_ACTORS:
        return False
    return not (actor.startswith("worker:") and op == "create")


def needs_base_etag(actor: Actor) -> bool:
    """Spec B §1: base_etag is required for actor != worker when op != create.
    User writes keep it optional; restore checks its own expectations."""
    return actor not in (USER, RESTORE) and not actor.startswith("worker:")


def _require_base(rel: str, current: bytes, *, actor: Actor, etag_now: str | None) -> None:
    """No base_etag: allowed only when the file still holds exactly what this
    actor last wrote there (a plugin re-upserting its own note)."""
    if not needs_base_etag(actor):
        return
    try:
        own = _changes.last_after_blob(rel, actor)
    except Exception:  # noqa: BLE001 — unknown history: fail closed
        log.warning("change log unavailable; refusing an etag-less %s write to %s", actor, rel)
        own = None
    if own is None or own != _history_store.blob_id(current):
        raise EtagRequired(etag_now)


def _put_blob(data: bytes) -> str:
    try:
        return _history_store.put_blob(data)
    except Exception as e:  # noqa: BLE001 — a non-user write must stay revertible
        raise HistoryUnavailable(f"history unavailable: {e}") from e


def _hold_reasons(proposed: ProposedChange) -> list[str]:
    try:
        return [str(r) for r in _hold_policy(proposed)]
    except Exception:  # noqa: BLE001 — a broken rule must not let a change through
        log.exception("hold policy failed for %s; holding the change", proposed.rel_path)
        return ["risk check failed"]


def _hold(proposed: ProposedChange, reasons: list[str]) -> WriteResult:
    """B3 path: keep the proposal as a pending row; write nothing."""
    before_blob = _put_blob(proposed.before) if proposed.before is not None else None
    pending_blob = _put_blob(proposed.after) if proposed.after is not None else None
    try:
        cid = _changes.record(
            actor=proposed.actor, rel_path=proposed.rel_path, op=proposed.op,
            reason=proposed.reason, before_blob=before_blob, dest_path=proposed.dest_path,
            status="pending", pending_bytes_blob=pending_blob, risk_reasons=reasons,
        )
    except Exception as e:  # noqa: BLE001 — cannot hold → refuse, file untouched
        raise HistoryUnavailable(f"history unavailable: {e}") from e
    etag = compute_etag(proposed.before) if proposed.before is not None else None
    return WriteResult("pending", str(cid), etag, proposed.rel_path, None)


def _record(
    proposed: ProposedChange, *, before_blob: str | None, after_blob: str | None
) -> str | None:
    """Spec B error handling: an insert failure after the write leaves the
    write standing (the snapshot exists) and raises the degraded banner."""
    try:
        cid = _changes.record(
            actor=proposed.actor, rel_path=proposed.rel_path, op=proposed.op,
            reason=proposed.reason, before_blob=before_blob, after_blob=after_blob,
            dest_path=proposed.dest_path,
        )
    except Exception as e:  # noqa: BLE001
        log.exception("change log insert failed for %s; the write stands", proposed.rel_path)
        _changes.mark_degraded(f"change to {proposed.rel_path} not recorded: {e}")
        return None
    return str(cid)


def _mark_approved(
    change_id: int, *, before_blob: str | None, after_blob: str | None, path: str
) -> str:
    """B3: the approved pending row becomes the applied row (no second row).
    Like ``_record``, a failure here leaves the write standing."""
    try:
        ok = _changes.apply_pending(change_id, before_blob=before_blob, after_blob=after_blob)
    except Exception as e:  # noqa: BLE001
        log.exception("could not mark change #%s applied", change_id)
        _changes.mark_degraded(f"approved change #{change_id} to {path} not marked: {e}")
        return str(change_id)
    if not ok:
        log.warning("change #%s was no longer pending when its approval landed", change_id)
        _changes.mark_degraded(f"approved change #{change_id} to {path} was not pending")
    return str(change_id)


def _check_approved(change_id: int, *, actor: Actor, op: Op, src_rel: str, dst_rel: str | None) -> None:
    """B3: ``approved_change`` skips the hold, so it must name this very
    write's pending row. Anything else, or an unreadable log, refuses."""
    try:
        row = _changes.get(change_id)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"cannot check approved change #{change_id}: {e}") from e
    if row is None or row.status != "pending" or row.actor != actor:
        raise ValueError(f"change #{change_id} is not this actor's pending change")
    same = src_rel == row.rel_path and dst_rel == row.dest_path
    # A forced approval of a move whose source vanished creates at the destination.
    at_dest = op == "create" and dst_rel is None and src_rel == row.current_path
    if not (same or at_dest):
        raise ValueError(f"change #{change_id} is for another path")


def _snapshot(
    rel: str, before: bytes, *, actor: Actor, reason: str, after: bytes | None
) -> tuple[Snapshot | None, bool]:
    """Spec A3 / B §1 step 5. Returns (snapshot, or None when coalesced; ok).
    A user save survives a history failure (ok=False). Any other actor's
    write is refused, because it must stay revertible."""
    try:
        return _history_store.snapshot(rel, before, actor=actor, reason=reason, after=after), True
    except Exception as e:  # noqa: BLE001
        if actor == USER:
            log.exception("history snapshot failed for %s; the user save proceeds", rel)
            return None, False
        raise HistoryUnavailable(f"history unavailable: {e}") from e


def _move_history(src_rel: str, dst_rel: str) -> bool:
    """The file already moved; history following it is best-effort."""
    try:
        _history_store.move_log(src_rel, dst_rel)
        return True
    except Exception:  # noqa: BLE001
        log.exception("history did not follow %s -> %s", src_rel, dst_rel)
        return False


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
    verbatim: bool = False,
    bump_updated: bool = True,
    approved_change: int | None = None,
) -> WriteResult:
    actor = parse_actor(actor)
    _check_args(op, content, body, fields, dest)
    if approved_change is not None and not records_change(actor, op):
        raise ValueError("only a change the log records can be approved")
    src = resolve_safe(rel_path)
    dst = resolve_safe(dest) if dest is not None else None
    if dst is not None and dst == src:
        raise ValueError("move destination equals the source")
    log.debug("vault write op=%s path=%s actor=%s reason=%s", op, rel_path, actor, reason)
    with _locked(src, *([dst] if dst is not None else [])):
        if approved_change is not None:
            _check_approved(approved_change, actor=actor, op=op, src_rel=_rel(src),
                            dst_rel=_rel(dst) if dst is not None else None)
        current = _read_bytes(src)
        etag_now = compute_etag(current) if current is not None else None
        if base_etag is not None and base_etag != etag_now:
            raise WriteConflict(etag_now)
        src_rel = _rel(src)
        dst_rel = _rel(dst) if dst is not None else None
        updated: str | None = None
        data: bytes | None
        if op == "create":
            if current is not None:
                raise WriteConflict(etag_now)
            assert content is not None
            data = _content_bytes(src, content, verbatim=verbatim)
        else:
            if current is None:
                raise FileMissing(rel_path)
            if base_etag is None:
                _require_base(src_rel, current, actor=actor, etag_now=etag_now)
            if op == "delete":
                data = None
            elif content is not None:
                data = _content_bytes(dst or src, content, verbatim=verbatim)
            elif body is not None or fields:
                data, updated = _edit_bytes(
                    current, body=body, fields=fields, suffix=src.suffix, bump_updated=bump_updated,
                )
            else:
                data = current  # plain move
        if dst is not None:
            existing = _read_bytes(dst)
            if existing is not None:
                raise WriteConflict(compute_etag(existing))
        if op == "modify" and data == current:
            return WriteResult("applied", None, etag_now, src_rel, updated)
        proposed = ProposedChange(
            actor, op, src_rel, dst_rel, current, data, reason,
            requested=(rel_path, *([dest] if dest is not None else [])),
        )
        recorded = records_change(actor, op)
        if recorded and approved_change is None:
            reasons = _hold_reasons(proposed)
            if reasons:
                return _hold(proposed, reasons)  # held: nothing is written
        history_ok = True
        before_blob: str | None = None
        if current is not None:
            snap, history_ok = _snapshot(src_rel, current, actor=actor, reason=reason, after=data)
            if recorded:
                before_blob = snap.blob if snap is not None else _put_blob(current)
        after_blob = _put_blob(data) if recorded and data is not None else None
        if data is None:
            src.unlink()
        elif dst is not None:
            assert dst_rel is not None
            _atomic_write(dst, data)
            src.unlink()
            history_ok = _move_history(src_rel, dst_rel) and history_ok
        else:
            _atomic_write(src, data)
        change_id: str | None
        if approved_change is not None:
            change_id = _mark_approved(
                approved_change, before_blob=before_blob, after_blob=after_blob, path=src_rel,
            )
        elif recorded:
            change_id = _record(proposed, before_blob=before_blob, after_blob=after_blob)
        else:
            change_id = None
        etag = compute_etag(data) if data is not None else None
        return WriteResult("applied", change_id, etag, dst_rel or src_rel, updated, history_ok)


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
