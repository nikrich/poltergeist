# A3 Page History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep a content-deduplicated history of every note version the app overwrites, in app state outside the vault. Snapshots are taken automatically on save (user autosaves coalesced, every other writer never coalesced), and a HistoryDrawer in the editor shows a diff against the current file and can restore any version.

**Architecture:** A new `ghostbrain/history/` package owns the store under `state_dir()/history`: content-addressed blobs, one JSONL log per note, a small "head" file per note for coalescing, retention pruning, and blob GC. The B1 write path (`ghostbrain/vault_write/writer.py::_write`) calls `history.store.snapshot(...)` once, under the per-path lock, before every write that changes a file. Because of that, every route, MCP tool, plugin and worker gets history without any per-route code. That includes B1's "Keep mine", which B1 deferred to A3. Three routes under `/v1/notes/history` list, read and restore versions. A daily scheduler job prunes. On the desktop side, a `HistoryDrawer` reuses B1's `lineDiff`, and restore goes through the editor's guarded save chain, so an autosave can never land on top of a restore.

**Tech Stack:** Python 3.11 stdlib (`hashlib`, `json`, `threading`, `tempfile`), FastAPI, pytest; React 18 + TanStack Query + zustand, Vitest + Testing Library, TypeScript (`tsc -b`).

**Spec:** `docs/superpowers/specs/2026-10-09-confluence-editor-design.md` (§ "Page history", § "Error handling", § "Testing", slice A3). Also read the parts of `docs/superpowers/specs/2026-10-09-ai-changes-revert-design.md` that cover the history store: §1 step 5, §4, §5 and §7. Spec B builds its change log and revert on the store's public interface (Task 1/2 Interfaces).

## Global Constraints

- History lives in **app state, not the vault** (user decision 2026-10-09). Root: `ghostbrain.paths.state_dir() / "history"`, which is `~/.ghostbrain/state/history` by default and `$GHOSTBRAIN_STATE_DIR/history` when the env var is set. The root `conftest.py` sandboxes `GHOSTBRAIN_STATE_DIR` per test. Never write history under `vault_path()`.
- On-disk layout is copied from the spec: `blobs/<sha256>.md` (whole file including frontmatter), `notes/<sha1(rel_path)>.jsonl` (one line per snapshot: `{ts, rel_path, blob, actor, reason}`, plus `size`).
- `actor` is one of `user | assistant | mcp | plugin:<id> | worker:<job> | restore`.
- User autosaves coalesce to **at most one snapshot per note per 5 minutes**. Non-user actors are **never** coalesced.
- Retention: **keep everything for 30 days, then one per day for a year, then one per month**. A **daily** scheduler job prunes logs and garbage-collects unreferenced blobs.
- **History write fails on a user save → the save proceeds**, the failure is logged, and the renderer shows a once-per-session toast "history unavailable". For a non-user actor (including `restore`) the write is **refused** (HTTP 500 `history unavailable`, file untouched).
- Restore = "snapshot the current version as `actor: restore`, then write the blob".
- Snapshots hook into `vault_write._write` **once**. No route calls the store before writing.
- No new npm or pip dependency. The diff reuses `desktop/src/renderer/lib/line-diff.ts` (B1), not the `diff` package the spec names.
- Python tests run with `python -m pytest`. Every new file under `tests/` that is CI-safe gets added to the fixed list in `.github/workflows/ci.yml`. Files under `ghostbrain/api/tests/` are picked up automatically.
- Desktop gates: `npm run typecheck` (tsc -b), `npx vitest run`, `npm run lint` (eslint `--max-warnings 0`). Windows release builds rerun the desktop tests, so assertions must not depend on POSIX paths, line endings or the locale (do not assert on formatted dates).
- No real people's or employer names in code, fixtures or copy.

## Review Focus

