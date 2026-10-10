"""Page history store (spec 2026-10-09-confluence-editor-design.md, slice A3;
shared with spec B's change log and revert).

Layout under ``history_dir()`` (= ``state_dir()/history``: app state, never
the vault):

    blobs/<sha256>.md        whole-file bytes, content-addressed (dedupe)
    notes/<sha1(rel)>.jsonl  one line per snapshot, oldest first
    notes/<sha1(rel)>.head   JSON {"ts", "actor", "after"}: the last kept
                             snapshot and the sha256 of the bytes the last
                             write through the app left on disk

A snapshot is the version of a note *just before* a write by ``actor``.
User snapshots coalesce (one per ``USER_COALESCE``) only while the disk still
holds exactly what our previous user write produced: a foreign edit in
between (Obsidian, Keep mine) is always kept.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import ghostbrain.paths as _paths

log = logging.getLogger("ghostbrain.history")

USER_COALESCE = timedelta(minutes=5)
# Same literal as ghostbrain.vault_write.USER; not imported, because
# vault_write imports this module.
_USER = "user"
_BLOB_RE = re.compile(r"[0-9a-f]{64}")
# One sidecar process owns every write (scheduler + worker run in-process).
# Re-entrant: snapshot() holds it while calling put_blob().
_lock = threading.RLock()


class HistoryError(Exception):
    """Base class for history-store failures."""


class HistoryUnavailable(HistoryError):
    """The store could not record or read history (disk, permissions)."""


class BlobNotFound(HistoryError):
    """No blob with that id (never stored, or garbage-collected)."""


@dataclass(frozen=True)
class Snapshot:
    ts: str  # ISO-8601, UTC
    rel_path: str  # vault-relative path at snapshot time
    blob: str  # sha256 hex of the stored bytes
    actor: str  # who was about to write
    reason: str
    size: int  # bytes

    @property
    def when(self) -> datetime:
        return datetime.fromisoformat(self.ts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts, "rel_path": self.rel_path, "blob": self.blob,
            "actor": self.actor, "reason": self.reason, "size": self.size,
        }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def history_dir() -> Path:
    return _paths.state_dir() / "history"


def _blobs_dir() -> Path:
    return history_dir() / "blobs"


def _notes_dir() -> Path:
    return history_dir() / "notes"


def _key(rel_path: str) -> str:
    return hashlib.sha1(rel_path.encode("utf-8")).hexdigest()


def _log_path(rel_path: str) -> Path:
    return _notes_dir() / f"{_key(rel_path)}.jsonl"


def _head_path(rel_path: str) -> Path:
    return _notes_dir() / f"{_key(rel_path)}.head"


def blob_id(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _check_blob(blob: str) -> None:
    if not isinstance(blob, str) or not _BLOB_RE.fullmatch(blob):
        raise ValueError(f"invalid blob id: {blob!r}")


def _blob_path(blob: str) -> Path:
    _check_blob(blob)
    return _blobs_dir() / f"{blob}.md"


def _atomic_write(path: Path, data: bytes, *, durable: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            if durable:
                fh.flush()
                os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def put_blob(data: bytes) -> str:
    blob = blob_id(data)
    path = _blob_path(blob)
    with _lock:
        try:
            os.utime(path)  # already stored: refresh mtime so GC's grace spares it
            return blob
        except FileNotFoundError:
            pass
        _atomic_write(path, data, durable=True)
    return blob


def get_blob(blob: str) -> bytes:
    path = _blob_path(blob)
    try:
        return path.read_bytes()
    except FileNotFoundError:
        raise BlobNotFound(blob) from None


def has_blob(blob: str) -> bool:
    return _blob_path(blob).is_file()


def _parse_line(line: str) -> Snapshot | None:
    try:
        d = json.loads(line)
        snap = Snapshot(
            ts=str(d["ts"]), rel_path=str(d["rel_path"]), blob=str(d["blob"]),
            actor=str(d["actor"]), reason=str(d.get("reason", "")), size=int(d.get("size", 0)),
        )
        _check_blob(snap.blob)
        snap.when  # noqa: B018 — validates the timestamp
        return snap
    except (ValueError, KeyError, TypeError):
        return None


def _raw_lines(log_file: Path) -> list[str]:
    try:
        text = log_file.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return []
    return [line for line in text.splitlines() if line.strip()]


def _read_log_file(log_file: Path) -> list[Snapshot]:
    out: list[Snapshot] = []
    for line in _raw_lines(log_file):
        snap = _parse_line(line)
        if snap is None:
            log.warning("skipping unreadable history line in %s", log_file.name)
            continue
        out.append(snap)
    return out


def _read_log(rel_path: str) -> list[Snapshot]:
    return _read_log_file(_log_path(rel_path))


def _rewrite(log_file: Path, entries: list[Snapshot]) -> None:
    if not entries:
        log_file.unlink(missing_ok=True)
        log_file.with_suffix(".head").unlink(missing_ok=True)
        return
    data = "".join(json.dumps(s.to_dict(), ensure_ascii=False) + "\n" for s in entries)
    _atomic_write(log_file, data.encode("utf-8"), durable=True)


def _append(rel_path: str, snap: Snapshot) -> None:
    path = _log_path(rel_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(snap.to_dict(), ensure_ascii=False) + "\n"
    with path.open("a+b") as fh:
        fh.seek(0, os.SEEK_END)
        if fh.tell() > 0:
            fh.seek(-1, os.SEEK_END)
            if fh.read(1) != b"\n":  # a crash left a partial line: start fresh
                line = "\n" + line
        fh.write(line.encode("utf-8"))
        fh.flush()
        os.fsync(fh.fileno())


def _read_head(rel_path: str) -> dict[str, Any] | None:
    try:
        data = json.loads(_head_path(rel_path).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_head(rel_path: str, head: dict[str, Any]) -> None:
    _atomic_write(_head_path(rel_path), json.dumps(head).encode("utf-8"), durable=False)


def _coalesces(
    head: dict[str, Any], before: bytes, *, actor: str, after: bytes | None, now: datetime
) -> bool:
    if actor != _USER or after is None:  # deletes are never coalesced
        return False
    if head.get("actor") != _USER or head.get("after") != blob_id(before):
        return False  # a non-user write or a foreign edit happened since
    try:
        last = datetime.fromisoformat(str(head["ts"]))
    except (KeyError, ValueError):
        return False
    return timedelta(0) <= now - last < USER_COALESCE


def snapshot(
    rel_path: str,
    before: bytes,
    *,
    actor: str,
    reason: str = "",
    after: bytes | None = None,
) -> Snapshot | None:
    now = _now()
    try:
        with _lock:
            head = _read_head(rel_path) or {}
            if _coalesces(head, before, actor=actor, after=after, now=now):
                assert after is not None
                _write_head(rel_path, {**head, "after": blob_id(after)})
                return None
            snap = Snapshot(
                ts=now.isoformat(), rel_path=rel_path, blob=put_blob(before),
                actor=actor, reason=reason, size=len(before),
            )
            _append(rel_path, snap)
            _write_head(rel_path, {
                "ts": snap.ts, "actor": actor,
                "after": blob_id(after) if after is not None else None,
            })
            return snap
    except OSError as e:
        raise HistoryUnavailable(f"history unavailable: {e}") from e


def list_snapshots(rel_path: str, *, limit: int | None = None) -> list[Snapshot]:
    try:
        with _lock:
            entries = _read_log(rel_path)
    except OSError as e:
        raise HistoryUnavailable(f"history unavailable: {e}") from e
    entries.reverse()
    return entries if limit is None else entries[:limit]


# ── retention + GC ───────────────────────────────────────────────────────────

KEEP_ALL = timedelta(days=30)
KEEP_DAILY = timedelta(days=365)
# A blob younger than this is never collected: a snapshot may have stored it
# a moment before the prune scanned the logs.
BLOB_GRACE = timedelta(days=1)

_ref_sources: dict[str, Callable[[], Iterable[str]]] = {}


@dataclass(frozen=True)
class PruneResult:
    notes: int
    kept: int
    dropped: int
    blobs_deleted: int
    gc_skipped: bool = False

    def to_details(self) -> dict[str, int | bool]:
        return {
            "notes": self.notes, "kept": self.kept, "dropped": self.dropped,
            "blobsDeleted": self.blobs_deleted, "gcSkipped": self.gc_skipped,
        }


def register_ref_source(name: str, source: Callable[[], Iterable[str]]) -> None:
    """Blob ids referenced outside the note logs (spec B's changes.db). GC
    keeps every id a source yields; a source that raises skips GC."""
    _ref_sources[name] = source


def retained(entries: list[Snapshot], now: datetime) -> list[Snapshot]:
    """30 days: everything. Then the newest per UTC day for a year, then the
    newest per UTC month. Returned oldest first."""
    keep: list[Snapshot] = []
    days: set[object] = set()
    months: set[tuple[int, int]] = set()
    for s in sorted(entries, key=lambda e: e.when, reverse=True):
        when = s.when.astimezone(timezone.utc)
        age = now - when
        if age <= KEEP_ALL:
            keep.append(s)
        elif age <= KEEP_DAILY:
            if when.date() not in days:
                days.add(when.date())
                keep.append(s)
        elif (when.year, when.month) not in months:
            months.add((when.year, when.month))
            keep.append(s)
    keep.sort(key=lambda e: e.when)
    return keep


def _gc_blobs(referenced: set[str]) -> int:
    blobs = _blobs_dir()
    if not blobs.is_dir():
        return 0
    cutoff = time.time() - BLOB_GRACE.total_seconds()
    deleted = 0
    for p in blobs.iterdir():
        name = p.name
        is_blob = name.endswith(".md") and _BLOB_RE.fullmatch(name[:-3]) is not None
        is_tmp = name.startswith(".") and name.endswith(".tmp")
        if not (is_blob or is_tmp) or (is_blob and name[:-3] in referenced):
            continue  # never touch files we did not create
        try:
            if p.stat().st_mtime > cutoff:
                continue
            p.unlink()
        except FileNotFoundError:
            continue
        if is_blob:
            deleted += 1
    return deleted


def prune(now: datetime | None = None) -> PruneResult:
    now = now or _now()
    notes = kept = dropped = 0
    referenced: set[str] = set()
    try:
        with _lock:
            notes_dir = _notes_dir()
            log_files = sorted(notes_dir.glob("*.jsonl")) if notes_dir.is_dir() else []
            for log_file in log_files:
                notes += 1
                raw = _raw_lines(log_file)
                entries = [s for s in (_parse_line(line) for line in raw) if s is not None]
                keep = retained(entries, now)
                kept += len(keep)
                dropped += len(raw) - len(keep)
                if len(keep) != len(raw):
                    _rewrite(log_file, keep)
                referenced.update(s.blob for s in keep)
            for name, source in list(_ref_sources.items()):
                try:
                    referenced.update(source())
                except Exception:  # noqa: BLE001 — unknown refs: deleting would be unsafe
                    log.exception("history ref source %r failed; skipping blob GC", name)
                    return PruneResult(notes, kept, dropped, 0, gc_skipped=True)
            deleted = _gc_blobs(referenced)
    except OSError as e:
        raise HistoryUnavailable(f"history unavailable: {e}") from e
    return PruneResult(notes, kept, dropped, deleted)


# ── moves ────────────────────────────────────────────────────────────────────

def move_log(src_rel: str, dest_rel: str) -> None:
    """A note moved (jot re-route): its history follows it."""
    if src_rel == dest_rel:
        return
    try:
        with _lock:
            src_log = _log_path(src_rel)
            if src_log.exists():
                merged = sorted(_read_log(dest_rel) + _read_log(src_rel), key=lambda s: s.when)
                _rewrite(_log_path(dest_rel), merged)
                src_log.unlink()
            head = _read_head(src_rel)
            if head is not None:
                _write_head(dest_rel, head)
                _head_path(src_rel).unlink(missing_ok=True)
    except OSError as e:
        raise HistoryUnavailable(f"history unavailable: {e}") from e