1. **A foreign edit between two user autosaves less than 5 minutes apart** (Obsidian, sync, or B1's **Keep mine** overwriting "theirs"). The foreign version must be snapshotted, not coalesced away. Pinned in Task 1 (`test_user_save_after_a_foreign_change_is_never_coalesced`), Task 3 (`test_autosaves_coalesce_but_an_outside_edit_is_kept`) and Task 4 over HTTP (`test_keep_mine_over_http_keeps_their_version`).
2. **An autosave that was already scheduled or queued when the user clicks Restore** must never overwrite the restored text. Pinned in Task 6 (`runExclusive drops text queued during a successful restore`, `an autosave scheduled before a restore never overwrites it`).
3. **Blob GC racing a concurrent snapshot, or B2's change log referencing blobs the logs no longer do.** GC must never delete a referenced or just-written blob, and must skip entirely when a reference source fails. Pinned in Task 2 (`test_gc_spares_fresh_unreferenced_blobs`, `test_prune_keeps_blobs_named_by_ref_sources`, `test_prune_skips_gc_when_a_ref_source_fails`).
4. **A crash mid-append leaves a partial JSONL line.** Listing must skip it and the next append must start on a new line. Pinned in Task 1 (`test_corrupt_log_lines_are_skipped_and_appends_start_on_a_new_line`).
5. **A jot is re-routed (moved) after it was edited.** Its history must follow it to the new path, or the drawer shows nothing. Pinned in Task 2 (`test_move_log_carries_entries_and_head`) and Task 3 (`test_move_carries_history_to_the_new_path`).

---

## File Structure

| File | Responsibility |
|---|---|
| `ghostbrain/history/__init__.py` (new) | Public re-exports of the store: the interface B2 imports |
| `ghostbrain/history/store.py` (new) | Blobs, per-note logs, head files, `snapshot` (with coalescing), listing, `move_log`, retention, `prune`/GC, ref sources |
| `ghostbrain/vault_write/actor.py` | + `RESTORE` actor |
| `ghostbrain/vault_write/writer.py` | `_snapshot` / `_move_history` helpers; `_write` snapshots before every changing write; `WriteResult.history_ok` |
| `ghostbrain/vault_write/__init__.py` | Re-export `RESTORE`, `HistoryUnavailable` |
| `ghostbrain/api/vault_http.py` | `HistoryUnavailable` → 500 `history unavailable` |
| `ghostbrain/api/models/history.py` (new) | `RestoreRequest`, `BLOB_PATTERN` |
| `ghostbrain/api/routes/history.py` (new) | `GET /v1/notes/history`, `GET /v1/notes/history/blob`, `POST /v1/notes/history/restore` |
| `ghostbrain/api/main.py` | Include the history router (before notes) |
| `ghostbrain/api/repo/note.py`, `ghostbrain/api/repo/notes_manual.py` | User save responses gain `historyOk` |
| `ghostbrain/scheduler_jobs.py` | `history-prune` daily job |
| `desktop/src/shared/api-types.ts` | History types; `historyOk?` on save responses |
| `desktop/src/renderer/lib/history-health.ts` (new) | Once-per-session "history unavailable" toast |
| `desktop/src/renderer/lib/api/hooks.ts` | `useNoteHistory`, `useHistoryVersion`, `useRestoreVersion`; save hooks report history health |
| `desktop/src/renderer/components/LineDiffView.tsx` (new) | Shared line-diff renderer (ConflictBanner, HistoryDrawer, later B2's Changes screen) |
| `desktop/src/renderer/components/ConflictBanner.tsx` | Uses `LineDiffView` |
| `desktop/src/renderer/lib/use-guarded-save.ts` | `runExclusive` (restore between autosaves) |
| `desktop/src/renderer/components/GuardedNoteEditor.tsx` | `GuardHandle.restore`; stale-instance saves dropped |
| `desktop/src/renderer/components/HistoryDrawer.tsx` (new) | Timeline, actor badge, diff vs current, Restore; exports `actorLabel` |
| `desktop/src/renderer/components/NoteHistory.tsx` (new) | `NoteHistoryButton`: the header button, the drawer, and restore through the guard |
| `desktop/src/renderer/components/NoteView.tsx`, `desktop/src/renderer/screens/jots.tsx` | Mount `NoteHistoryButton` in the editor headers |
| `.github/workflows/ci.yml` | Add the three new `tests/` files |

---

### Task 1: History store core — blobs, per-note log, coalesced snapshots

**Files:**
- Create: `ghostbrain/history/__init__.py`
- Create: `ghostbrain/history/store.py`
- Test: `tests/test_history_store.py`
- Modify: `.github/workflows/ci.yml` (add `tests/test_history_store.py`)

**Interfaces:**
- Consumes: `ghostbrain.paths.state_dir() -> Path`.
- Produces (importable from `ghostbrain.history`; B2 builds on exactly these):
  - `history_dir() -> Path`: `state_dir() / "history"`.
  - `blob_id(data: bytes) -> str`: sha256 hex, 64 chars. Pure.
  - `put_blob(data: bytes) -> str`: idempotent. It refreshes the mtime of an existing blob so GC's grace window spares it. Returns `blob_id(data)`.
  - `get_blob(blob: str) -> bytes`: raises `ValueError` for a malformed id and `BlobNotFound` when the blob is absent.
  - `has_blob(blob: str) -> bool`.
  - `snapshot(rel_path: str, before: bytes, *, actor: str, reason: str = "", after: bytes | None = None) -> Snapshot | None`: records `before` as the version just before a write by `actor`. Returns `None` when the snapshot is coalesced (user only). `after` is the bytes the write will leave on disk (`None` for a delete). Raises `HistoryUnavailable` on any I/O failure.
  - `list_snapshots(rel_path: str, *, limit: int | None = None) -> list[Snapshot]`: newest first.
  - `@dataclass(frozen=True) Snapshot(ts: str, rel_path: str, blob: str, actor: str, reason: str, size: int)` with `.when -> datetime` and `.to_dict() -> dict`.
  - Exceptions: `HistoryError(Exception)`, `HistoryUnavailable(HistoryError)`, `BlobNotFound(HistoryError)`.
  - Constant: `USER_COALESCE = timedelta(minutes=5)`.
  - Test seam: `store._now() -> datetime` (UTC), which tests monkeypatch.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_history_store.py`:

```python
"""History store: content-addressed blobs, per-note log, coalescing (spec A3)."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone

import pytest

from ghostbrain import history
from ghostbrain.history import store

T0 = datetime(2026, 10, 9, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch):
    now = {"t": T0}
    monkeypatch.setattr(store, "_now", lambda: now["t"])

    def advance(**kw: float) -> None:
        now["t"] = now["t"] + timedelta(**kw)

    return advance


def test_history_dir_lives_in_app_state_not_the_vault(tmp_path):
    # Root conftest: GHOSTBRAIN_STATE_DIR=tmp_path/state, VAULT_PATH=tmp_path/vault.
    assert store.history_dir() == (tmp_path / "state").resolve() / "history"
    assert history.history_dir() == store.history_dir()


def test_put_blob_dedupes_identical_content():
    a = store.put_blob(b"same\n")
    b = store.put_blob(b"same\n")
    assert a == b == store.blob_id(b"same\n")
    assert len(list((store.history_dir() / "blobs").glob("*.md"))) == 1
    assert store.get_blob(a) == b"same\n"
    assert store.has_blob(a)


def test_get_blob_rejects_bad_ids_and_reports_missing():
    with pytest.raises(ValueError):
        store.get_blob("../../secrets")
    with pytest.raises(ValueError):
        store.get_blob("A" * 64)
    with pytest.raises(store.BlobNotFound):
        store.get_blob("0" * 64)
    assert not store.has_blob("0" * 64)


def test_snapshot_appends_and_lists_newest_first(clock):
    s1 = store.snapshot("a.md", b"v1\n", actor="assistant", reason="r1", after=b"v2\n")
    clock(seconds=1)
    s2 = store.snapshot("a.md", b"v2\n", actor="mcp", reason="r2", after=b"v3\n")
    got = store.list_snapshots("a.md")
    assert [s.blob for s in got] == [s2.blob, s1.blob]
    assert got[0].actor == "mcp" and got[0].reason == "r2" and got[0].size == 3
    assert got[1].ts == T0.isoformat()
    assert store.list_snapshots("a.md", limit=1) == [got[0]]
    assert store.list_snapshots("other.md") == []


def test_snapshot_to_dict_is_the_log_line_shape(clock):
    s = store.snapshot("a.md", b"v1\n", actor="assistant", reason="x")
    assert s.to_dict() == {
        "ts": T0.isoformat(), "rel_path": "a.md", "blob": store.blob_id(b"v1\n"),
        "actor": "assistant", "reason": "x", "size": 3,
    }
    line = store._log_path("a.md").read_text(encoding="utf-8").strip()
    assert json.loads(line) == s.to_dict()


def test_user_snapshots_coalesce_within_five_minutes(clock):
    assert store.snapshot("a.md", b"v1\n", actor="user", after=b"v2\n") is not None
    clock(minutes=1)
    assert store.snapshot("a.md", b"v2\n", actor="user", after=b"v3\n") is None
    clock(minutes=3, seconds=59)  # 4:59 since the kept snapshot
    assert store.snapshot("a.md", b"v3\n", actor="user", after=b"v4\n") is None
    clock(seconds=2)  # 5:01
    s = store.snapshot("a.md", b"v4\n", actor="user", after=b"v5\n")
    assert s is not None and store.get_blob(s.blob) == b"v4\n"
    assert len(store.list_snapshots("a.md")) == 2


def test_user_save_after_a_foreign_change_is_never_coalesced(clock):
    """Keep mine / an Obsidian edit: disk no longer holds what our last write
    left there, so the foreign version must be kept."""
    store.snapshot("a.md", b"v1\n", actor="user", after=b"mine\n")
    clock(seconds=30)
    s = store.snapshot("a.md", b"theirs\n", actor="user", after=b"mine again\n")
    assert s is not None and store.get_blob(s.blob) == b"theirs\n"


def test_non_user_actors_never_coalesce(clock):
    for i in range(3):
        snap = store.snapshot(
            "a.md", f"v{i}\n".encode(), actor="assistant", after=f"v{i + 1}\n".encode()
        )
        assert snap is not None
    assert len(store.list_snapshots("a.md")) == 3


def test_user_save_after_a_non_user_write_is_kept(clock):
    store.snapshot("a.md", b"v1\n", actor="assistant", after=b"ai\n")
    clock(seconds=10)
    assert store.snapshot("a.md", b"ai\n", actor="user", after=b"me\n") is not None


def test_user_delete_is_never_coalesced(clock):
    store.snapshot("a.md", b"v1\n", actor="user", after=b"v2\n")
    clock(seconds=5)
    s = store.snapshot("a.md", b"v2\n", actor="user", after=None)
    assert s is not None and store.get_blob(s.blob) == b"v2\n"


def test_clock_going_backwards_does_not_coalesce(clock):
    store.snapshot("a.md", b"v1\n", actor="user", after=b"v2\n")
    clock(minutes=-1)
    assert store.snapshot("a.md", b"v2\n", actor="user", after=b"v3\n") is not None


def test_corrupt_log_lines_are_skipped_and_appends_start_on_a_new_line(clock):
    store.snapshot("a.md", b"v1\n", actor="assistant")
    with store._log_path("a.md").open("a", encoding="utf-8") as fh:
        fh.write('{"ts": "broken')  # crash mid-append: no trailing newline
    clock(seconds=1)
    store.snapshot("a.md", b"v2\n", actor="assistant")
    got = store.list_snapshots("a.md")
    assert [store.get_blob(s.blob) for s in got] == [b"v2\n", b"v1\n"]


def test_unicode_paths_and_reasons_round_trip(clock):
    rel = "20-contexts/wörk/ñote.md"
    store.snapshot(rel, "é\n".encode(), actor="assistant", reason="polished “intro”")
    [s] = store.list_snapshots(rel)
    assert s.rel_path == rel and s.reason == "polished “intro”"


def test_io_failures_raise_history_unavailable(monkeypatch):
    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(store, "_atomic_write", boom)
    with pytest.raises(store.HistoryUnavailable):
        store.snapshot("a.md", b"v1\n", actor="assistant")


def test_concurrent_snapshots_of_one_note_lose_no_lines(clock):
    def snap(i: int) -> None:
        store.snapshot("a.md", f"v{i}\n".encode(), actor="assistant")

    threads = [threading.Thread(target=snap, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(store.list_snapshots("a.md")) == 20


def test_package_reexports_the_interface():
    for name in ("history_dir", "blob_id", "put_blob", "get_blob", "has_blob", "snapshot",
                 "list_snapshots", "Snapshot", "HistoryError", "HistoryUnavailable",
                 "BlobNotFound", "USER_COALESCE"):
        assert hasattr(history, name), name
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-plans2 && python -m pytest tests/test_history_store.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.history'`

- [ ] **Step 3: Write the store**

Create `ghostbrain/history/store.py`:

```python
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
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

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
```

Create `ghostbrain/history/__init__.py`:

```python
"""Page history (spec A3): the store spec B's change log and revert build on."""
from ghostbrain.history.store import (
    USER_COALESCE,
    BlobNotFound,
    HistoryError,
    HistoryUnavailable,
    Snapshot,
    blob_id,
    get_blob,
    has_blob,
    history_dir,
    list_snapshots,
    put_blob,
    snapshot,
)

__all__ = [
    "USER_COALESCE", "BlobNotFound", "HistoryError", "HistoryUnavailable", "Snapshot",
    "blob_id", "get_blob", "has_blob", "history_dir", "list_snapshots", "put_blob", "snapshot",
]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-plans2 && python -m pytest tests/test_history_store.py -q`
Expected: PASS (16 passed)

- [ ] **Step 5: Add the file to CI**

In `.github/workflows/ci.yml`, under the `python -m pytest \` list, add this line directly after `tests/test_vault_index_links.py \`:

```yaml
            tests/test_history_store.py \
```

- [ ] **Step 6: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-plans2 && git add ghostbrain/history tests/test_history_store.py .github/workflows/ci.yml && git commit -m "feat(history): content-addressed page history store with user coalescing (A3)"
```

---

### Task 2: Retention, blob GC, log moves, and the daily prune job

**Files:**
- Modify: `ghostbrain/history/store.py` (append the functions below)
- Modify: `ghostbrain/history/__init__.py` (re-export)
- Modify: `ghostbrain/scheduler_jobs.py` (`_history_prune_job`, registration in `register_connectors`)
- Test: `tests/test_history_retention.py`
- Test: `tests/test_scheduler_history_prune_job.py`
- Modify: `.github/workflows/ci.yml` (add `tests/test_history_retention.py` only. The scheduler test imports `ghostbrain.scheduler_jobs`, which pulls in every connector, so it stays out of the CI list like the existing `tests/test_scheduler_*` files)

**Interfaces:**
- Consumes: Task 1 internals (`_lock`, `_notes_dir`, `_blobs_dir`, `_raw_lines`, `_parse_line`, `_rewrite`, `_read_log`, `_log_path`, `_head_path`, `_read_head`, `_write_head`, `_BLOB_RE`, `_now`, `HistoryUnavailable`, `Snapshot`).
- Produces (importable from `ghostbrain.history`):
  - `KEEP_ALL = timedelta(days=30)`, `KEEP_DAILY = timedelta(days=365)`, `BLOB_GRACE = timedelta(days=1)`.
  - `retained(entries: list[Snapshot], now: datetime) -> list[Snapshot]`: pure. Returns the survivors, oldest first. Buckets are UTC calendar days and months, and the newest entry in each bucket wins.
  - `move_log(src_rel: str, dest_rel: str) -> None`: moves a note's log and head to its new path, merging by time. Raises `HistoryUnavailable`.
  - `register_ref_source(name: str, source: Callable[[], Iterable[str]]) -> None`: **B2 registers its changes-DB blob ids here**, so GC never deletes `before_blob` / `after_blob` / `pending_bytes_blob`.
  - `prune(now: datetime | None = None) -> PruneResult`: retention over every log plus blob GC. GC skips blobs younger than `BLOB_GRACE` (by real file mtime) and skips GC entirely when a ref source raises.
  - `@dataclass(frozen=True) PruneResult(notes: int, kept: int, dropped: int, blobs_deleted: int, gc_skipped: bool = False)` with `.to_details() -> dict`.
  - Scheduler job id `history-prune`, `DailyAt(hour=3, minute=15)`, label `"daily 03:15"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_history_retention.py`:

```python
"""History retention, blob GC, ref sources, log moves (spec A3)."""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from ghostbrain import history
from ghostbrain.history import store
from ghostbrain.history.store import Snapshot

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _no_ref_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store, "_ref_sources", {})


def _s(when: datetime, n: int = 0) -> Snapshot:
    return Snapshot(ts=when.isoformat(), rel_path="a.md", blob=f"{n:064x}", actor="user",
                    reason="", size=1)


def _snap_at(monkeypatch, when: datetime, rel: str, data: bytes, actor: str = "assistant"):
    monkeypatch.setattr(store, "_now", lambda: when)
    return store.snapshot(rel, data, actor=actor)


def _age_file(path, days: float) -> None:
    old = time.time() - days * 86400
    os.utime(path, (old, old))


def test_retained_keeps_everything_for_30_days():
    entries = [_s(NOW - timedelta(days=d, hours=h), i)
               for i, (d, h) in enumerate([(30, 0), (29, 0), (1, 3), (1, 1), (0, 0)])]
    assert store.retained(entries, NOW) == sorted(entries, key=lambda s: s.when)


def test_retained_keeps_newest_per_day_between_30_days_and_a_year():
    morning = _s(datetime(2026, 8, 30, 9, tzinfo=timezone.utc), 1)
    noon = _s(datetime(2026, 8, 30, 13, tzinfo=timezone.utc), 2)
    evening = _s(datetime(2026, 8, 30, 18, tzinfo=timezone.utc), 3)
    day_before = _s(datetime(2026, 8, 29, 9, tzinfo=timezone.utc), 4)
    got = store.retained([morning, noon, evening, day_before], NOW)
    assert got == [day_before, evening]


def test_retained_keeps_newest_per_month_after_a_year():
    early_aug = _s(datetime(2025, 8, 3, 10, tzinfo=timezone.utc), 1)
    late_aug = _s(datetime(2025, 8, 20, 10, tzinfo=timezone.utc), 2)
    july = _s(datetime(2025, 7, 1, 10, tzinfo=timezone.utc), 3)
    got = store.retained([early_aug, late_aug, july], NOW)
    assert got == [july, late_aug]


def test_prune_rewrites_logs_and_reports_counts(monkeypatch):
    for i, hour in enumerate((9, 13, 18)):
        _snap_at(monkeypatch, datetime(2026, 8, 30, hour, tzinfo=timezone.utc), "a.md",
                 f"v{i}\n".encode())
    _snap_at(monkeypatch, NOW - timedelta(days=1), "a.md", b"recent\n")
    res = store.prune(now=NOW)
    assert (res.notes, res.kept, res.dropped) == (1, 2, 2)
    got = store.list_snapshots("a.md")
    assert [store.get_blob(s.blob) for s in got] == [b"recent\n", b"v2\n"]
    assert res.to_details() == {"notes": 1, "kept": 2, "dropped": 2, "blobsDeleted": 0,
                                "gcSkipped": False}


def test_prune_gcs_unreferenced_blobs_older_than_the_grace(monkeypatch):
    for i, hour in enumerate((9, 18)):
        _snap_at(monkeypatch, datetime(2026, 8, 30, hour, tzinfo=timezone.utc), "a.md",
                 f"v{i}\n".encode())
    dropped_blob = store.blob_id(b"v0\n")
    kept_blob = store.blob_id(b"v1\n")
    for b in (dropped_blob, kept_blob):
        _age_file(store._blob_path(b), days=2)
    res = store.prune(now=NOW)
    assert res.blobs_deleted == 1
    assert not store.has_blob(dropped_blob) and store.has_blob(kept_blob)


def test_gc_spares_fresh_unreferenced_blobs():
    """A blob put by a snapshot racing the prune has a fresh mtime."""
    fresh = store.put_blob(b"just written\n")
    assert store.prune(now=NOW).blobs_deleted == 0
    assert store.has_blob(fresh)


def test_put_blob_refreshes_mtime_of_an_existing_blob():
    blob = store.put_blob(b"x\n")
    _age_file(store._blob_path(blob), days=2)
    store.put_blob(b"x\n")
    assert store.prune(now=NOW).blobs_deleted == 0


def test_gc_removes_stale_temp_files_but_never_foreign_files():
    blobs = store.history_dir() / "blobs"
    blobs.mkdir(parents=True)
    tmp = blobs / ".abc.md.123.tmp"
    tmp.write_bytes(b"partial")
    foreign = blobs / "README.txt"
    foreign.write_bytes(b"not ours")
    for p in (tmp, foreign):
        _age_file(p, days=2)
    store.prune(now=NOW)
    assert not tmp.exists() and foreign.exists()


def test_prune_keeps_blobs_named_by_ref_sources():
    orphan = store.put_blob(b"changes-db only\n")
    _age_file(store._blob_path(orphan), days=2)
    history.register_ref_source("changes", lambda: [orphan])
    assert store.prune(now=NOW).blobs_deleted == 0
    assert store.has_blob(orphan)


def test_prune_skips_gc_when_a_ref_source_fails():
    orphan = store.put_blob(b"maybe referenced\n")
    _age_file(store._blob_path(orphan), days=2)

    def broken():
        raise RuntimeError("changes.db locked")

    history.register_ref_source("changes", broken)
    res = store.prune(now=NOW)
    assert res.gc_skipped is True and res.blobs_deleted == 0
    assert store.has_blob(orphan)


def test_prune_drops_logs_with_no_readable_entries():
    log_file = store._log_path("a.md")
    log_file.parent.mkdir(parents=True)
    log_file.write_text("garbage\n", encoding="utf-8")
    store._head_path("a.md").write_text("{}", encoding="utf-8")
    res = store.prune(now=NOW)
    assert res.dropped == 1
    assert not log_file.exists() and not store._head_path("a.md").exists()


def test_move_log_carries_entries_and_head(monkeypatch):
    monkeypatch.setattr(store, "_now", lambda: NOW)
    store.snapshot("inbox/j.md", b"v1\n", actor="user", after=b"v2\n")
    store.move_log("inbox/j.md", "20-contexts/work/j.md")
    assert store.list_snapshots("inbox/j.md") == []
    [moved] = store.list_snapshots("20-contexts/work/j.md")
    assert store.get_blob(moved.blob) == b"v1\n"
    # The head moved too: the next user save at the new path coalesces.
    assert store.snapshot("20-contexts/work/j.md", b"v2\n", actor="user", after=b"v3\n") is None


def test_move_log_merges_into_an_existing_destination_log_in_time_order(monkeypatch):
    _snap_at(monkeypatch, NOW - timedelta(hours=3), "b.md", b"old b\n")
    _snap_at(monkeypatch, NOW - timedelta(hours=2), "a.md", b"a\n")
    _snap_at(monkeypatch, NOW - timedelta(hours=1), "b.md", b"new b\n")
    store.move_log("a.md", "b.md")
    got = [store.get_blob(s.blob) for s in store.list_snapshots("b.md")]
    assert got == [b"new b\n", b"a\n", b"old b\n"]


def test_move_log_without_history_is_a_no_op():
    store.move_log("none.md", "elsewhere.md")
    assert store.list_snapshots("elsewhere.md") == []
```

Create `tests/test_scheduler_history_prune_job.py`:

```python
"""Scheduler registration + wrapping for the daily history prune."""
from __future__ import annotations

from ghostbrain.history import store
from ghostbrain.scheduler import DailyAt, Scheduler
from ghostbrain.scheduler_jobs import _history_prune_job, register_connectors


def test_history_prune_registered_daily():
    sched = Scheduler()
    register_connectors(sched)
    job = sched._jobs["history-prune"]
    assert job.schedule == DailyAt(hour=3, minute=15)
    assert job.schedule_label == "daily 03:15"


def test_history_prune_job_reports_counts():
    result = _history_prune_job()
    assert result.connector == "history-prune"
    assert result.ok is True
    assert result.details == {"notes": 0, "kept": 0, "dropped": 0, "blobsDeleted": 0,
                              "gcSkipped": False}


def test_history_prune_job_never_raises(monkeypatch):
    def boom(now=None):
        raise store.HistoryUnavailable("disk")

    monkeypatch.setattr(store, "prune", boom)
    result = _history_prune_job()
    assert result.ok is False and result.error_type == "HistoryUnavailable"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-plans2 && python -m pytest tests/test_history_retention.py tests/test_scheduler_history_prune_job.py -q`
Expected: FAIL with `AttributeError: module 'ghostbrain.history.store' has no attribute '_ref_sources'` (fixture) and `ImportError: cannot import name '_history_prune_job'`

- [ ] **Step 3: Implement retention, GC, ref sources, and log moves**

Append to `ghostbrain/history/store.py` (add `import time` and `from typing import Any, Callable, Iterable` to the imports at the top, replacing the existing `from typing import Any`):

```python
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
```

Replace `ghostbrain/history/__init__.py` with:

```python
"""Page history (spec A3): the store spec B's change log and revert build on."""
from ghostbrain.history.store import (
    BLOB_GRACE,
    KEEP_ALL,
    KEEP_DAILY,
    USER_COALESCE,
    BlobNotFound,
    HistoryError,
    HistoryUnavailable,
    PruneResult,
    Snapshot,
    blob_id,
    get_blob,
    has_blob,
    history_dir,
    list_snapshots,
    move_log,
    prune,
    put_blob,
    register_ref_source,
    retained,
    snapshot,
)

__all__ = [
    "BLOB_GRACE", "KEEP_ALL", "KEEP_DAILY", "USER_COALESCE",
    "BlobNotFound", "HistoryError", "HistoryUnavailable", "PruneResult", "Snapshot",
    "blob_id", "get_blob", "has_blob", "history_dir", "list_snapshots", "move_log",
    "prune", "put_blob", "register_ref_source", "retained", "snapshot",
]
```

- [ ] **Step 4: Add the scheduler job**

In `ghostbrain/scheduler_jobs.py`, add after `_gdrive_backfill_job`:

```python
def _history_prune_job() -> RunResult:
    """Daily page-history retention + blob GC (spec A3). Lazy import keeps
    sidecar start cheap; prune only touches app state, never the vault."""
    def work() -> dict:
        from ghostbrain.history import store

        return store.prune().to_details()

    return _wrap_job("history-prune", work)
```

In `register_connectors`, add after the `claudemd` job:

```python
    scheduler.add_job(
        "history-prune",
        DailyAt(hour=3, minute=15),
        _history_prune_job,
        "daily 03:15",
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-plans2 && python -m pytest tests/test_history_store.py tests/test_history_retention.py tests/test_scheduler_history_prune_job.py -q`
Expected: PASS

- [ ] **Step 6: Add the retention tests to CI**

In `.github/workflows/ci.yml`, add after `tests/test_history_store.py \`:

```yaml
            tests/test_history_retention.py \
```

- [ ] **Step 7: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-plans2 && git add ghostbrain/history ghostbrain/scheduler_jobs.py tests/test_history_retention.py tests/test_scheduler_history_prune_job.py .github/workflows/ci.yml && git commit -m "feat(history): retention pruning, blob GC with ref sources, log moves, daily job (A3)"
```

---

### Task 3: Snapshot inside the vault write path

**Files:**
- Modify: `ghostbrain/vault_write/actor.py` (add `RESTORE`)
- Modify: `ghostbrain/vault_write/writer.py:1-8` (module docstring), `:22-25` (imports), `:44-51` (`WriteResult`), `:235-288` (`_write` body); add `_snapshot` and `_move_history`
- Modify: `ghostbrain/vault_write/__init__.py`
- Modify: `ghostbrain/api/vault_http.py` (`HistoryUnavailable` → 500)
- Test: `tests/test_vault_write_history.py`
- Modify: `.github/workflows/ci.yml` (add `tests/test_vault_write_history.py`)

**Interfaces:**
- Consumes: `ghostbrain.history.store.snapshot(...)`, `store.move_log(...)`, `HistoryUnavailable`, `Snapshot` (Tasks 1–2).
- Produces:
  - `ghostbrain.vault_write.RESTORE: Actor = "restore"`. `parse_actor("restore")` accepts it. It counts as a non-user actor: never coalesced, and a history failure refuses the write.
  - `WriteResult.history_ok: bool = True`, a new last field. It is `False` only when a **user** write went through without its snapshot.
  - `ghostbrain.vault_write.HistoryUnavailable`, re-exported from `ghostbrain.history`.
  - `writer._snapshot(rel: str, before: bytes, *, actor: Actor, reason: str, after: bytes | None) -> tuple[Snapshot | None, bool]`. **B2 hook:** the returned `Snapshot.blob` is the change row's `before_blob`.
  - The sidecar maps `HistoryUnavailable` to HTTP **500** `{"detail": "history unavailable"}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_vault_write_history.py`:

```python
"""vault_write takes a page-history snapshot before every changing write (A3)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ghostbrain import vault_write
from ghostbrain.history import store
from ghostbrain.vault_write import (
    ASSISTANT,
    RESTORE,
    USER,
    HistoryUnavailable,
    compute_etag,
    parse_actor,
    write,
)

T0 = datetime(2026, 10, 9, 10, 0, tzinfo=timezone.utc)
REL = "20-contexts/work/plan.md"
V1 = b"---\ntitle: Plan\n---\n\nfirst draft\n"


@pytest.fixture
def hv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("VAULT_PATH", str(vault))
    now = {"t": T0}
    monkeypatch.setattr(store, "_now", lambda: now["t"])
    note = vault / REL
    note.parent.mkdir(parents=True)
    note.write_bytes(V1)

    def advance(**kw: float) -> None:
        now["t"] = now["t"] + timedelta(**kw)

    return note, advance


def _versions(rel: str = REL) -> list[bytes]:
    return [store.get_blob(s.blob) for s in store.list_snapshots(rel)]


def test_user_body_save_snapshots_the_previous_file_bytes(hv):
    res = write(REL, body="second draft", actor=USER, reason="edited in the editor")
    assert res.history_ok is True
    [snap] = store.list_snapshots(REL)
    assert store.get_blob(snap.blob) == V1
    assert (snap.actor, snap.reason, snap.rel_path) == ("user", "edited in the editor", REL)


def test_identical_save_takes_no_snapshot(hv):
    write(REL, content=V1.decode(), actor=USER)
    assert store.list_snapshots(REL) == []


def test_create_takes_no_snapshot(hv):
    write("20-contexts/work/new.md", content="hello\n", op="create", actor=ASSISTANT)
    assert store.list_snapshots("20-contexts/work/new.md") == []


def test_autosaves_coalesce_but_an_outside_edit_is_kept(hv):
    note, advance = hv
    write(REL, body="v2", actor=USER)
    advance(seconds=20)
    write(REL, body="v3", actor=USER)
    assert _versions() == [V1]
    theirs = b"---\ntitle: Plan\n---\n\ntheirs\n"
    note.write_bytes(theirs)  # an Obsidian edit
    advance(seconds=20)
    # Keep mine: overwrite on the fresh etag (B1 deferred this snapshot to A3).
    write(REL, body="mine", actor=USER, base_etag=compute_etag(theirs))
    assert _versions() == [theirs, V1]


def test_assistant_writes_snapshot_every_time(hv):
    _, advance = hv
    for i in range(3):
        write(REL, body=f"ai {i}", actor=ASSISTANT)
        advance(seconds=1)
    assert len(store.list_snapshots(REL)) == 3


def test_non_user_write_is_refused_when_history_fails(hv, monkeypatch):
    note, _ = hv

    def boom(*_a, **_k):
        raise store.HistoryUnavailable("disk full")

    monkeypatch.setattr(store, "snapshot", boom)
    with pytest.raises(HistoryUnavailable):
        write(REL, body="ai edit", actor=ASSISTANT)
    assert note.read_bytes() == V1


def test_user_write_proceeds_when_history_fails(hv, monkeypatch):
    note, _ = hv

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(store, "snapshot", boom)
    res = write(REL, body="my edit", actor=USER)
    assert res.history_ok is False
    assert b"my edit" in note.read_bytes()


def test_restore_is_an_actor_that_is_never_coalesced(hv):
    _, advance = hv
    assert parse_actor("restore") == RESTORE == "restore"
    write(REL, body="v2", actor=USER)
    advance(seconds=5)
    write(REL, content=V1.decode(), actor=RESTORE, reason="restored")
    assert [s.actor for s in store.list_snapshots(REL)] == ["restore", "user"]


def test_delete_keeps_the_deleted_version(hv):
    write(REL, op="delete", actor=USER)
    assert _versions() == [V1]


def test_move_carries_history_to_the_new_path(hv):
    _, advance = hv
    write(REL, body="edited", actor=USER)
    advance(minutes=6)
    dest = "20-contexts/work/projects/plan.md"
    res = write(REL, op="move", dest=dest, fields={"context": "work"}, actor=USER)
    assert res.path == dest and res.history_ok is True
    assert store.list_snapshots(REL) == []
    versions = _versions(dest)
    assert versions[-1] == V1 and len(versions) == 2


def test_html_writes_are_snapshotted_too(hv):
    rel = "90-meta/generated/doc.html"
    write(rel, content="<p>one</p>", op="create", actor="mcp")
    write(rel, content="<p>two</p>", actor="mcp")
    assert _versions(rel) == [b"<p>one</p>"]


def test_package_exports_restore_and_history_unavailable():
    assert vault_write.RESTORE == "restore"
    assert vault_write.HistoryUnavailable is store.HistoryUnavailable
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-plans2 && python -m pytest tests/test_vault_write_history.py -q`
Expected: FAIL with `ImportError: cannot import name 'RESTORE' from 'ghostbrain.vault_write'`

- [ ] **Step 3: Add the `restore` actor**

In `ghostbrain/vault_write/actor.py`, replace the constants and regex block with:

```python
USER: Actor = "user"
ASSISTANT: Actor = "assistant"
MCP: Actor = "mcp"
# Page-history restore (spec A3): the version being replaced is snapshotted
# as ``restore``. A non-user actor for history purposes: never coalesced, and
# a history failure refuses the write.
RESTORE: Actor = "restore"

_ID = r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}"
_ACTOR_RE = re.compile(rf"user|assistant|mcp|restore|plugin:{_ID}|worker:{_ID}")
```

- [ ] **Step 4: Hook the snapshot into `_write`**

In `ghostbrain/vault_write/writer.py`:

Replace the module docstring (lines 1–8) with:

```python
"""The single vault write path: lock → etag check → minimal-diff bytes →
history snapshot → atomic replace (spec B §1; snapshot from spec A3).

A3 snapshots the current bytes inside ``_write`` (``_snapshot``) before every
write that changes a file, so every writer — routes, MCP, plugins, worker —
gets page history without per-route code. B2 adds the change record and B3
the risk hold at the marked hook points (under the file lock; the public
``write`` wrapper only re-indexes the A2 link index afterwards).
"""
```

Replace lines 22–25 (the imports from `ghostbrain.paths` through `compute_etag`) with:

```python
import ghostbrain.paths as _paths
from ghostbrain.history import store as _history_store
from ghostbrain.history.store import HistoryUnavailable, Snapshot
from ghostbrain.vault_write.actor import USER, Actor, parse_actor
from ghostbrain.vault_write.errors import FileMissing, InvalidPath, MalformedNote, WriteConflict
from ghostbrain.vault_write.etag import compute_etag
```

Replace the `WriteResult` dataclass (lines 44–51) with:

```python
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
```

Add these two helpers directly above `def _write(`:

```python
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
```

Replace the body of `_write` from `with _locked(...)` to the end of the function (lines 255–288) with:

```python
    with _locked(src, *([dst] if dst is not None else [])):
        current = _read_bytes(src)
        etag_now = compute_etag(current) if current is not None else None
        if base_etag is not None and base_etag != etag_now:
            raise WriteConflict(etag_now)
        # B3 hook point: the risk check (→ pending) goes here, before any snapshot.
        if op == "create":
            if current is not None:
                raise WriteConflict(etag_now)
            assert content is not None
            data = _content_bytes(src, content)
            _atomic_write(src, data)
            # B2 hook point: change row for a create (no before-version).
            return WriteResult("applied", None, compute_etag(data), _rel(src), None)
        if current is None:
            raise FileMissing(rel_path)
        src_rel = _rel(src)
        if op == "delete":
            _, history_ok = _snapshot(src_rel, current, actor=actor, reason=reason, after=None)
            src.unlink()
            return WriteResult("applied", None, None, src_rel, None, history_ok)
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
            _, history_ok = _snapshot(src_rel, current, actor=actor, reason=reason, after=data)
            _atomic_write(dst, data)
            src.unlink()
            dst_rel = _rel(dst)
            history_ok = _move_history(src_rel, dst_rel) and history_ok
            return WriteResult("applied", None, compute_etag(data), dst_rel, updated, history_ok)
        history_ok = True
        if data != current:
            # B2 hook point: the snapshot's blob is the change row's before_blob.
            _, history_ok = _snapshot(src_rel, current, actor=actor, reason=reason, after=data)
            _atomic_write(src, data)
        return WriteResult("applied", None, compute_etag(data), src_rel, updated, history_ok)
```

In `ghostbrain/vault_write/__init__.py`, add `RESTORE` to the actor import list, add `from ghostbrain.history.store import HistoryUnavailable` after the errors import, and replace `__all__` with:

```python
__all__ = [
    "ASSISTANT", "DELETE_FIELD", "MCP", "RESTORE", "USER", "WRITABLE_SUFFIXES",
    "Actor", "FileMissing", "HistoryUnavailable", "InvalidPath", "MalformedNote",
    "NoteSnapshot", "Op", "ParsedNote", "VaultWriteError", "WriteConflict", "WriteResult",
    "apply_fields", "compute_etag", "current_etag", "find_key_block", "lines_of",
    "load_metadata", "normalize_if_match", "parse_actor", "parse_note", "plugin_actor",
    "read", "resolve_safe", "splice_body", "worker_actor", "write", "write_new",
]
```

The resulting actor import block reads:

```python
from ghostbrain.vault_write.actor import (
    ASSISTANT,
    MCP,
    RESTORE,
    USER,
    Actor,
    parse_actor,
    plugin_actor,
    worker_actor,
)
```

- [ ] **Step 5: Map `HistoryUnavailable` to HTTP 500**

In `ghostbrain/api/vault_http.py`, add the import `from ghostbrain.history import HistoryUnavailable`, and inside `install_vault_write_errors` add before the `app.add_exception_handler` lines:

```python
    async def _history(_req: Request, _exc: Exception) -> JSONResponse:
        # Spec B error handling: a non-user write that cannot be snapshotted
        # is refused; the file is untouched.
        return JSONResponse(status_code=500, content={"detail": "history unavailable"})
```

and after the last `add_exception_handler` line:

```python
    app.add_exception_handler(HistoryUnavailable, _history)
```

- [ ] **Step 6: Run the new and the existing write-path tests**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-plans2 && python -m pytest tests/test_vault_write_history.py tests/test_vault_write_writer.py tests/test_vault_write_text.py ghostbrain/api/tests -q`
Expected: PASS (B1's tests are unchanged and still green: `history_ok` defaults to `True`, and `_rel(src)` is the same value as before)

- [ ] **Step 7: Add the test file to CI**

In `.github/workflows/ci.yml`, add after `tests/test_vault_write_writer.py \`:

```yaml
            tests/test_vault_write_history.py \
```

- [ ] **Step 8: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-plans2 && git add ghostbrain/vault_write ghostbrain/api/vault_http.py tests/test_vault_write_history.py .github/workflows/ci.yml && git commit -m "feat(vault-write): history snapshot before every changing write; restore actor (A3)"
```

---

### Task 4: History routes and `historyOk` on save responses

**Files:**
- Create: `ghostbrain/api/models/history.py`
- Create: `ghostbrain/api/routes/history.py`
- Modify: `ghostbrain/api/main.py` (import + `include_router` before `notes_routes`)
- Modify: `ghostbrain/api/repo/note.py` (`save_note_body` return)
- Modify: `ghostbrain/api/repo/notes_manual.py` (`update_jot_body` return)
- Test: `ghostbrain/api/tests/test_routes_notes_history.py`

**Interfaces:**
- Consumes: `history.list_snapshots`, `history.get_blob`, `history.BlobNotFound`, `history.Snapshot` (Task 1); `vault_write.write`, `vault_write.read`, `vault_write.current_etag`, `vault_write.resolve_safe`, `vault_write.RESTORE`, `WriteResult.history_ok` (Task 3); `ghostbrain.api.vault_http.if_match`.
- Produces (HTTP; the desktop relies on these shapes):
  - `GET /v1/notes/history?path=&limit=200` (limit 1–1000) → `{"path": str, "items": [{"ts", "path", "blob", "actor", "reason", "size"}]}`, newest first. A bad path → 400.
  - `GET /v1/notes/history/blob?path=&blob=` → `{"path", "blob", "content": str, "current": str | null}`. A blob not in this note's log → 404. A malformed blob → 422.
  - `POST /v1/notes/history/restore` body `{"path", "blob"}`, optional `If-Match` → `{"path", "etag", "body", "restored": blob, "historyOk": bool}`. A stale `If-Match` → 409. An unknown or GC'd version → 404. A history failure → 500 `history unavailable`, file untouched.
  - `PATCH /v1/notes/body` and `PATCH /v1/notes/{jot_id}` responses gain `"historyOk": bool`.

- [ ] **Step 1: Write the failing tests**

Create `ghostbrain/api/tests/test_routes_notes_history.py`:

```python
"""Page-history routes + historyOk on saves (spec A3)."""
from __future__ import annotations

from datetime import datetime, timezone

from ghostbrain.api.repo.notes_manual import write_inbox_jot
from ghostbrain.api.tests.conftest import write_note
from ghostbrain.history import store
from ghostbrain.vault_write import compute_etag

REL = "20-contexts/work/notes/plan.md"
V1 = "---\ntitle: Plan\n---\n\nfirst draft\n"


def _save(client, headers, body, if_match=None):
    h = dict(headers)
    if if_match:
        h["If-Match"] = f'"{if_match}"'
    return client.patch("/v1/notes/body", json={"path": REL, "body": body}, headers=h)


def _history(client, headers):
    return client.get("/v1/notes/history", params={"path": REL}, headers=headers)


def test_saving_records_a_version_and_lists_it(tmp_vault, client, auth_headers):
    write_note(tmp_vault, REL, V1)
    r = _save(client, auth_headers, "second draft")
    assert r.status_code == 200 and r.json()["historyOk"] is True
    h = _history(client, auth_headers)
    assert h.status_code == 200
    data = h.json()
    assert data["path"] == REL
    [item] = data["items"]
    assert item["actor"] == "user" and item["path"] == REL
    assert item["blob"] == store.blob_id(V1.encode())
    assert item["size"] == len(V1.encode())


def test_keep_mine_over_http_keeps_their_version(tmp_vault, client, auth_headers):
    note = write_note(tmp_vault, REL, V1)
    _save(client, auth_headers, "mine 1")
    theirs = "---\ntitle: Plan\n---\n\ntheirs\n"
    note.write_bytes(theirs.encode())
    fresh = compute_etag(note.read_bytes())
    assert _save(client, auth_headers, "mine 2", if_match=fresh).status_code == 200
    blobs = [i["blob"] for i in _history(client, auth_headers).json()["items"]]
    assert store.blob_id(theirs.encode()) in blobs


def test_blob_returns_the_version_and_the_current_file(tmp_vault, client, auth_headers):
    write_note(tmp_vault, REL, V1)
    _save(client, auth_headers, "second draft")
    blob = store.blob_id(V1.encode())
    r = client.get("/v1/notes/history/blob", params={"path": REL, "blob": blob},
                   headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["content"] == V1
    assert "second draft" in data["current"]


def test_blob_of_another_note_is_404(tmp_vault, client, auth_headers):
    write_note(tmp_vault, REL, V1)
    _save(client, auth_headers, "second draft")
    write_note(tmp_vault, "20-contexts/work/notes/other.md", "x\n")
    r = client.get("/v1/notes/history/blob",
                   params={"path": "20-contexts/work/notes/other.md",
                           "blob": store.blob_id(V1.encode())},
                   headers=auth_headers)
    assert r.status_code == 404


def test_malformed_blob_id_is_422(tmp_vault, client, auth_headers):
    r = client.get("/v1/notes/history/blob", params={"path": REL, "blob": "../x"},
                   headers=auth_headers)
    assert r.status_code == 422


def test_history_path_outside_the_vault_is_400(tmp_vault, client, auth_headers):
    r = client.get("/v1/notes/history", params={"path": "../secrets.md"}, headers=auth_headers)
    assert r.status_code == 400


def test_restore_snapshots_current_then_writes_the_version(tmp_vault, client, auth_headers):
    note = write_note(tmp_vault, REL, V1)
    _save(client, auth_headers, "second draft")
    before_restore = note.read_bytes()
    blob = store.blob_id(V1.encode())
    r = client.post("/v1/notes/history/restore", json={"path": REL, "blob": blob},
                    headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert note.read_bytes() == V1.encode()
    assert data["body"] == "first draft"
    assert data["etag"] == compute_etag(V1.encode())
    assert data["restored"] == blob and data["historyOk"] is True
    newest = _history(client, auth_headers).json()["items"][0]
    assert newest["actor"] == "restore"
    assert newest["blob"] == store.blob_id(before_restore)


def test_restore_with_stale_if_match_is_409_and_leaves_the_file(tmp_vault, client, auth_headers):
    note = write_note(tmp_vault, REL, V1)
    _save(client, auth_headers, "second draft")
    current = note.read_bytes()
    r = client.post("/v1/notes/history/restore",
                    json={"path": REL, "blob": store.blob_id(V1.encode())},
                    headers={**auth_headers, "If-Match": '"0000000000000000"'})
    assert r.status_code == 409
    assert note.read_bytes() == current


def test_restore_of_an_unknown_version_is_404(tmp_vault, client, auth_headers):
    write_note(tmp_vault, REL, V1)
    r = client.post("/v1/notes/history/restore", json={"path": REL, "blob": "a" * 64},
                    headers=auth_headers)
    assert r.status_code == 404


def test_restore_of_a_collected_version_is_404(tmp_vault, client, auth_headers):
    write_note(tmp_vault, REL, V1)
    _save(client, auth_headers, "second draft")
    blob = store.blob_id(V1.encode())
    store._blob_path(blob).unlink()
    r = client.post("/v1/notes/history/restore", json={"path": REL, "blob": blob},
                    headers=auth_headers)
    assert r.status_code == 404
    assert r.json()["detail"] == "this version is no longer available"


def test_jot_save_reports_history_ok(tmp_vault, client, auth_headers):
    rec = write_inbox_jot("hello jot", captured_at=datetime.now(timezone.utc))
    r = client.patch(f"/v1/notes/{rec['id']}", json={"body": "hello again"},
                     headers=auth_headers)
    assert r.status_code == 200 and r.json()["historyOk"] is True
    items = client.get("/v1/notes/history", params={"path": rec["path"]},
                       headers=auth_headers).json()["items"]
    assert len(items) == 1


def test_user_save_survives_a_history_failure(tmp_vault, client, auth_headers, monkeypatch):
    note = write_note(tmp_vault, REL, V1)

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(store, "snapshot", boom)
    r = _save(client, auth_headers, "kept anyway")
    assert r.status_code == 200 and r.json()["historyOk"] is False
    assert b"kept anyway" in note.read_bytes()


def test_plugin_write_is_refused_when_history_fails(tmp_vault, client, auth_headers, monkeypatch):
    note = write_note(tmp_vault, REL, V1)

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(store, "snapshot", boom)
    r = client.put("/v1/notes", json={"path": REL, "content": "plugin text"},
                   headers=auth_headers)
    assert r.status_code == 500
    assert r.json()["detail"] == "history unavailable"
    assert note.read_bytes() == V1.encode()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-plans2 && python -m pytest ghostbrain/api/tests/test_routes_notes_history.py -q`
Expected: FAIL. Listing returns 404/405 (no route yet), and `historyOk` is a `KeyError`.

- [ ] **Step 3: Add the request model**

Create `ghostbrain/api/models/history.py`:

```python
"""Page-history request schemas (spec A3)."""
from pydantic import BaseModel, Field

BLOB_PATTERN = r"^[0-9a-f]{64}$"


class RestoreRequest(BaseModel):
    path: str = Field(min_length=1, max_length=500)  # vault-relative
    blob: str = Field(pattern=BLOB_PATTERN)
```

- [ ] **Step 4: Add the routes**

Create `ghostbrain/api/routes/history.py`:

```python
"""Page history (spec A3): list a note's versions, read one, restore one.

Snapshots are taken by the vault write path itself; these routes only read
the store and restore through ``vault_write.write(actor=RESTORE)``, which
snapshots the version being replaced first."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

import ghostbrain.paths as _paths
from ghostbrain import history, vault_write
from ghostbrain.api.models.history import BLOB_PATTERN, RestoreRequest
from ghostbrain.api.vault_http import if_match
from ghostbrain.vault_write import RESTORE

router = APIRouter(prefix="/v1/notes/history", tags=["history"])


def _canonical(path: str) -> str:
    """The rel path the write path logs under (resolved, POSIX). Raises
    vault_write.InvalidPath (→ 400) for anything outside the vault."""
    target = vault_write.resolve_safe(path)
    return target.relative_to(_paths.vault_path().resolve()).as_posix()


def _entry(s: history.Snapshot) -> dict:
    return {"ts": s.ts, "path": s.rel_path, "blob": s.blob, "actor": s.actor,
            "reason": s.reason, "size": s.size}


def _find(rel: str, blob: str) -> history.Snapshot:
    match = next((s for s in history.list_snapshots(rel) if s.blob == blob), None)
    if match is None:
        raise HTTPException(status_code=404, detail="no such version of this note")
    return match


def _blob_text(blob: str) -> str:
    try:
        return history.get_blob(blob).decode("utf-8")
    except history.BlobNotFound:
        raise HTTPException(status_code=404, detail="this version is no longer available")
    except UnicodeDecodeError:
        raise HTTPException(status_code=422, detail="this version is not UTF-8 text")


@router.get("")
def list_history(
    path: str = Query(..., min_length=1, max_length=500),
    limit: int = Query(200, ge=1, le=1000),
) -> dict:
    rel = _canonical(path)
    return {"path": rel, "items": [_entry(s) for s in history.list_snapshots(rel, limit=limit)]}


@router.get("/blob")
def get_version(
    path: str = Query(..., min_length=1, max_length=500),
    blob: str = Query(..., pattern=BLOB_PATTERN),
) -> dict:
    rel = _canonical(path)
    _find(rel, blob)
    content = _blob_text(blob)
    try:
        current: str | None = (
            vault_write.resolve_safe(rel).read_bytes().decode("utf-8", errors="replace")
        )
    except FileNotFoundError:
        current = None
    return {"path": rel, "blob": blob, "content": content, "current": current}


@router.post("/restore")
def restore_version(req: RestoreRequest, base_etag: str | None = Depends(if_match)) -> dict:
    rel = _canonical(req.path)
    match = _find(rel, req.blob)
    text = _blob_text(req.blob)
    exists = vault_write.current_etag(rel) is not None
    res = vault_write.write(
        rel,
        content=text,
        op="modify" if exists else "create",
        actor=RESTORE,
        reason=f"restored the version from {match.ts}",
        base_etag=base_etag,
    )
    return {
        "path": res.path,
        "etag": res.etag,
        "body": vault_write.read(rel).body,
        "restored": req.blob,
        "historyOk": res.history_ok,
    }
```

- [ ] **Step 5: Register the router**

In `ghostbrain/api/main.py`, add `from ghostbrain.api.routes import history as history_routes` to the route imports (alphabetical, after `health`). Replace the line `    app.include_router(notes_routes.router)` with:

```python
    # Before notes: /v1/notes/history/* must never be read as a jot id.
    app.include_router(history_routes.router)
    app.include_router(notes_routes.router)
```

- [ ] **Step 6: Report `historyOk` on user saves**

In `ghostbrain/api/repo/note.py`, change the return of `save_note_body` to:

```python
    return {"path": rel_path, "updated": res.updated, "etag": res.etag,
            "historyOk": res.history_ok}
```

In `ghostbrain/api/repo/notes_manual.py`, change the return of `update_jot_body` to:

```python
    return {"id": jot_id, "path": res.path, "updated": now, "etag": res.etag,
            "historyOk": res.history_ok}
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-plans2 && python -m pytest ghostbrain/api/tests -q`
Expected: PASS (new file green; existing `test_routes_notes_body.py` / `test_routes_notes_mutate.py` unaffected, since they assert on keys, not whole dicts. If one compares a whole response dict, add `"historyOk": True` to its expected value)

- [ ] **Step 8: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-plans2 && git add ghostbrain/api && git commit -m "feat(api): page history list/blob/restore routes; historyOk on saves (A3)"
```

---

### Task 5: Desktop data layer: types, hooks, history-health toast, shared diff view

**Files:**
- Modify: `desktop/src/shared/api-types.ts` (after `UpdateJotResponse`)
- Create: `desktop/src/renderer/lib/history-health.ts`
- Modify: `desktop/src/renderer/lib/api/hooks.ts` (imports; `useUpdateJot`, `useUpdateNoteByPath` `onSuccess`; three new hooks)
- Create: `desktop/src/renderer/components/LineDiffView.tsx`
- Modify: `desktop/src/renderer/components/ConflictBanner.tsx` (use `LineDiffView`)
- Test: `desktop/src/renderer/__tests__/history-health.test.tsx`
- Test: `desktop/src/renderer/__tests__/LineDiffView.test.tsx`

**Interfaces:**
- Consumes: Task 4 HTTP shapes; `lineDiff(oldText, newText): DiffLine[]` from `lib/line-diff.ts`; `toast` from `stores/toast`.
- Produces:
  - Types: `HistoryEntry { ts: string; path: string; blob: string; actor: string; reason: string; size: number }`, `NoteHistoryResponse { path: string; items: HistoryEntry[] }`, `HistoryBlobResponse { path: string; blob: string; content: string; current: string | null }`, `RestoreHistoryResponse { path: string; etag: string | null; body: string; restored: string; historyOk: boolean }`. Plus `historyOk?: boolean` on `UpdateNoteBodyResponse` and `UpdateJotResponse`.
  - `reportHistoryHealth(res: { historyOk?: boolean } | null | undefined): void`, which toasts once per session, and `resetHistoryHealthForTests(): void`.
  - Hooks: `useNoteHistory(path: string | null)`, `useHistoryVersion(path: string | null, blob: string | null)`, `useRestoreVersion()`. The last is a mutation over `{ path: string; blob: string }` → `RestoreHistoryResponse`.
  - `<LineDiffView oldText newText legend testId? className? />`. This is the diff component spec B's Changes screen reuses.

- [ ] **Step 1: Write the failing tests**

Create `desktop/src/renderer/__tests__/history-health.test.tsx`:

```tsx
import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as client from '../lib/api/client';
import { useUpdateNoteByPath } from '../lib/api/hooks';
import { reportHistoryHealth, resetHistoryHealthForTests } from '../lib/history-health';
import { useToasts } from '../stores/toast';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ApiError: actual.ApiError, get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn() };
});
const patchMock = vi.mocked(client.patch);

afterEach(() => {
  resetHistoryHealthForTests();
  useToasts.setState({ toasts: [] });
  patchMock.mockReset();
});

const messages = () => useToasts.getState().toasts.map((t) => t.message);

describe('reportHistoryHealth', () => {
  it('toasts once per session when a save went through without history', () => {
    reportHistoryHealth({ historyOk: false });
    reportHistoryHealth({ historyOk: false });
    expect(messages()).toEqual(['history unavailable — your edits are saved, but no version was kept']);
  });

  it('stays quiet when history worked or the server predates the field', () => {
    reportHistoryHealth({ historyOk: true });
    reportHistoryHealth({});
    reportHistoryHealth(undefined);
    expect(messages()).toEqual([]);
  });

  it('is wired into the by-path save hook', async () => {
    patchMock.mockResolvedValue({ path: 'a.md', updated: null, etag: 'e', historyOk: false });
    const qc = new QueryClient();
    const { result } = renderHook(() => useUpdateNoteByPath(), {
      wrapper: ({ children }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>,
    });
    await result.current.mutateAsync({ path: 'a.md', body: 'x' });
    await waitFor(() => expect(messages()).toHaveLength(1));
  });
});
```

Create `desktop/src/renderer/__tests__/LineDiffView.test.tsx`:

```tsx
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { LineDiffView } from '../components/LineDiffView';

describe('LineDiffView', () => {
  it('renders the legend and prefixed added / removed / kept lines', () => {
    render(
      <LineDiffView testId="d" oldText={'keep\nold line'} newText={'keep\nnew line'} legend="- old · + new" />,
    );
    const view = screen.getByTestId('d');
    expect(view).toHaveTextContent('- old · + new');
    expect(view).toHaveTextContent('- old line');
    expect(view).toHaveTextContent('+ new line');
    expect(view).toHaveTextContent('keep');
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-plans2/desktop && npx vitest run src/renderer/__tests__/history-health.test.tsx src/renderer/__tests__/LineDiffView.test.tsx`
Expected: FAIL. Resolving `../lib/history-health` and `../components/LineDiffView` fails.

- [ ] **Step 3: Add the types**

In `desktop/src/shared/api-types.ts`, replace `UpdateNoteBodyResponse` and `UpdateJotResponse` with the versions below and add the history types after them:

```ts
export interface UpdateNoteBodyResponse {
  path: string;
  updated: string | null;
  etag: string;
  /** false: saved, but no history version was kept (spec A3). */
  historyOk?: boolean;
}

export interface UpdateJotResponse {
  id: string;
  path: string;
  updated: string;
  etag: string;
  historyOk?: boolean;
}

/** One page-history version: the note as it was just before a write by `actor`. */
export interface HistoryEntry {
  ts: string;
  /** Vault-relative path at snapshot time. */
  path: string;
  /** sha256 of the stored file bytes. */
  blob: string;
  /** user | assistant | mcp | plugin:<id> | worker:<job> | restore */
  actor: string;
  reason: string;
  size: number;
}

export interface NoteHistoryResponse {
  path: string;
  /** Newest first. */
  items: HistoryEntry[];
}

export interface HistoryBlobResponse {
  path: string;
  blob: string;
  /** Whole file (frontmatter included) of that version. */
  content: string;
  /** Whole current file; null when the note no longer exists. */
  current: string | null;
}

export interface RestoreHistoryResponse {
  path: string;
  etag: string | null;
  /** The restored note's body, as GET /v1/notes?path= returns it. */
  body: string;
  restored: string;
  historyOk: boolean;
}
```

- [ ] **Step 4: Add the history-health module**

Create `desktop/src/renderer/lib/history-health.ts`:

```ts
import { toast } from '../stores/toast';

let warned = false;

/** Spec A3: a user save whose history snapshot failed still succeeds; tell
 * the user once per session, not on every autosave. */
export function reportHistoryHealth(res: { historyOk?: boolean } | null | undefined): void {
  if (warned || res?.historyOk !== false) return;
  warned = true;
  toast.error('history unavailable — your edits are saved, but no version was kept');
}

export function resetHistoryHealthForTests(): void {
  warned = false;
}
```

- [ ] **Step 5: Add the hooks**

In `desktop/src/renderer/lib/api/hooks.ts`:

Add `HistoryBlobResponse`, `NoteHistoryResponse` and `RestoreHistoryResponse` to the `from '../../../shared/api-types'` import list, and add below the client import:

```ts
import { reportHistoryHealth } from '../history-health';
```

In `useUpdateJot`, replace `onSuccess: () => {` with `onSuccess: (res) => {` and make `reportHistoryHealth(res);` its first line. Do the same in `useUpdateNoteByPath`.

Add after `useUpdateNoteByPath`:

```ts
export function useNoteHistory(path: string | null) {
  return useQuery({
    queryKey: ['note-history', path],
    queryFn: () =>
      get<NoteHistoryResponse>(`/v1/notes/history?path=${encodeURIComponent(path!)}`),
    enabled: path !== null,
    staleTime: 0,
  });
}

export function useHistoryVersion(path: string | null, blob: string | null) {
  return useQuery({
    queryKey: ['note-history', path, blob],
    queryFn: () =>
      get<HistoryBlobResponse>(
        `/v1/notes/history/blob?path=${encodeURIComponent(path!)}&blob=${encodeURIComponent(blob!)}`,
      ),
    enabled: path !== null && blob !== null,
    staleTime: 0,
  });
}

export function useRestoreVersion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { path: string; blob: string }) =>
      post<RestoreHistoryResponse>('/v1/notes/history/restore', vars),
    onSuccess: (res) => {
      reportHistoryHealth(res);
      qc.invalidateQueries({ queryKey: ['note-history'] });
      qc.invalidateQueries({ queryKey: ['note'] });
      qc.invalidateQueries({ queryKey: ['note-by-path'] });
      qc.invalidateQueries({ queryKey: JOTS_KEY });
      qc.invalidateQueries({ queryKey: ['vault', 'backlinks'] });
    },
  });
}
```

- [ ] **Step 6: Add `LineDiffView` and use it in ConflictBanner**

Create `desktop/src/renderer/components/LineDiffView.tsx`:

```tsx
import { useMemo } from 'react';
import { lineDiff } from '../lib/line-diff';

const lineClass = {
  same: 'text-ink-2',
  del: 'bg-oxblood/10 text-oxblood',
  add: 'bg-neon/10 text-ink-0',
} as const;
const prefix = { same: '  ', del: '- ', add: '+ ' } as const;

interface Props {
  oldText: string;
  newText: string;
  /** One-line key, e.g. "- theirs · + yours". */
  legend: string;
  testId?: string;
  className?: string;
}

/** Line diff of oldText → newText (conflict banner, page history, B2's Changes screen). */
export function LineDiffView({ oldText, newText, legend, testId, className = '' }: Props) {
  const lines = useMemo(() => lineDiff(oldText, newText), [oldText, newText]);
  return (
    <pre
      data-testid={testId}
      className={`overflow-auto rounded-sm border border-hairline bg-paper p-2 font-mono text-11 ${className}`}
    >
      <div className="mb-1 text-ink-3">{legend}</div>
      {lines.map((line, i) => (
        <div key={i} className={lineClass[line.kind]}>
          {prefix[line.kind]}
          {line.text}
        </div>
      ))}
    </pre>
  );
}
```

In `desktop/src/renderer/components/ConflictBanner.tsx`, delete the `lineDiff` import and the `lineClass` / `prefix` constants. Add `import { LineDiffView } from './LineDiffView';`, and replace the whole `{showDiff && !unread && (<pre …>…</pre>)}` block with:

```tsx
      {showDiff && !unread && (
        <LineDiffView
          testId="conflict-diff"
          className="mt-2 max-h-64"
          oldText={conflict.theirs}
          newText={conflict.mine}
          legend="- theirs (on disk) · + yours (in the editor)"
        />
      )}
```

- [ ] **Step 7: Run the tests, typecheck and lint**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-plans2/desktop && npx vitest run src/renderer/__tests__/history-health.test.tsx src/renderer/__tests__/LineDiffView.test.tsx src/renderer/__tests__/GuardedNoteEditor.test.tsx && npm run typecheck && npm run lint`
Expected: PASS (GuardedNoteEditor's existing `conflict-diff` assertions still hold)

- [ ] **Step 8: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-plans2 && git add desktop/src && git commit -m "feat(desktop): page-history types, hooks, history-health toast, shared LineDiffView (A3)"
```

---

### Task 6: Restore through the guarded save chain

**Files:**
- Modify: `desktop/src/renderer/lib/use-guarded-save.ts` (`GuardedSave` interface, `runExclusive`, `RESTORE_BLOCKED`)
- Modify: `desktop/src/renderer/components/GuardedNoteEditor.tsx` (`GuardHandle.restore`, nonce-guarded `onSave`, `keepTheirs` via `remount`)
- Test: `desktop/src/renderer/__tests__/use-guarded-save.test.tsx` (append)
- Test: `desktop/src/renderer/__tests__/GuardedNoteEditor.test.tsx` (append)

**Interfaces:**
- Consumes: the existing `useGuardedSave` internals (`inFlightRef`, `queuedRef`, `conflictRef`, `etagRef`, `markSaved`, `run`).
- Produces:
  - `export const RESTORE_BLOCKED = 'resolve the conflict banner first (keep mine or keep theirs)'`.
  - `GuardedSave.runExclusive: <T extends { body: string; etag?: string | null }>(perform: () => Promise<T>) => Promise<T>`. It waits for any in-flight save and its queue, runs `perform`, and adopts `res.etag`/`res.body`. On success it drops text queued meanwhile. On failure it replays that text. It rejects with `RESTORE_BLOCKED` while a conflict is up.
  - `GuardHandle.restore: (perform: () => Promise<{ body: string; etag?: string | null }>) => Promise<void>`. This is `runExclusive`, then a remount of the editor with `res.body`. Saves scheduled by the replaced editor instance are dropped.

- [ ] **Step 1: Write the failing tests**

Append to `desktop/src/renderer/__tests__/use-guarded-save.test.tsx` (inside the existing `describe('useGuardedSave', …)` block, before its closing `});`), and add `RESTORE_BLOCKED` to the import from `../lib/use-guarded-save`:

```tsx
  it('runExclusive waits for the in-flight save, then adopts the result etag', async () => {
    const first = deferred<{ etag: string }>();
    const send = vi.fn().mockReturnValueOnce(first.promise).mockResolvedValue({ etag: 'e4' });
    const { result } = renderHook(() =>
      useGuardedSave({ body: 'a', etag: 'e1' }, { send, fetchLatest: vi.fn() }),
    );
    act(() => result.current.save('b'));
    const perform = vi.fn().mockResolvedValue({ body: 'restored', etag: 'e3' });
    let done!: Promise<unknown>;
    act(() => {
      done = result.current.runExclusive(perform);
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 40));
    });
    expect(perform).not.toHaveBeenCalled();
    await act(async () => {
      first.resolve({ etag: 'e2' });
      await done;
    });
    expect(perform).toHaveBeenCalledTimes(1);
    act(() => result.current.save('after'));
    await waitFor(() => expect(send).toHaveBeenLastCalledWith('after', 'e3'));
  });

  it('runExclusive drops text queued during a successful restore', async () => {
    const gate = deferred<{ body: string; etag: string }>();
    const send = vi.fn().mockResolvedValue({ etag: 'e9' });
    const { result } = renderHook(() =>
      useGuardedSave({ body: 'a', etag: 'e1' }, { send, fetchLatest: vi.fn() }),
    );
    let done!: Promise<unknown>;
    act(() => {
      done = result.current.runExclusive(() => gate.promise);
    });
    act(() => result.current.save('typed during restore'));
    await act(async () => {
      gate.resolve({ body: 'restored', etag: 'e3' });
      await done;
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 40));
    });
    expect(send).not.toHaveBeenCalled();
  });

  it('runExclusive replays queued text when the restore fails', async () => {
    let fail!: (e: Error) => void;
    const gate = new Promise<{ body: string; etag: string }>((_, rej) => (fail = rej));
    const send = vi.fn().mockResolvedValue({ etag: 'e2' });
    const { result } = renderHook(() =>
      useGuardedSave({ body: 'a', etag: 'e1' }, { send, fetchLatest: vi.fn() }),
    );
    let done!: Promise<unknown>;
    act(() => {
      done = result.current.runExclusive(() => gate);
    });
    act(() => result.current.save('typed'));
    await act(async () => {
      fail(new Error('boom'));
      await expect(done).rejects.toThrow('boom');
    });
    await waitFor(() => expect(send).toHaveBeenCalledWith('typed', 'e1'));
  });

  it('runExclusive refuses while the conflict banner is up', async () => {
    const send = vi.fn().mockRejectedValueOnce(conflict());
    const fetchLatest = vi.fn().mockResolvedValue({ body: 'theirs', etag: 'e2' });
    const { result } = renderHook(() =>
      useGuardedSave({ body: 'a', etag: 'e1' }, { send, fetchLatest }),
    );
    act(() => result.current.save('mine'));
    await waitFor(() => expect(result.current.conflict).not.toBeNull());
    const perform = vi.fn();
    await expect(result.current.runExclusive(perform)).rejects.toThrow(RESTORE_BLOCKED);
    expect(perform).not.toHaveBeenCalled();
  });
```

Append to `desktop/src/renderer/__tests__/GuardedNoteEditor.test.tsx` (inside `describe('GuardedNoteEditor', …)`), and add `import { RESTORE_BLOCKED } from '../lib/use-guarded-save';`:

```tsx
  it('restore reloads the editor with the restored text and chains its etag', async () => {
    const send = vi.fn().mockResolvedValue({ etag: 'eeeeeeeeeeeeeeee' });
    const guardRef = { current: null } as React.MutableRefObject<GuardHandle | null>;
    const getEditor = setup(send, vi.fn(), guardRef);
    await waitFor(() => expect(guardRef.current).not.toBeNull());
    await act(async () => {
      await guardRef.current!.restore(async () => ({ body: 'restored text', etag: E2 }));
    });
    await screen.findByText('restored text');
    await typeTail(getEditor);
    await waitFor(() =>
      expect(send).toHaveBeenLastCalledWith(expect.stringContaining('restored text'), E2),
    );
  });

  it('an autosave scheduled before a restore never overwrites it', async () => {
    const send = vi.fn().mockResolvedValue({ etag: 'eeeeeeeeeeeeeeee' });
    const guardRef = { current: null } as React.MutableRefObject<GuardHandle | null>;
    const getEditor = setup(send, vi.fn(), guardRef);
    await typeTail(getEditor); // debounced save pending (10 ms)
    await act(async () => {
      await guardRef.current!.restore(async () => ({ body: 'restored text', etag: E2 }));
    });
    await screen.findByText('restored text');
    await act(async () => {
      await new Promise((r) => setTimeout(r, 60));
    });
    // Nothing based on the pre-restore text may be sent on the restored etag.
    expect(send.mock.calls.filter(([, ifMatch]) => ifMatch === E2)).toEqual([]);
  });

  it('restore is refused while the conflict banner is up', async () => {
    const send = vi.fn().mockRejectedValueOnce(new ApiError('changed', 409));
    const fetchLatest = vi.fn().mockResolvedValue({ body: 'their edit', etag: E2 });
    const guardRef = { current: null } as React.MutableRefObject<GuardHandle | null>;
    const getEditor = setup(send, fetchLatest, guardRef);
    await typeTail(getEditor);
    await screen.findByRole('alert');
    const perform = vi.fn();
    await expect(guardRef.current!.restore(perform)).rejects.toThrow(RESTORE_BLOCKED);
    expect(perform).not.toHaveBeenCalled();
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-plans2/desktop && npx vitest run src/renderer/__tests__/use-guarded-save.test.tsx src/renderer/__tests__/GuardedNoteEditor.test.tsx`
Expected: FAIL with `TypeError: result.current.runExclusive is not a function` / `guardRef.current.restore is not a function`

- [ ] **Step 3: Add `runExclusive` to the hook**

In `desktop/src/renderer/lib/use-guarded-save.ts`:

Add below the `asError` constant:

```ts
export const RESTORE_BLOCKED = 'resolve the conflict banner first (keep mine or keep theirs)';
const IDLE_POLL_MS = 20;
```

Add to the `GuardedSave` interface:

```ts
  /** Run a whole-note replacement (history restore) between autosaves: waits
   * for the in-flight save and its queue, adopts the result's etag, drops text
   * queued meanwhile on success (the editor reloads) and replays it on
   * failure. Rejects with RESTORE_BLOCKED while a conflict is up. */
  runExclusive: <T extends { body: string; etag?: string | null }>(
    perform: () => Promise<T>,
  ) => Promise<T>;
```

Add this function before `const keepTheirs = …`:

```ts
  const runExclusive = async <T extends { body: string; etag?: string | null }>(
    perform: () => Promise<T>,
  ): Promise<T> => {
    if (conflictRef.current) throw new Error(RESTORE_BLOCKED);
    while (inFlightRef.current) await new Promise((r) => setTimeout(r, IDLE_POLL_MS));
    if (conflictRef.current) throw new Error(RESTORE_BLOCKED);
    inFlightRef.current = true;
    let ok = false;
    try {
      const res = await perform();
      markSaved(res.body, res.etag);
      ok = true;
      return res;
    } finally {
      inFlightRef.current = false;
      const next = queuedRef.current;
      queuedRef.current = null;
      if (!ok && next !== null) void run(next);
    }
  };
```

Change the hook's return to:

```ts
  return { save, conflict, resolving, keepMine, keepTheirs, adopt, hasConflict, runExclusive };
```

- [ ] **Step 4: Add `restore` to the editor guard**

In `desktop/src/renderer/components/GuardedNoteEditor.tsx`:

Add to `GuardHandle`:

```ts
  /** Replace the note through `perform` (history restore) between autosaves,
   * then reload the editor with the result. Rejects under a conflict. */
  restore: (perform: () => Promise<{ body: string; etag?: string | null }>) => Promise<void>;
```

Directly after `const [doc, setDoc] = useState(...)`, add:

```tsx
  // Bumped synchronously on every reload, so a debounced save from the
  // replaced editor instance (scheduled before a restore) is dropped.
  const liveNonce = useRef(0);
  const remount = (body: string) => {
    liveNonce.current += 1;
    setDoc({ body, nonce: liveNonce.current });
  };
```

Replace the `useState<GuardHandle>` initializer with:

```tsx
  const [handle] = useState<GuardHandle>(() => ({
    adopt: (etag, body) => guardLatest.current.adopt(etag, body),
    hasConflict: () => guardLatest.current.hasConflict(),
    restore: async (perform) => {
      const res = await guardLatest.current.runExclusive(perform);
      remount(res.body);
    },
  }));
```

(`remount` only touches a ref and the stable `setDoc`, so capturing the first render's copy is safe.)

Replace `keepTheirs` with:

```tsx
  const keepTheirs = () => {
    const c = guard.keepTheirs();
    if (c) remount(c.theirs);
  };
```

Replace the `<RichMarkdownEditor … />` line with:

```tsx
      <RichMarkdownEditor
        key={doc.nonce}
        markdown={doc.body}
        onSave={(body) => {
          if (liveNonce.current === mountNonce) guard.save(body);
        }}
        {...editorProps}
      />
```

and add `const mountNonce = doc.nonce;` directly before the `return (`.

- [ ] **Step 5: Run the tests, typecheck and lint**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-plans2/desktop && npx vitest run src/renderer/__tests__/use-guarded-save.test.tsx src/renderer/__tests__/GuardedNoteEditor.test.tsx && npm run typecheck && npm run lint`
Expected: PASS (all existing keep-mine / keep-theirs tests still green)

- [ ] **Step 6: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-plans2 && git add desktop/src && git commit -m "feat(desktop): restore through the guarded save chain; drop stale-instance autosaves (A3)"
```

---

### Task 7: HistoryDrawer and the editor-header History button

**Files:**
- Create: `desktop/src/renderer/components/HistoryDrawer.tsx`
- Create: `desktop/src/renderer/components/NoteHistory.tsx`
- Modify: `desktop/src/renderer/components/NoteView.tsx` (header: before the "open in editor" button)
- Modify: `desktop/src/renderer/screens/jots.tsx` (TopBar `right`: first child of the button group)
- Test: `desktop/src/renderer/__tests__/HistoryDrawer.test.tsx`
- Test: `desktop/src/renderer/__tests__/NoteView.test.tsx` (append one test)

**Interfaces:**
- Consumes: `useNoteHistory`, `useHistoryVersion`, `useRestoreVersion` and the history types (Task 5); `LineDiffView` (Task 5); `GuardHandle.restore`, `RESTORE_BLOCKED` (Task 6); `sameBody` from `lib/use-guarded-save`; `formatRelativeTime` from `lib/format`.
- Produces:
  - `actorLabel(actor: string): string`: `user → "you"`, `assistant → "✦ assistant"`, `mcp → "⌁ mcp"`, `restore → "↺ restore"`, `plugin:x → "⧉ x"`, `worker:x → "⚙ x"`. B2's Changes screen reuses it.
  - `<HistoryDrawer path onClose onRestore={(entry: HistoryEntry) => Promise<void>} />`.
  - `<NoteHistoryButton path={string | null} guardRef={MutableRefObject<GuardHandle | null>} />`. Parents key it by path, so switching notes closes the drawer.

- [ ] **Step 1: Write the failing tests**

Create `desktop/src/renderer/__tests__/HistoryDrawer.test.tsx`:

```tsx
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as client from '../lib/api/client';
import { HistoryDrawer, actorLabel } from '../components/HistoryDrawer';
import { NoteHistoryButton } from '../components/NoteHistory';
import type { GuardHandle } from '../components/GuardedNoteEditor';
import { RESTORE_BLOCKED } from '../lib/use-guarded-save';
import { useToasts } from '../stores/toast';
import type {
  HistoryBlobResponse,
  NoteHistoryResponse,
  RestoreHistoryResponse,
} from '../../shared/api-types';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ApiError: actual.ApiError, get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn() };
});
const getMock = vi.mocked(client.get);
const postMock = vi.mocked(client.post);

const PATH = '20-contexts/work/notes/plan.md';
const B1 = 'a'.repeat(64);
const B2 = 'b'.repeat(64);
const HISTORY: NoteHistoryResponse = {
  path: PATH,
  items: [
    { ts: '2026-10-09T10:05:00+00:00', path: PATH, blob: B2, actor: 'assistant', reason: 'polished intro', size: 40 },
    { ts: '2026-10-09T10:00:00+00:00', path: PATH, blob: B1, actor: 'user', reason: 'edited in the editor', size: 30 },
  ],
};
const VERSIONS: Record<string, HistoryBlobResponse> = {
  [B2]: { path: PATH, blob: B2, content: 'keep\nold intro', current: 'keep\nnew intro' },
  [B1]: { path: PATH, blob: B1, content: 'keep\nnew intro', current: 'keep\nnew intro' },
};

function routeGets(history: NoteHistoryResponse = HISTORY) {
  getMock.mockImplementation((async (url: string) => {
    if (url.startsWith('/v1/notes/history/blob')) {
      const blob = new URLSearchParams(url.split('?')[1]).get('blob')!;
      return VERSIONS[blob];
    }
    if (url.startsWith('/v1/notes/history')) return history;
    throw new Error(`unexpected GET ${url}`);
  }) as unknown as typeof client.get);
}

function withQuery(children: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

afterEach(() => {
  getMock.mockReset();
  postMock.mockReset();
  useToasts.setState({ toasts: [] });
});

describe('actorLabel', () => {
  it('labels every actor kind', () => {
    expect(actorLabel('user')).toBe('you');
    expect(actorLabel('assistant')).toBe('✦ assistant');
    expect(actorLabel('mcp')).toBe('⌁ mcp');
    expect(actorLabel('restore')).toBe('↺ restore');
    expect(actorLabel('plugin:familiar')).toBe('⧉ familiar');
    expect(actorLabel('worker:reversal')).toBe('⚙ reversal');
  });
});

describe('HistoryDrawer', () => {
  it('lists versions with actor badges and diffs the newest against current', async () => {
    routeGets();
    render(withQuery(<HistoryDrawer path={PATH} onClose={() => {}} onRestore={vi.fn()} />));
    expect(await screen.findByText('polished intro')).toBeInTheDocument();
    expect(screen.getAllByTestId('actor-badge').map((b) => b.textContent)).toEqual(['✦ assistant', 'you']);
    const diff = await screen.findByTestId('history-diff');
    expect(diff).toHaveTextContent('- old intro');
    expect(diff).toHaveTextContent('+ new intro');
  });

  it('loads another version when it is picked', async () => {
    routeGets();
    render(withQuery(<HistoryDrawer path={PATH} onClose={() => {}} onRestore={vi.fn()} />));
    fireEvent.click(await screen.findByText('edited in the editor'));
    await waitFor(() =>
      expect(getMock).toHaveBeenCalledWith(
        `/v1/notes/history/blob?path=${encodeURIComponent(PATH)}&blob=${B1}`,
      ),
    );
    expect(await screen.findByText('same as the current version')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'restore this version' })).toBeDisabled();
  });

  it('restores the selected version and closes', async () => {
    routeGets();
    const onRestore = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();
    render(withQuery(<HistoryDrawer path={PATH} onClose={onClose} onRestore={onRestore} />));
    await screen.findByTestId('history-diff');
    fireEvent.click(screen.getByRole('button', { name: 'restore this version' }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(onRestore).toHaveBeenCalledWith(HISTORY.items[0]);
  });

  it('keeps the drawer open and explains a refused restore', async () => {
    routeGets();
    const onRestore = vi.fn().mockRejectedValue(new Error(RESTORE_BLOCKED));
    const onClose = vi.fn();
    render(withQuery(<HistoryDrawer path={PATH} onClose={onClose} onRestore={onRestore} />));
    await screen.findByTestId('history-diff');
    fireEvent.click(screen.getByRole('button', { name: 'restore this version' }));
    await waitFor(() =>
      expect(useToasts.getState().toasts.map((t) => t.message)).toEqual([
        `restore failed: ${RESTORE_BLOCKED}`,
      ]),
    );
    expect(onClose).not.toHaveBeenCalled();
  });

  it('shows an empty state before the first edit', async () => {
    routeGets({ path: PATH, items: [] });
    render(withQuery(<HistoryDrawer path={PATH} onClose={() => {}} onRestore={vi.fn()} />));
    expect(await screen.findByText(/no earlier versions yet/)).toBeInTheDocument();
  });
});

describe('NoteHistoryButton', () => {
  it('restores through the editor guard', async () => {
    routeGets();
    const restored: RestoreHistoryResponse = {
      path: PATH, etag: 'ffffffffffffffff', body: 'old intro', restored: B2, historyOk: true,
    };
    postMock.mockResolvedValue(restored);
    const restore = vi.fn(async (perform: () => Promise<unknown>) => {
      await perform();
    });
    const guardRef = {
      current: { adopt: vi.fn(), hasConflict: () => false, restore },
    } as unknown as React.MutableRefObject<GuardHandle | null>;
    render(withQuery(<NoteHistoryButton path={PATH} guardRef={guardRef} />));
    fireEvent.click(screen.getByRole('button', { name: 'history' }));
    await screen.findByTestId('history-diff');
    fireEvent.click(screen.getByRole('button', { name: 'restore this version' }));
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith('/v1/notes/history/restore', { path: PATH, blob: B2 }),
    );
    expect(restore).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'page history' })).toBeNull());
  });
});
```

Append to `desktop/src/renderer/__tests__/NoteView.test.tsx` (inside `describe('NoteView', …)`):

```tsx
  it('offers page history in the header', async () => {
    apiRequest.mockResolvedValue({ ok: true, data: manualNote });
    render(withQuery(<NoteView />));
    act(() => useNoteView.getState().open(manualNote.path));
    await screen.findByText('hand-written');
    expect(screen.getByRole('button', { name: 'history' })).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-plans2/desktop && npx vitest run src/renderer/__tests__/HistoryDrawer.test.tsx src/renderer/__tests__/NoteView.test.tsx`
Expected: FAIL. Resolving `../components/HistoryDrawer` fails, and NoteView has no `history` button.

- [ ] **Step 3: Write the drawer**

Create `desktop/src/renderer/components/HistoryDrawer.tsx`:

```tsx
import { useState } from 'react';
import { useHistoryVersion, useNoteHistory } from '../lib/api/hooks';
import { formatRelativeTime } from '../lib/format';
import { sameBody } from '../lib/use-guarded-save';
import type { HistoryEntry } from '../../shared/api-types';
import { toast } from '../stores/toast';
import { Btn } from './Btn';
import { LineDiffView } from './LineDiffView';
import { Lucide } from './Lucide';

/** Short label for the writer a snapshot was taken before. Shared with spec B's Changes screen. */
export function actorLabel(actor: string): string {
  if (actor === 'user') return 'you';
  if (actor === 'assistant') return '✦ assistant';
  if (actor === 'mcp') return '⌁ mcp';
  if (actor === 'restore') return '↺ restore';
  if (actor.startsWith('plugin:')) return `⧉ ${actor.slice('plugin:'.length)}`;
  if (actor.startsWith('worker:')) return `⚙ ${actor.slice('worker:'.length)}`;
  return actor;
}

// The same content can be snapshotted twice, so a blob alone is not a key.
const entryKey = (e: HistoryEntry): string => `${e.ts}|${e.blob}`;

interface Props {
  path: string;
  onClose: () => void;
  /** Restores `entry` through the editor guard; rejects with a user-facing message. */
  onRestore: (entry: HistoryEntry) => Promise<void>;
}

/** Spec A3: timeline of versions, actor badge, diff against the current file, restore. */
export function HistoryDrawer({ path, onClose, onRestore }: Props) {
  const history = useNoteHistory(path);
  const items = history.data?.items ?? [];
  const [picked, setPicked] = useState<string | null>(null);
  const selected = items.find((e) => entryKey(e) === picked) ?? items[0] ?? null;
  const version = useHistoryVersion(path, selected?.blob ?? null);
  const [restoring, setRestoring] = useState(false);
  const current = version.data?.current ?? null;
  const unchanged =
    version.data !== undefined && current !== null && sameBody(version.data.content, current);

  const restore = async () => {
    if (!selected) return;
    setRestoring(true);
    try {
      await onRestore(selected);
      toast.success('version restored — the replaced text is in history');
      onClose();
    } catch (err) {
      toast.error(`restore failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setRestoring(false);
    }
  };

  return (
    <aside
      role="dialog"
      aria-label="page history"
      className="fixed inset-y-0 right-0 z-50 flex w-[760px] max-w-[94vw] flex-col border-l border-hairline bg-paper shadow-xl"
      onClick={(e) => e.stopPropagation()}
    >
      <header className="flex items-center gap-2 border-b border-hairline px-4 py-3">
        <Lucide name="history" size={14} color="var(--ink-2)" />
        <div className="flex-1 text-13 font-medium text-ink-0">page history</div>
        <Btn
          variant="ghost"
          size="sm"
          icon={<Lucide name="x" size={14} />}
          onClick={onClose}
          ariaLabel="close history"
        />
      </header>
      <div className="flex min-h-0 flex-1">
        <ol aria-label="versions" className="w-[240px] flex-shrink-0 overflow-y-auto border-r border-hairline">
          {history.isLoading && <li className="p-4 text-11 text-ink-3">loading…</li>}
          {history.isError && (
            <li className="p-4 text-11 text-ink-3">
              history unavailable{' '}
              <button type="button" className="underline" onClick={() => void history.refetch()}>
                retry
              </button>
            </li>
          )}
          {history.isSuccess && items.length === 0 && (
            <li className="p-4 text-11 text-ink-3">
              no earlier versions yet — they appear after the note is edited
            </li>
          )}
          {items.map((e) => {
            const active = selected !== null && entryKey(e) === entryKey(selected);
            return (
              <li key={entryKey(e)}>
                <button
                  type="button"
                  title={e.ts}
                  aria-current={active ? 'true' : undefined}
                  onClick={() => setPicked(entryKey(e))}
                  className={`w-full px-4 py-2 text-left hover:bg-fog/50 ${active ? 'bg-fog/60' : ''}`}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-12 text-ink-0">{formatRelativeTime(e.ts)}</span>
                    <span
                      data-testid="actor-badge"
                      className="rounded-sm border border-hairline px-1 font-mono text-10 text-ink-2"
                    >
                      {actorLabel(e.actor)}
                    </span>
                  </div>
                  {e.reason && <div className="truncate text-11 text-ink-2">{e.reason}</div>}
                </button>
              </li>
            );
          })}
        </ol>
        <section className="flex min-w-0 flex-1 flex-col">
          {selected !== null && version.isLoading && (
            <div className="p-4 text-11 text-ink-3">loading version…</div>
          )}
          {version.isError && (
            <div className="p-4 text-11 text-ink-3">this version could not be loaded</div>
          )}
          {version.data && (
            <>
              <div className="flex-1 overflow-auto p-4">
                {current === null ? (
                  <div className="text-11 text-ink-3">
                    this note no longer exists on disk — restoring recreates it
                  </div>
                ) : unchanged ? (
                  <div className="text-11 text-ink-3">same as the current version</div>
                ) : (
                  <LineDiffView
                    testId="history-diff"
                    oldText={version.data.content}
                    newText={current}
                    legend="- this version · + current"
                  />
                )}
              </div>
              <footer className="flex items-center justify-end gap-2 border-t border-hairline px-4 py-2">
                <Btn
                  variant="primary"
                  size="sm"
                  icon={<Lucide name="rotate-ccw" size={13} />}
                  onClick={() => void restore()}
                  disabled={restoring || unchanged}
                >
                  {restoring ? 'restoring…' : 'restore this version'}
                </Btn>
              </footer>
            </>
          )}
        </section>
      </div>
    </aside>
  );
}
```

If `Btn`'s accessible name includes the icon (it renders no text), the `getByRole('button', { name: 'restore this version' })` query still matches. If `npm run lint` flags the `fog/60` class or another token, use the same classes `BacklinksPanel` uses (`hover:bg-fog/50`) for both the active and hover states.

- [ ] **Step 4: Write the header button**

Create `desktop/src/renderer/components/NoteHistory.tsx`:

```tsx
import { useState } from 'react';
import { useRestoreVersion } from '../lib/api/hooks';
import type { HistoryEntry } from '../../shared/api-types';
import { Btn } from './Btn';
import type { GuardHandle } from './GuardedNoteEditor';
import { HistoryDrawer } from './HistoryDrawer';
import { Lucide } from './Lucide';

interface Props {
  /** Vault-relative path of the open note; null hides the button. */
  path: string | null;
  /** The open editor's guard: restore runs between its autosaves and reloads it. */
  guardRef: React.MutableRefObject<GuardHandle | null>;
}

/** "History" item for an editor header. Parents key it by path so switching notes closes the drawer. */
export function NoteHistoryButton({ path, guardRef }: Props) {
  const [open, setOpen] = useState(false);
  const restoreVersion = useRestoreVersion();
  if (path === null) return null;

  const onRestore = async (entry: HistoryEntry): Promise<void> => {
    const guard = guardRef.current;
    if (!guard) throw new Error('the editor is still loading');
    await guard.restore(() => restoreVersion.mutateAsync({ path, blob: entry.blob }));
  };

  return (
    <>
      <Btn
        variant="ghost"
        size="sm"
        icon={<Lucide name="history" size={13} />}
        onClick={() => setOpen(true)}
      >
        history
      </Btn>
      {open && <HistoryDrawer path={path} onClose={() => setOpen(false)} onRestore={onRestore} />}
    </>
  );
}
```

- [ ] **Step 5: Mount it in both editor headers**

In `desktop/src/renderer/components/NoteView.tsx`, add `import { NoteHistoryButton } from './NoteHistory';`. In the `<header>`, directly before the "open in editor" `<Btn …>`, add:

```tsx
          <NoteHistoryButton key={path} path={path} guardRef={guardRef} />
```

In `desktop/src/renderer/screens/jots.tsx`, add `import { NoteHistoryButton } from '../components/NoteHistory';`. Inside the TopBar `right={<div className="flex gap-2">…` add as the first child:

```tsx
            {selectedItem && (
              <NoteHistoryButton key={selectedItem.path} path={selectedItem.path} guardRef={guardRef} />
            )}
```

(`guardRef` is the existing `useRef<GuardHandle | null>` already passed to `GuardedNoteEditor` on both screens. The jot path changes on re-route, which closes the drawer, and the store has moved the history to the new path (Task 3).)

- [ ] **Step 6: Run the full desktop gates**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-plans2/desktop && npx vitest run && npm run typecheck && npm run lint`
Expected: PASS (whole suite: `jots.test.tsx` and `NoteView.test.tsx` mock `window.gb.api.request`, and the drawer fetches nothing until it opens)

- [ ] **Step 7: Run the full backend suite once more**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-plans2 && python -m pytest ghostbrain/api/tests tests/test_history_store.py tests/test_history_retention.py tests/test_vault_write_history.py tests/test_vault_write_writer.py tests/test_vault_write_text.py tests/test_vault_index_links.py -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-plans2 && git add desktop/src && git commit -m "feat(desktop): HistoryDrawer with diff and restore in the note and jot editors (A3)"
```

---

## Self-Review

**Spec coverage (A3 + the parts of spec B that touch the store):**
- Content-addressed `blobs/<sha256>.md`, per-note `notes/<sha1(rel)>.jsonl` with `{ts, rel_path, blob, actor, reason}` → Task 1.
- Snapshot before any write that changes the note, coalesced for user (5 min), never for non-user → Task 1 (policy), Task 3 (hook: modify/move/delete; no snapshot on create or no-op).
- `PATCH /v1/notes/{jot_id}` and `/body` snapshot as user → Task 3, through the shared write path (pinned over HTTP in Task 4).
- Retention 30 d / daily for a year / monthly, daily prune + blob GC → Task 2.
- Three routes (list, blob, restore with the `restore` actor snapshot first) → Task 4.
- HistoryDrawer: timeline, actor badge, line diff vs current, Restore; "History" item in the editor header → Tasks 5 and 7.
- Error handling: user save proceeds plus a once-per-session toast → Tasks 3, 4 and 5. Non-user refused with 500 `history unavailable`, file untouched → Tasks 3 and 4.
- Spec B: `history.snapshot` at §1 step 5 with abort-for-non-user → Task 3. `before_blob`/`after_blob` ids → `put_blob`/`blob_id`/`Snapshot.blob`. Pruning of change rows by the history job → `register_ref_source` keeps their blobs, and B2 adds its own row pruning inside its module. "HistoryDrawer diff component" reuse → `LineDiffView` + `actorLabel`. "Keep mine snapshots theirs" → Task 3/4 tests.
- Pytest list in the spec: blob dedupe (T1), coalescing window per actor (T1), retention pruning (T2), restore snapshots first (T4). Vitest: HistoryDrawer diff and restore call (T7).

**Spec ambiguities resolved:**
1. `~/.ghostbrain/history` vs `state_dir()`: the spec says both, and `state_dir()` is `~/.ghostbrain/state`. The plan follows the "via `state_dir()`" convention, so history lives at `~/.ghostbrain/state/history` and test sandboxing works.
2. "At most one per 5 minutes of continuous editing" is read as at most one user snapshot per 5 minutes, measured from the last kept snapshot. Coalescing happens only while the file still holds what the app's last user write left. Deletes are never coalesced.
3. Restore needs an actor `restore` that B1's actor grammar lacked. It is added as a real `Actor`. It counts as non-user for history (never coalesced, failure refuses). B2 decides whether restore writes get change rows. Spec B's revert writes as `user`.
4. The spec names the `diff` npm package. B1 already ships `lineDiff` for exactly this reuse, so there is no new dependency.
5. How the "history unavailable" toast learns about failures: a `historyOk` field on the two user-save responses (and restore), reported once per session.
6. The diff compares whole files (frontmatter included), because restore writes whole files.
7. No size cap on blobs. Dedupe plus retention bound the storage, and the list route caps at 1000 entries per call (default 200).
8. The desktop restore sends no `If-Match`, because restore snapshots the current version first, so nothing on disk is lost. The editor side is serialised by `runExclusive`. The route still honours `If-Match` for other callers.

**Placeholder scan:** no TBD/TODO. Every code step has full code. The one conditional instruction (the Btn/lint class fallback in Task 7, Step 3) names the exact replacement.

**Type consistency:** `snapshot(rel_path, before, *, actor, reason, after) -> Snapshot | None` is the same in Tasks 1, 2 and 3. `_snapshot` returns `tuple[Snapshot | None, bool]` and is unpacked as such. `WriteResult.history_ok` → `historyOk` in Task 4 → `historyOk?` in Task 5 types → `reportHistoryHealth`. `runExclusive<T extends {body; etag?}>` (Task 6) is used by `GuardHandle.restore` (Task 6), which `NoteHistoryButton` (Task 7) calls with `restoreVersion.mutateAsync` returning `RestoreHistoryResponse` (`body`, `etag`). `HistoryEntry` fields match the route's `_entry` keys (`ts, path, blob, actor, reason, size`).

**Review Focus check:** each of the five lines has a named test in its owning task (Tasks 1, 2, 3, 4 and 6).
