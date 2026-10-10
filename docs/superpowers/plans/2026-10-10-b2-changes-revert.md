# B2 Change Log + Changes Screen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every vault change made by an assistant, the MCP tools, a plugin or a worker job is attributed, recorded in a change log, and listed on a new Changes screen with a per-change diff and one-click Revert. Revert is refused when the file changed since, unless the user forces it.

**Architecture:** A new `ghostbrain/changes/` package owns a stdlib-SQLite change log (`state_dir()/changes.db`). Rows hold attribution and blob ids. The bytes live in A3's page-history store (`ghostbrain.history`). The B1 write path (`vault_write._write`) records a row for every non-user write, under the per-path lock, right after the atomic replace. Before writing, it stores the before-version (A3's snapshot) and the after-version (`put_blob`). It also exposes a hold-policy hook that B3's risk rules plug into, which produces `pending` rows. Attribution travels as an `X-Poltergeist-Actor` header. The Electron forwarder stamps `user`/`assistant`, the plugin bridges stamp `plugin:<id>`, and the MCP client stamps `mcp`. The sidecar maps the header to the `actor` of every write route. `ghostbrain/changes/revert.py` reverts or re-applies a row through the write path as the `restore` actor, so the replaced version always lands in page history. `/v1/changes` routes and a React Changes screen sit on top. The screen reuses A3's `LineDiffView` and `actorLabel`.

**Tech Stack:** Python 3.11 stdlib (`sqlite3`, `difflib`, `threading`), FastAPI, pytest; Electron main (TypeScript), React 18 + TanStack Query 5 + zustand, Vitest + Testing Library, `tsc -b`.

**Spec:** `docs/superpowers/specs/2026-10-09-ai-changes-revert-design.md`. This plan covers §2 (actor attribution), §4 (change log), §5 (routes, without approve/reject), §6 (Changes screen, without the Pending section and nav badge) and the error-handling and testing rows for those parts. It builds on A3's plan, `docs/superpowers/plans/2026-10-09-a3-page-history.md`: read its Task 1–3 Interfaces before starting.

## Global Constraints

- **B2 must be built on a branch that already contains A3 (page history).** Branch from `feat/a3-page-history`, or from `main` once A3 is merged. Before Task 1, run `cd "$B2" && python -c "import ghostbrain.history as h; from ghostbrain.vault_write import RESTORE; from ghostbrain.vault_write.writer import _snapshot; print(h.register_ref_source, RESTORE)"`. It must print without an error. If it fails, stop: A3 is missing.
- Every command runs from the B2 worktree root. Export it once per shell: `export B2=/absolute/path/to/your/b2/worktree`. The commands below use `cd "$B2" && …`. Never run the app, and never touch `~/ghostbrain` or `~/.ghostbrain`. The root `conftest.py` sandboxes `GHOSTBRAIN_STATE_DIR` and `VAULT_PATH` per test.
- A3's store is used **exactly** as its plan defines it: `history.blob_id`, `put_blob`, `get_blob`, `has_blob`, `snapshot`, `list_snapshots`, `register_ref_source`, `prune`, `BlobNotFound`, `HistoryUnavailable`, `vault_write.RESTORE`, `writer._snapshot`, `writer._move_history`, and `WriteResult.history_ok`. Blob ids are 64-hex sha256 of the **whole file bytes**. Etags are the first 16 hex of the same hash.
- Change log location: `ghostbrain.paths.state_dir() / "changes.db"` (SQLite via the stdlib). That is `~/.ghostbrain/state/changes.db` by default. The spec's `~/.ghostbrain/changes.db` is the same directory family; the user asked for the state dir.
- Table `changes` columns, copied from spec §4: `id, ts, actor, rel_path, dest_path, op, reason, before_blob, after_blob, pending_bytes_blob, status, risk_reasons` (JSON). B2 adds `resolved_ts`. Statuses: `applied | pending | reverted | rejected | conflicted`. Indexed by `ts` and `status`, plus `rel_path`.
- Blob columns hold A3 blob ids. **No file content is ever stored in the DB.** `before_blob` is null for a create. `after_blob` is null for a delete and for a pending row. `pending_bytes_blob` is set only on a pending row.
- Actors: `user | assistant | mcp | plugin:<id> | worker:<job>` plus A3's `restore`. Over HTTP the sidecar accepts `user`, `assistant`, `mcp` and `plugin:<id>` in `X-Poltergeist-Actor`. A missing or blank header means `user`. `worker:*` and `restore` are in-process only, so the header is refused with 400.
- **Who gets a row:** every write by an actor other than `user` and `restore`, **except a `worker:*` create**. User decision 1: connector ingest stays audit-only and is not on the Changes screen. User writes get page history only (spec §1 step 7).
- **User decision 2:** assistant-created new notes apply immediately and are revertible. B2 holds nothing. The hold-policy hook defaults to "never hold". B3 installs the risk rules.
- **`base_etag` required (spec §1, B1 deferral):** for every actor except `user`, `restore` and `worker:*`, a `modify`/`delete`/`move` without `base_etag` raises `EtagRequired` (HTTP **428**). There is one exception. When the file still holds exactly what that same actor last wrote there (its latest `applied` row's `after_blob`), that row is the implicit base. That is what keeps a plugin's routine re-upsert of its own note working with no etag. A broken change log fails closed (428). User writes keep `base_etag` optional: the editor always sends it, and explicit user actions (re-route, delete) act on the user's own command.
- Revert succeeds only when the file at the change's current path hashes to the expected blob (`after_blob` for revert, `before_blob` for undo). Otherwise it fails with **409** unless `force: true`. Revert and undo write as `restore`, so the replaced version is always snapshotted (A3: `restore` is never coalesced, and a history failure refuses the write) and no new change row is added. Reverting and undoing are **user-only** (403 for any other actor header).
- Retention: change rows are kept for **1 year**, and pending rows are never pruned. Pruning is done by A3's daily `history-prune` job. The change log registers itself with `history.register_ref_source("changes", …)` so blob GC never deletes a blob a row names.
- Change-log insert fails after a successful write → the write stands, the failure is logged, and a "degraded" marker file makes the Changes screen show "some changes may be missing; see page history".
- Out of scope (later slices): risk rules (`risk.py`), approve/reject routes, the Pending section and the nav badge are **B3**. `worker/reversal.py` and `profile/apply.py` are **B4**. B2 leaves the B3 hook described in Task 2.
- The docs library (#144, `ghostbrain/api/repo/doc_library`) is **not** attributed or listed. Its writes are user-initiated uploads, moves, renames and deletes with deterministic extraction (no LLM). They include binary originals, which the write path does not handle (`WRITABLE_SUFFIXES = (".md", ".html")`). This is a known gap: a plugin calling `/v1/library/*` is not recorded.
- No new pip or npm dependency. Diffs in the renderer use A3's `LineDiffView`. The API's unified diff uses Python `difflib`.
- Python tests run with `python -m pytest`. Every new CI-safe file under `tests/` goes into the fixed list in `.github/workflows/ci.yml`. Files under `ghostbrain/api/tests/` are picked up automatically. The CI backend installs only `[dev,api]`.
- Desktop gates: `npm run typecheck` (tsc -b), `npx vitest run`, `npm run lint` (`--max-warnings 0`). Windows release builds rerun the desktop tests, so assertions must not depend on POSIX paths, line endings, the time zone or the locale.
- No real people's or employer names in code, fixtures or copy.

## Review Focus

1. **A plugin re-upserting a note it owns, with no `If-Match`** (Familiar's daily write-back). That must keep working. Once the user has edited that note, the same call must be refused (428), not overwrite the edit. Pinned in Task 2 (`test_a_plugin_may_rewrite_its_own_untouched_note_without_an_etag`, `test_another_actors_last_write_is_not_an_implicit_base`) and Task 5 over HTTP (`test_plugin_header_attributes_and_allows_rewriting_its_own_note`).
2. **Revert → undo → revert on a note with CRLF line endings and no trailing newline.** It must be byte-exact. Otherwise undo would claim "changed since" against bytes the app itself wrote. Pinned in Task 3 (`test_round_trip_is_byte_exact_without_a_trailing_newline_and_with_crlf`), which relies on Task 2's `verbatim=True`.
3. **A blob that only a change row still names.** Page-history retention can drop a note's log entry after 30 days while the change row lives for a year. Blob GC must keep that blob, and must skip GC entirely when the change log can't be read. Pinned in Task 4 (`test_blobs_named_only_by_change_rows_survive_gc`, `test_a_broken_change_log_skips_blob_gc`).
4. **Reverting a moved jot after something new was created at its old path.** The new file must never be overwritten (409), and the row must stay `applied`. Pinned in Task 3 (`test_revert_of_a_move_never_overwrites_a_note_now_at_the_old_path`).
5. **A docs-panel Accept that lands while an autosave is in flight.** The queued save must keep its `assistant` mark, so it isn't silently recorded as a user edit. The mark must also not leak onto the user's next keystrokes. Pinned in Task 9 (`an attributed save queued behind an in-flight save keeps its mark`, `attributeNext marks only the next save`).

---

## File Structure

| File | Responsibility |
|---|---|
| `ghostbrain/changes/__init__.py` (new) | Re-exports the change-log API (never imports `revert`, to avoid an import cycle with `vault_write`) |
| `ghostbrain/changes/log.py` (new) | SQLite schema, `Change`, record/get/list/set_status/counts, implicit-base lookup, ref source, retention, degraded marker |
| `ghostbrain/changes/revert.py` (new) | Revert / undo of a row through the write path as `restore`; drift detection |
| `ghostbrain/changes/maintenance.py` (new) | `run_prune`: change-log retention, then A3's history prune + GC |
| `ghostbrain/vault_write/errors.py` | + `EtagRequired` |
| `ghostbrain/vault_write/writer.py` | Records change rows; `base_etag` rule; hold-policy hook (B3); `verbatim`; move with `content` |
| `ghostbrain/vault_write/__init__.py` | Re-export the new names |
| `ghostbrain/api/vault_http.py` | `EtagRequired` → 428; `request_actor` header dependency |
| `ghostbrain/api/routes/notes.py`, `ghostbrain/api/routes/docs.py` | Actor from the header on every write route |
| `ghostbrain/api/repo/note.py`, `ghostbrain/api/repo/notes_manual.py`, `ghostbrain/api/repo/generated_docs.py` | `reason` / `base_etag` / `actor` parameters; extract-photo sends its etag |
| `ghostbrain/api/models/changes.py` (new), `ghostbrain/api/routes/changes.py` (new) | `/v1/changes` list, detail, revert, undo, degraded dismiss |
| `ghostbrain/api/main.py` | Include the changes router |
| `ghostbrain/scheduler_jobs.py` | `history-prune` runs `run_prune` |
| `ghostbrain/mcp/client.py` | Sends `X-Poltergeist-Actor: mcp` |
| `desktop/src/shared/types.ts` | `WriteActor`; `actor` bridge option; plugin request `opts` |
| `desktop/src/main/api-forwarder.ts` | `ACTOR_HEADER`, `requestHeadersFrom` (user/assistant), `pluginHeadersFrom` |
| `desktop/src/main/plugins/ipc.ts`, `desktop/src/main/plugins/loader.ts`, `desktop/src/main/index.ts`, `desktop/src/preload/index.ts` | Plugin id threaded through both plugin bridges and stamped |
| `desktop/src/renderer/lib/api/client.ts`, `desktop/src/renderer/lib/api/hooks.ts` | `actor` patch option; change-log hooks |
| `desktop/src/renderer/lib/use-guarded-save.ts`, `desktop/src/renderer/components/GuardedNoteEditor.tsx` | `attributeNext('assistant')` |
| `desktop/src/renderer/components/DocsAssistPanel.tsx`, `desktop/src/renderer/screens/jots.tsx` | Accept marks the next save as the assistant's |
| `desktop/src/shared/api-types.ts` | Change-log types |
| `desktop/src/renderer/screens/changes.tsx` (new) | The Changes screen |
| `desktop/src/renderer/stores/navigation.ts`, `desktop/src/renderer/components/Sidebar.tsx`, `desktop/src/renderer/App.tsx` | Nav item + route |
| `.github/workflows/ci.yml` | Five new or newly listed `tests/` files |

---

### Task 1: Change-log store

**Files:**
- Create: `ghostbrain/changes/__init__.py`
- Create: `ghostbrain/changes/log.py`
- Test: `tests/test_changes_log.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `ghostbrain.paths.state_dir() -> Path`; `ghostbrain.history.register_ref_source(name, source)` (A3 Task 2).
- Produces (importable from `ghostbrain.changes` and `ghostbrain.changes.log`):
  - Constants: `DB_NAME = "changes.db"`, `RETENTION = timedelta(days=365)`, `OPS = ("create", "modify", "delete", "move")`, `STATUSES = ("applied", "pending", "reverted", "rejected", "conflicted")`.
  - `class ChangeLogError(Exception)`: any SQLite or OS failure.
  - `@dataclass(frozen=True) Change(id: int, ts: str, actor: str, rel_path: str, dest_path: str | None, op: str, reason: str, before_blob: str | None, after_blob: str | None, pending_bytes_blob: str | None, status: str, risk_reasons: tuple[str, ...], resolved_ts: str | None)`, with `.current_path -> str` (`dest_path or rel_path`) and `.to_api() -> dict` (`{id, ts, actor, path, destPath, op, reason, status, riskReasons, resolvedTs}`).
  - `db_path() -> Path`.
  - `record(*, actor: str, rel_path: str, op: str, reason: str = "", before_blob: str | None = None, after_blob: str | None = None, dest_path: str | None = None, status: str = "applied", pending_bytes_blob: str | None = None, risk_reasons: Iterable[str] = ()) -> int`. `status` must be `applied` or `pending`.
  - `get(change_id: int) -> Change | None`.
  - `list_changes(*, status: str | None = None, actor: str | None = None, since: datetime | None = None, path_query: str | None = None, limit: int = 100) -> list[Change]`: newest first. `actor="plugin"`/`"worker"` matches the whole kind. `path_query` is a case-insensitive substring of `rel_path` or `dest_path`.
  - `set_status(change_id: int, status: str, *, expect: Iterable[str]) -> bool`: compare-and-set. It sets `resolved_ts` for `reverted | rejected | conflicted` and clears it otherwise.
  - `counts() -> dict[str, int]`.
  - `last_after_blob(path: str, actor: str) -> str | None`: the `after_blob` of `actor`'s newest `applied` row whose current path is `path`.
  - `referenced_blobs() -> list[str]`: every non-null blob id in the table, sorted and unique.
  - `prune(now: datetime | None = None, *, keep: timedelta = RETENTION) -> int`: deletes non-pending rows older than `keep` and returns the count.
  - `mark_degraded(reason: str) -> None`, `degraded() -> str | None` (ts of the last failure), `clear_degraded() -> None`.
  - `register_with_history() -> None`: registers `"changes"` as an A3 ref source. It is idempotent and runs at import.
  - Test seam: `log._now() -> datetime` (UTC).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_changes_log.py`:

```python
"""Change-log store (spec B §4, slice B2)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ghostbrain.changes import log as changes
from ghostbrain.history import store

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
B = "a" * 64
C = "b" * 64
D = "c" * 64


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch):
    now = {"t": NOW}
    monkeypatch.setattr(changes, "_now", lambda: now["t"])

    def set_time(t: datetime) -> None:
        now["t"] = t

    return set_time


def test_db_lives_in_the_state_dir(tmp_path):
    # Root conftest: GHOSTBRAIN_STATE_DIR = tmp_path/state.
    assert changes.db_path() == (tmp_path / "state").resolve() / "changes.db"


def test_record_and_get_round_trip(clock):
    cid = changes.record(
        actor="assistant", rel_path="a.md", op="modify", reason="polish",
        before_blob=B, after_blob=C,
    )
    c = changes.get(cid)
    assert c == changes.Change(
        id=cid, ts=NOW.isoformat(), actor="assistant", rel_path="a.md", dest_path=None,
        op="modify", reason="polish", before_blob=B, after_blob=C, pending_bytes_blob=None,
        status="applied", risk_reasons=(), resolved_ts=None,
    )
    assert c.current_path == "a.md"
    assert c.to_api() == {
        "id": cid, "ts": NOW.isoformat(), "actor": "assistant", "path": "a.md",
        "destPath": None, "op": "modify", "reason": "polish", "status": "applied",
        "riskReasons": [], "resolvedTs": None,
    }
    assert changes.get(cid + 1) is None


def test_record_rejects_unknown_ops_and_final_statuses():
    with pytest.raises(ValueError):
        changes.record(actor="mcp", rel_path="a.md", op="rename")
    with pytest.raises(ValueError):
        changes.record(actor="mcp", rel_path="a.md", op="create", status="reverted")


def test_list_is_newest_first_and_filters(clock):
    a = changes.record(actor="assistant", rel_path="20-contexts/work/plan.md", op="modify")
    clock(NOW + timedelta(hours=1))
    p = changes.record(actor="plugin:familiar", rel_path="Familiar/100%_done.md", op="create")
    clock(NOW + timedelta(hours=2))
    m = changes.record(
        actor="mcp", rel_path="inbox/j.md", dest_path="20-contexts/work/j.md", op="move",
    )
    assert changes.get(m).current_path == "20-contexts/work/j.md"
    assert [c.id for c in changes.list_changes()] == [m, p, a]
    assert [c.id for c in changes.list_changes(limit=1)] == [m]
    assert [c.id for c in changes.list_changes(actor="plugin")] == [p]
    assert [c.id for c in changes.list_changes(actor="plugin:familiar")] == [p]
    assert [c.id for c in changes.list_changes(actor="assistant")] == [a]
    assert [c.id for c in changes.list_changes(path_query="100%")] == [p]
    assert changes.list_changes(path_query="100%x") == []
    assert [c.id for c in changes.list_changes(path_query="WORK")] == [m, a]
    assert [c.id for c in changes.list_changes(since=NOW + timedelta(minutes=30))] == [m, p]
    assert [c.id for c in changes.list_changes(status="applied")] == [m, p, a]


def test_status_changes_are_compare_and_set(clock):
    cid = changes.record(actor="assistant", rel_path="a.md", op="modify")
    clock(NOW + timedelta(minutes=5))
    assert changes.set_status(cid, "reverted", expect=("applied",)) is True
    assert changes.set_status(cid, "reverted", expect=("applied",)) is False
    c = changes.get(cid)
    assert c.status == "reverted"
    assert c.resolved_ts == (NOW + timedelta(minutes=5)).isoformat()
    assert changes.set_status(cid, "applied", expect=("reverted",)) is True
    assert changes.get(cid).resolved_ts is None
    with pytest.raises(ValueError):
        changes.set_status(cid, "gone", expect=("applied",))


def test_counts_and_risk_reasons():
    changes.record(actor="assistant", rel_path="a.md", op="modify")
    changes.record(
        actor="assistant", rel_path="b.md", op="modify", status="pending",
        risk_reasons=["touches 90-meta"],
    )
    assert changes.counts() == {"applied": 1, "pending": 1}
    [pending] = changes.list_changes(status="pending")
    assert pending.risk_reasons == ("touches 90-meta",)


def test_last_after_blob_is_the_actors_latest_applied_write_at_that_path():
    changes.record(actor="plugin:familiar", rel_path="F/m.md", op="create", after_blob=B)
    changes.record(
        actor="plugin:familiar", rel_path="F/m.md", op="modify", before_blob=B, after_blob=C,
    )
    changes.record(
        actor="plugin:other", rel_path="F/m.md", op="modify", before_blob=C, after_blob=D,
    )
    assert changes.last_after_blob("F/m.md", "plugin:familiar") == C
    assert changes.last_after_blob("F/m.md", "plugin:other") == D
    assert changes.last_after_blob("F/x.md", "plugin:familiar") is None
    mv = changes.record(
        actor="mcp", rel_path="in/j.md", dest_path="w/j.md", op="move",
        before_blob=B, after_blob=C,
    )
    assert changes.last_after_blob("w/j.md", "mcp") == C
    changes.set_status(mv, "reverted", expect=("applied",))
    assert changes.last_after_blob("w/j.md", "mcp") is None


def test_referenced_blobs_cover_every_blob_column():
    changes.record(actor="assistant", rel_path="a.md", op="modify", before_blob=B, after_blob=C)
    changes.record(
        actor="assistant", rel_path="b.md", op="modify", status="pending",
        before_blob=B, pending_bytes_blob=D,
    )
    assert changes.referenced_blobs() == sorted([B, C, D])


def test_prune_drops_rows_older_than_a_year_but_never_pending(clock):
    clock(NOW - timedelta(days=400))
    old = changes.record(actor="assistant", rel_path="a.md", op="modify")
    held = changes.record(actor="assistant", rel_path="b.md", op="modify", status="pending")
    clock(NOW - timedelta(days=10))
    recent = changes.record(actor="assistant", rel_path="c.md", op="modify")
    assert changes.prune(NOW) == 1
    assert {c.id for c in changes.list_changes()} == {held, recent}
    assert changes.get(old) is None


def test_ids_are_never_reused_after_a_prune(clock):
    clock(NOW - timedelta(days=400))
    first = changes.record(actor="assistant", rel_path="a.md", op="modify")
    changes.prune(NOW)
    clock(NOW)
    assert changes.record(actor="assistant", rel_path="a.md", op="modify") > first


def test_degraded_marker_round_trip(clock):
    assert changes.degraded() is None
    changes.mark_degraded("insert failed")
    assert changes.degraded() == NOW.isoformat()
    changes.clear_degraded()
    assert changes.degraded() is None


def test_an_unusable_state_dir_raises_change_log_error(tmp_path, monkeypatch):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(blocker / "state"))
    with pytest.raises(changes.ChangeLogError):
        changes.list_changes()


def test_registered_as_a_history_ref_source():
    changes.register_with_history()
    changes.record(actor="assistant", rel_path="a.md", op="modify", after_blob=B)
    assert list(store._ref_sources["changes"]()) == [B]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "$B2" && python -m pytest tests/test_changes_log.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.changes'`

- [ ] **Step 3: Write the store**

Create `ghostbrain/changes/log.py`:

```python
"""Change log (spec B §4, slice B2): one SQLite row per non-user vault change.

Rows hold attribution and A3 blob ids only. The bytes live in the page-history
store (``ghostbrain.history``). SQLite rather than JSONL because revert /
approve are in-place status edits. Each call opens its own short connection,
so no handle is shared between threads; WAL keeps readers and the writer apart.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

import ghostbrain.paths as _paths
from ghostbrain import history as _history

log = logging.getLogger("ghostbrain.changes")

DB_NAME = "changes.db"
DEGRADED_NAME = "changes.degraded"
RETENTION = timedelta(days=365)
OPS = ("create", "modify", "delete", "move")
STATUSES = ("applied", "pending", "reverted", "rejected", "conflicted")
_NEW_STATUSES = ("applied", "pending")
_RESOLVED = ("reverted", "rejected", "conflicted")

_SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    rel_path TEXT NOT NULL,
    dest_path TEXT,
    op TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    before_blob TEXT,
    after_blob TEXT,
    pending_bytes_blob TEXT,
    status TEXT NOT NULL,
    risk_reasons TEXT NOT NULL DEFAULT '[]',
    resolved_ts TEXT
);
CREATE INDEX IF NOT EXISTS changes_ts ON changes(ts);
CREATE INDEX IF NOT EXISTS changes_status ON changes(status);
CREATE INDEX IF NOT EXISTS changes_rel_path ON changes(rel_path);
"""


class ChangeLogError(Exception):
    """The change log could not be read or written."""


@dataclass(frozen=True)
class Change:
    id: int
    ts: str
    actor: str
    rel_path: str
    dest_path: str | None
    op: str
    reason: str
    before_blob: str | None
    after_blob: str | None
    pending_bytes_blob: str | None
    status: str
    risk_reasons: tuple[str, ...]
    resolved_ts: str | None

    @property
    def current_path(self) -> str:
        """Where the after-version lives (the destination of a move)."""
        return self.dest_path or self.rel_path

    def to_api(self) -> dict[str, Any]:
        return {
            "id": self.id, "ts": self.ts, "actor": self.actor, "path": self.rel_path,
            "destPath": self.dest_path, "op": self.op, "reason": self.reason,
            "status": self.status, "riskReasons": list(self.risk_reasons),
            "resolvedTs": self.resolved_ts,
        }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(when: datetime) -> str:
    return when.astimezone(timezone.utc).isoformat()


def db_path() -> Path:
    return _paths.state_dir() / DB_NAME


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    try:
        path = db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), timeout=5.0)
    except (OSError, sqlite3.Error) as e:
        raise ChangeLogError(f"change log unavailable: {e}") from e
    try:
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)
        with conn:  # commit on success, roll back on error
            yield conn
    except sqlite3.Error as e:
        raise ChangeLogError(f"change log unavailable: {e}") from e
    finally:
        conn.close()


def _row(r: sqlite3.Row) -> Change:
    try:
        reasons = tuple(str(x) for x in json.loads(r["risk_reasons"] or "[]"))
    except (ValueError, TypeError):
        reasons = ()
    return Change(
        id=int(r["id"]), ts=r["ts"], actor=r["actor"], rel_path=r["rel_path"],
        dest_path=r["dest_path"], op=r["op"], reason=r["reason"],
        before_blob=r["before_blob"], after_blob=r["after_blob"],
        pending_bytes_blob=r["pending_bytes_blob"], status=r["status"],
        risk_reasons=reasons, resolved_ts=r["resolved_ts"],
    )


def record(
    *,
    actor: str,
    rel_path: str,
    op: str,
    reason: str = "",
    before_blob: str | None = None,
    after_blob: str | None = None,
    dest_path: str | None = None,
    status: str = "applied",
    pending_bytes_blob: str | None = None,
    risk_reasons: Iterable[str] = (),
) -> int:
    if op not in OPS:
        raise ValueError(f"unknown op: {op!r}")
    if status not in _NEW_STATUSES:
        raise ValueError("a new change is applied or pending")
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO changes (ts, actor, rel_path, dest_path, op, reason, before_blob,"
            " after_blob, pending_bytes_blob, status, risk_reasons)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                _iso(_now()), actor, rel_path, dest_path, op, reason, before_blob,
                after_blob, pending_bytes_blob, status, json.dumps(list(risk_reasons)),
            ),
        )
        return int(cur.lastrowid)


def get(change_id: int) -> Change | None:
    with _connect() as conn:
        r = conn.execute("SELECT * FROM changes WHERE id = ?", (change_id,)).fetchone()
    return _row(r) if r is not None else None


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def list_changes(
    *,
    status: str | None = None,
    actor: str | None = None,
    since: datetime | None = None,
    path_query: str | None = None,
    limit: int = 100,
) -> list[Change]:
    where: list[str] = []
    args: list[Any] = []
    if status is not None:
        where.append("status = ?")
        args.append(status)
    if actor is not None:
        if actor in ("plugin", "worker"):
            where.append("actor LIKE ?")
            args.append(f"{actor}:%")
        else:
            where.append("actor = ?")
            args.append(actor)
    if since is not None:
        where.append("ts >= ?")
        args.append(_iso(since))
    if path_query:
        where.append("(rel_path LIKE ? ESCAPE '\\' OR dest_path LIKE ? ESCAPE '\\')")
        args += [_like(path_query), _like(path_query)]
    sql = "SELECT * FROM changes"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    with _connect() as conn:
        return [_row(r) for r in conn.execute(sql, args).fetchall()]


def set_status(change_id: int, status: str, *, expect: Iterable[str]) -> bool:
    if status not in STATUSES:
        raise ValueError(f"unknown status: {status!r}")
    expected = tuple(expect)
    if not expected:
        raise ValueError("expect at least one current status")
    resolved = _iso(_now()) if status in _RESOLVED else None
    marks = ", ".join("?" for _ in expected)
    with _connect() as conn:
        cur = conn.execute(
            f"UPDATE changes SET status = ?, resolved_ts = ? WHERE id = ? AND status IN ({marks})",
            (status, resolved, change_id, *expected),
        )
        return cur.rowcount == 1


def counts() -> dict[str, int]:
    with _connect() as conn:
        rows = conn.execute("SELECT status, COUNT(*) AS n FROM changes GROUP BY status").fetchall()
    return {r["status"]: int(r["n"]) for r in rows}


def last_after_blob(path: str, actor: str) -> str | None:
    with _connect() as conn:
        r = conn.execute(
            "SELECT after_blob FROM changes WHERE actor = ? AND status = 'applied'"
            " AND COALESCE(dest_path, rel_path) = ? ORDER BY id DESC LIMIT 1",
            (actor, path),
        ).fetchone()
    return r["after_blob"] if r is not None else None


def referenced_blobs() -> list[str]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT before_blob, after_blob, pending_bytes_blob FROM changes"
        ).fetchall()
    return sorted({b for r in rows for b in r if b})


def prune(now: datetime | None = None, *, keep: timedelta = RETENTION) -> int:
    cutoff = _iso((now or _now()) - keep)
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM changes WHERE ts < ? AND status != 'pending'", (cutoff,)
        )
        return int(cur.rowcount)


# ── degraded marker: a change-log insert failed after a write went through ──

def _degraded_path() -> Path:
    return _paths.state_dir() / DEGRADED_NAME


def mark_degraded(reason: str) -> None:
    try:
        p = _degraded_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"ts": _iso(_now()), "reason": reason}), encoding="utf-8")
    except OSError:
        log.exception("could not record the change-log failure marker")


def degraded() -> str | None:
    try:
        data = json.loads(_degraded_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return _iso(_now())  # unreadable marker: still degraded
    return str(data.get("ts")) if isinstance(data, dict) else _iso(_now())


def clear_degraded() -> None:
    try:
        _degraded_path().unlink(missing_ok=True)
    except OSError:
        log.exception("could not clear the change-log failure marker")


def register_with_history() -> None:
    """A3 blob GC keeps every blob a change row names. The lambda looks the
    function up on each call, so a failing change log skips GC entirely."""
    _history.register_ref_source("changes", lambda: referenced_blobs())


register_with_history()
```

Create `ghostbrain/changes/__init__.py`:

```python
"""Change log (spec B §4, slice B2).

Import ``ghostbrain.changes.revert`` explicitly. It imports ``vault_write``,
which imports this package, so re-exporting it here would be an import cycle.
"""
from ghostbrain.changes.log import (
    DB_NAME,
    OPS,
    RETENTION,
    STATUSES,
    Change,
    ChangeLogError,
    clear_degraded,
    counts,
    db_path,
    degraded,
    get,
    last_after_blob,
    list_changes,
    mark_degraded,
    prune,
    record,
    referenced_blobs,
    register_with_history,
    set_status,
)

__all__ = [
    "DB_NAME", "OPS", "RETENTION", "STATUSES", "Change", "ChangeLogError",
    "clear_degraded", "counts", "db_path", "degraded", "get", "last_after_blob",
    "list_changes", "mark_degraded", "prune", "record", "referenced_blobs",
    "register_with_history", "set_status",
]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd "$B2" && python -m pytest tests/test_changes_log.py -q`
Expected: PASS (14 passed)

- [ ] **Step 5: Add the file to CI**

In `.github/workflows/ci.yml`, in the `python -m pytest \` list, add this directly after the line `tests/test_vault_write_history.py \` (added by A3):

```yaml
            tests/test_changes_log.py \
```

- [ ] **Step 6: Commit**

```bash
cd "$B2" && git add ghostbrain/changes tests/test_changes_log.py .github/workflows/ci.yml && git commit -m "feat(changes): SQLite change log in the state dir, registered as a history ref source (B2)"
```

---

### Task 2: The write path records changes; `base_etag` required; B3 hold hook

**Files:**
- Modify: `ghostbrain/vault_write/errors.py` (add `EtagRequired`)
- Modify: `ghostbrain/vault_write/writer.py` (module docstring, imports, `_content_bytes`, `_check_args`, `write`, `_write`; new helpers)
- Modify: `ghostbrain/vault_write/__init__.py`
- Modify: `ghostbrain/api/vault_http.py` (428 handler)
- Modify: `ghostbrain/api/repo/notes_manual.py` (`update_jot_body` gains `reason`; `extract_photo_into_jot` sends its etag)
- Modify: `tests/test_vault_write_history.py` (A3) and `ghostbrain/api/tests/test_routes_notes_history.py` (A3): assistant and plugin edits now send their etag
- Modify: `ghostbrain/api/tests/test_routes_notes_upsert.py` (`test_upsert_replaces_existing` sends `If-Match`)
- Modify: `ghostbrain/api/tests/test_extract_photo.py` (append)
- Test: `tests/test_vault_write_changes.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: Task 1 (`changes.log.record`, `last_after_blob`, `mark_degraded`, `ChangeLogError`); A3 (`_history_store.put_blob`, `_history_store.blob_id`, `writer._snapshot`, `writer._move_history`, `HistoryUnavailable`, `RESTORE`, `WriteResult.history_ok`).
- Produces (all importable from `ghostbrain.vault_write`):
  - `write(..., verbatim: bool = False)`: with `verbatim=True`, `content=` is written byte-for-byte (no trailing newline is added to `.md`). `op="move"` now also accepts `content=` (replacement bytes at the destination).
  - `WriteResult.change_id`: `str(row id)` for a recorded or pending change, else `None`. `WriteResult.status == "pending"` only when the hold policy held the change.
  - `class EtagRequired(VaultWriteError)` with `.current_etag`. HTTP **428** `{"detail": ETAG_REQUIRED_MESSAGE, "currentEtag": …}`.
  - `records_change(actor: Actor, op: Op) -> bool` and `needs_base_etag(actor: Actor) -> bool`.
  - **B3 hook:** `@dataclass(frozen=True) ProposedChange(actor: Actor, op: Op, rel_path: str, dest_path: str | None, before: bytes | None, after: bytes | None, reason: str)`, `HoldPolicy = Callable[[ProposedChange], list[str]]`, and `set_hold_policy(policy: HoldPolicy | None) -> None`. For every recorded write, `_write` calls the policy under the file lock, before any snapshot. A non-empty list means hold: the before and proposed bytes go to the blob store, a `pending` row is recorded with `risk_reasons`, `WriteResult("pending", change_id, current etag, rel_path, None)` is returned, and **nothing is written**. A raising policy holds with `["risk check failed"]`. B3 calls `set_hold_policy(risk.evaluate)` at import and adds approve/reject on top of the pending rows.
  - `notes_manual.update_jot_body(jot_id, new_body, *, actor=USER, base_etag=None, reason="edited jot")`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_vault_write_changes.py`:

```python
"""B2: the vault write path records non-user changes in the change log."""
from __future__ import annotations

from pathlib import Path

import pytest

from ghostbrain import vault_write
from ghostbrain.changes import log as changes
from ghostbrain.history import store
from ghostbrain.vault_write import (
    ASSISTANT,
    MCP,
    RESTORE,
    USER,
    EtagRequired,
    HistoryUnavailable,
    ProposedChange,
    compute_etag,
    plugin_actor,
    set_hold_policy,
    worker_actor,
    write,
    write_new,
)

REL = "20-contexts/work/plan.md"
V1 = b"---\ntitle: Plan\n---\n\nfirst draft\n"
FAMILIAR = plugin_actor("familiar")


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"  # the root conftest points VAULT_PATH here
    note = root / REL
    note.parent.mkdir(parents=True)
    note.write_bytes(V1)
    return root


@pytest.fixture(autouse=True)
def _default_policy():
    yield
    set_hold_policy(None)


def _row(res) -> changes.Change:
    assert res.change_id is not None
    row = changes.get(int(res.change_id))
    assert row is not None
    return row


def test_assistant_edit_records_before_and_after(vault):
    res = write(REL, body="polished draft", actor=ASSISTANT, base_etag=compute_etag(V1),
                reason="polished intro")
    row = _row(res)
    on_disk = (vault / REL).read_bytes()
    assert (row.actor, row.op, row.rel_path, row.dest_path, row.status) == (
        "assistant", "modify", REL, None, "applied")
    assert row.reason == "polished intro"
    assert store.get_blob(row.before_blob) == V1
    assert store.get_blob(row.after_blob) == on_disk
    assert res.etag == compute_etag(on_disk)


def test_user_and_restore_writes_get_no_row(vault):
    assert write(REL, body="mine", actor=USER).change_id is None
    assert write(REL, content=V1.decode(), actor=RESTORE).change_id is None
    assert changes.list_changes() == []


def test_assistant_created_note_is_applied_now_and_recorded(vault):
    res = write_new("20-contexts/work/new.md", "# New\n", actor=ASSISTANT, reason="drafted")
    assert res.status == "applied"
    assert (vault / "20-contexts/work/new.md").read_bytes() == b"# New\n"
    row = _row(res)
    assert (row.op, row.before_blob) == ("create", None)
    assert store.get_blob(row.after_blob) == b"# New\n"


def test_worker_creation_is_ingest_but_worker_edits_are_recorded(vault):
    ingest = write("20-contexts/work/gmail/t.md", content="mail\n", op="create",
                   actor=worker_actor("gmail"))
    assert ingest.change_id is None
    edit = write(REL, fields={"routingStatus": "routed"}, actor=worker_actor("jot-router"))
    assert _row(edit).actor == "worker:jot-router"


def test_move_and_delete_rows(vault):
    dest = "20-contexts/work/projects/plan.md"
    moved = write(REL, op="move", dest=dest, fields={"context": "work"}, actor=FAMILIAR,
                  base_etag=compute_etag(V1))
    row = _row(moved)
    assert (row.op, row.rel_path, row.dest_path) == ("move", REL, dest)
    assert store.get_blob(row.before_blob) == V1
    assert store.get_blob(row.after_blob) == (vault / dest).read_bytes()
    gone = write(dest, op="delete", actor=ASSISTANT, base_etag=vault_write.current_etag(dest))
    drow = _row(gone)
    assert (drow.op, drow.after_blob) == ("delete", None)
    assert store.get_blob(drow.before_blob) == store.get_blob(row.after_blob)


def test_identical_write_records_nothing(vault):
    res = write(REL, content=V1.decode(), actor=ASSISTANT, base_etag=compute_etag(V1))
    assert res.change_id is None
    assert changes.list_changes() == []


def test_non_user_edit_without_an_etag_is_refused(vault):
    with pytest.raises(EtagRequired) as exc:
        write(REL, content="plugin text\n", actor=FAMILIAR)
    assert exc.value.current_etag == compute_etag(V1)
    assert (vault / REL).read_bytes() == V1


def test_a_plugin_may_rewrite_its_own_untouched_note_without_an_etag(vault):
    rel = "Familiar/memory.md"
    write(rel, content="v1\n", op="create", actor=FAMILIAR)
    write(rel, content="v2\n", actor=FAMILIAR)  # implicit base: its own last write
    assert (vault / rel).read_bytes() == b"v2\n"
    (vault / rel).write_bytes(b"user edit\n")
    with pytest.raises(EtagRequired):
        write(rel, content="v3\n", actor=FAMILIAR)
    assert (vault / rel).read_bytes() == b"user edit\n"


def test_another_actors_last_write_is_not_an_implicit_base(vault):
    rel = "Familiar/memory.md"
    write(rel, content="v1\n", op="create", actor=FAMILIAR)
    with pytest.raises(EtagRequired):
        write(rel, content="hijack\n", actor=plugin_actor("other"))


def test_a_broken_change_log_fails_closed_for_implicit_bases(vault, monkeypatch):
    rel = "Familiar/memory.md"
    write(rel, content="v1\n", op="create", actor=FAMILIAR)

    def boom(*_a, **_k):
        raise changes.ChangeLogError("database is locked")

    monkeypatch.setattr(changes, "last_after_blob", boom)
    with pytest.raises(EtagRequired):
        write(rel, content="v2\n", actor=FAMILIAR)


def test_change_log_failure_after_the_write_keeps_the_write(vault, monkeypatch):
    def boom(**_k):
        raise changes.ChangeLogError("disk full")

    monkeypatch.setattr(changes, "record", boom)
    res = write(REL, body="ai edit", actor=ASSISTANT, base_etag=compute_etag(V1))
    assert res.status == "applied" and res.change_id is None
    assert b"ai edit" in (vault / REL).read_bytes()
    assert changes.degraded() is not None


def test_blob_store_failure_refuses_a_non_user_create(vault, monkeypatch):
    def boom(_data):
        raise OSError("disk full")

    monkeypatch.setattr(store, "put_blob", boom)
    with pytest.raises(HistoryUnavailable):
        write("20-contexts/work/new.md", content="x\n", op="create", actor=MCP)
    assert not (vault / "20-contexts/work/new.md").exists()


def test_hold_policy_hook_records_pending_and_writes_nothing(vault):
    seen: list[ProposedChange] = []

    def hold(p: ProposedChange) -> list[str]:
        seen.append(p)
        return ["touches config"]

    set_hold_policy(hold)
    res = write(REL, body="risky", actor=ASSISTANT, base_etag=compute_etag(V1), reason="r")
    assert res.status == "pending" and res.etag == compute_etag(V1)
    assert (vault / REL).read_bytes() == V1
    row = _row(res)
    assert (row.status, row.risk_reasons, row.after_blob) == ("pending", ("touches config",), None)
    assert store.get_blob(row.before_blob) == V1
    assert b"risky" in store.get_blob(row.pending_bytes_blob)
    [p] = seen
    assert (p.actor, p.op, p.rel_path, p.dest_path, p.before) == (
        "assistant", "modify", REL, None, V1)
    assert store.list_snapshots(REL) == []


def test_user_writes_never_reach_the_hold_policy(vault):
    set_hold_policy(lambda _p: ["always"])
    assert write(REL, body="mine", actor=USER).status == "applied"


def test_a_failing_hold_policy_holds_the_change(vault):
    def broken(_p):
        raise RuntimeError("bug in a rule")

    set_hold_policy(broken)
    res = write(REL, body="x", actor=ASSISTANT, base_etag=compute_etag(V1))
    assert res.status == "pending"
    assert _row(res).risk_reasons == ("risk check failed",)


def test_verbatim_content_keeps_the_bytes_exact(vault):
    write(REL, content="no trailing newline", actor=USER, verbatim=True)
    assert (vault / REL).read_bytes() == b"no trailing newline"


def test_move_can_carry_replacement_content(vault):
    dest = "20-contexts/work/archive/plan.md"
    res = write(REL, op="move", dest=dest, content="replaced\n", actor=USER)
    assert res.path == dest
    assert not (vault / REL).exists()
    assert (vault / dest).read_bytes() == b"replaced\n"


def test_package_exports_the_b2_surface():
    for name in ("EtagRequired", "ProposedChange", "HoldPolicy", "set_hold_policy",
                 "records_change", "needs_base_etag"):
        assert hasattr(vault_write, name)
    assert vault_write.records_change("assistant", "modify") is True
    assert vault_write.records_change("restore", "modify") is False
    assert vault_write.records_change("user", "create") is False
    assert vault_write.records_change("worker:gmail", "create") is False
    assert vault_write.records_change("worker:jot-router", "move") is True
    assert vault_write.needs_base_etag("plugin:x") is True
    assert vault_write.needs_base_etag("worker:x") is False
    assert vault_write.needs_base_etag("user") is False
```

Append to `ghostbrain/api/tests/test_extract_photo.py`:

```python
def test_extract_is_an_assistant_change(tmp_vault):
    from ghostbrain.changes import log as changes

    rec = notes_manual.write_inbox_jot("whiteboard shot\n\n")

    class R:
        text = "Queue feeds the handler."

    with patch.object(notes_manual, "llm_run", return_value=R()):
        out = notes_manual.extract_photo_into_jot(rec["id"], "90-meta/assets/jots/2026/06/y.jpg")

    assert out["extracted"] is True
    [row] = changes.list_changes()
    assert (row.actor, row.op, row.reason) == ("assistant", "modify", "added text from a photo")


def test_extract_never_overwrites_an_edit_made_while_reading_the_photo(tmp_vault):
    rec = notes_manual.write_inbox_jot("whiteboard shot\n\n")

    class R:
        text = "Queue feeds the handler."

    def slow_vision(*_a, **_k):
        notes_manual.update_jot_body(rec["id"], "typed while it ran")
        return R()

    with patch.object(notes_manual, "llm_run", side_effect=slow_vision):
        out = notes_manual.extract_photo_into_jot(rec["id"], "90-meta/assets/jots/2026/06/z.jpg")

    assert out["extracted"] is False
    assert "changed" in out["reason"]
    assert out["body"] == "typed while it ran"
    assert notes_manual.read_jot(rec["id"])["body"] == "typed while it ran"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "$B2" && python -m pytest tests/test_vault_write_changes.py ghostbrain/api/tests/test_extract_photo.py -q`
Expected: FAIL with `ImportError: cannot import name 'EtagRequired' from 'ghostbrain.vault_write'`

- [ ] **Step 3: Add `EtagRequired`**

Append to `ghostbrain/vault_write/errors.py`:

```python
ETAG_REQUIRED_MESSAGE = "read the note first and send its etag (If-Match) to change it"


class EtagRequired(VaultWriteError):
    """A non-user writer changed an existing file without ``base_etag`` and
    the file is not exactly what that writer last wrote there (spec B §1:
    required for actor != worker when op != create). HTTP 428."""

    def __init__(self, current_etag: str | None) -> None:
        super().__init__(ETAG_REQUIRED_MESSAGE)
        self.current_etag = current_etag
```

- [ ] **Step 4: Record changes in the write path**

In `ghostbrain/vault_write/writer.py`:

Replace the module docstring with:

```python
"""The single vault write path: lock → etag check → minimal-diff bytes →
hold check → history snapshot → atomic replace → change row (spec B §1;
snapshot from spec A3, change log from slice B2).

Every write by an actor other than ``user`` / ``restore`` gets a row in the
change log (``ghostbrain.changes``), except a ``worker:*`` create, which is
connector ingest and stays audit-only (user decision 2026-10-09). The B3 risk
policy plugs in through ``set_hold_policy``; B2's default never holds.
"""
```

Add `Callable` to the `typing` import (`from typing import Any, Callable, Iterator, Literal, Mapping`). Directly below `from ghostbrain.history.store import HistoryUnavailable, Snapshot`, add:

```python
from ghostbrain.changes import log as _changes
```

Replace the actor import line with:

```python
from ghostbrain.vault_write.actor import RESTORE, USER, Actor, parse_actor
```

Replace the errors import line with:

```python
from ghostbrain.vault_write.errors import (
    EtagRequired,
    FileMissing,
    InvalidPath,
    MalformedNote,
    WriteConflict,
)
```

Replace `_content_bytes` with:

```python
def _content_bytes(path: Path, content: str, *, verbatim: bool = False) -> bytes:
    if not verbatim and path.suffix.lower() == ".md" and not content.endswith("\n"):
        content += "\n"
    return content.encode("utf-8")
```

In `_check_args`, delete these two lines (a move may now carry replacement content, which revert needs):

```python
    if op == "move" and content is not None:
        raise ValueError("op='move' takes body/fields, not content")
```

Replace `write` (the public wrapper) with:

```python
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
) -> WriteResult:
    result = _write(
        rel_path, actor=actor, content=content, body=body, fields=fields,
        op=op, dest=dest, reason=reason, base_etag=base_etag, verbatim=verbatim,
    )
    _reindex(result.path, *([rel_path] if dest is not None else []))
    return result
```

Add this block directly above `def _snapshot(` (A3's helper):

```python
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


HoldPolicy = Callable[[ProposedChange], list[str]]


def _never_hold(_change: ProposedChange) -> list[str]:
    return []


_hold_policy: HoldPolicy = _never_hold


def set_hold_policy(policy: HoldPolicy | None) -> None:
    """B3 installs its risk rules here. ``None`` restores B2's default: never
    hold (user decision 2026-10-09: new notes apply now, revert in one click)."""
    global _hold_policy
    _hold_policy = policy or _never_hold


def records_change(actor: Actor, op: Op) -> bool:
    """Spec B §1 step 7: user (and restore) writes get no row. A worker
    *creating* a note is connector ingest: audit log only (decision 1)."""
    if actor in (USER, RESTORE):
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
```

Replace the whole `_write` function (A3's version) with:

```python
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
                data, updated = _edit_bytes(current, body=body, fields=fields, suffix=src.suffix)
            else:
                data = current  # plain move
        if dst is not None:
            existing = _read_bytes(dst)
            if existing is not None:
                raise WriteConflict(compute_etag(existing))
        if op == "modify" and data == current:
            return WriteResult("applied", None, etag_now, src_rel, updated)
        proposed = ProposedChange(actor, op, src_rel, dst_rel, current, data, reason)
        recorded = records_change(actor, op)
        if recorded:
            reasons = _hold_reasons(proposed)
            if reasons:
                return _hold(proposed, reasons)  # B3: nothing is written
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
        change_id = (
            _record(proposed, before_blob=before_blob, after_blob=after_blob) if recorded else None
        )
        etag = compute_etag(data) if data is not None else None
        return WriteResult("applied", change_id, etag, dst_rel or src_rel, updated, history_ok)
```

In `ghostbrain/vault_write/__init__.py`, add `EtagRequired` to the `ghostbrain.vault_write.errors` import list. Add `HoldPolicy`, `ProposedChange`, `needs_base_etag`, `records_change` and `set_hold_policy` to the `ghostbrain.vault_write.writer` import list. Replace `__all__` with:

```python
__all__ = [
    "ASSISTANT", "DELETE_FIELD", "MCP", "RESTORE", "USER", "WRITABLE_SUFFIXES",
    "Actor", "EtagRequired", "FileMissing", "HistoryUnavailable", "HoldPolicy",
    "InvalidPath", "MalformedNote", "NoteSnapshot", "Op", "ParsedNote", "ProposedChange",
    "VaultWriteError", "WriteConflict", "WriteResult",
    "apply_fields", "compute_etag", "current_etag", "find_key_block", "lines_of",
    "load_metadata", "needs_base_etag", "normalize_if_match", "parse_actor", "parse_note",
    "plugin_actor", "read", "records_change", "resolve_safe", "set_hold_policy",
    "splice_body", "worker_actor", "write", "write_new",
]
```

- [ ] **Step 5: Map `EtagRequired` to HTTP 428**

In `ghostbrain/api/vault_http.py`, add `EtagRequired` to the `from ghostbrain.vault_write import (...)` list. Inside `install_vault_write_errors`, add after `_conflict`:

```python
    async def _etag_required(_req: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, EtagRequired)
        return JSONResponse(
            status_code=428,
            content={"detail": str(exc), "currentEtag": exc.current_etag},
        )
```

and after the last `app.add_exception_handler(...)` line:

```python
    app.add_exception_handler(EtagRequired, _etag_required)
```

- [ ] **Step 6: Make every in-repo non-user editor send its etag**

In `ghostbrain/api/repo/notes_manual.py`, replace `update_jot_body`'s signature and its `reason="edited jot",` argument with:

```python
def update_jot_body(
    jot_id: str,
    new_body: str,
    *,
    actor: Actor = USER,
    base_etag: str | None = None,
    reason: str = "edited jot",
) -> dict:
```

```python
        reason=reason,
```

In `extract_photo_into_jot`, replace the line `saved = update_jot_body(jot_id, new_body, actor=ASSISTANT)` with:

```python
    try:
        # The vision call can take a while; the jot's etag from before it
        # guarantees an edit typed meanwhile is never overwritten (spec B §1).
        saved = update_jot_body(
            jot_id, new_body, actor=ASSISTANT, base_etag=record["etag"],
            reason="added text from a photo",
        )
    except vault_write.WriteConflict:
        fresh = read_jot(jot_id)
        return {
            "id": jot_id,
            "path": fresh["path"],
            "body": fresh["body"],
            "extracted": False,
            "reason": "the note changed while reading the photo — try again",
        }
```

- [ ] **Step 7: Update the existing tests that edited without an etag**

In `tests/test_vault_write_history.py` (A3), in `test_assistant_writes_snapshot_every_time`, replace `write(REL, body=f"ai {i}", actor=ASSISTANT)` with:

```python
        write(REL, body=f"ai {i}", actor=ASSISTANT, base_etag=vault_write.current_etag(REL))
```

and in `test_non_user_write_is_refused_when_history_fails`, replace `write(REL, body="ai edit", actor=ASSISTANT)` with:

```python
        write(REL, body="ai edit", actor=ASSISTANT, base_etag=compute_etag(V1))
```

In `ghostbrain/api/tests/test_routes_notes_history.py` (A3), in `test_plugin_write_is_refused_when_history_fails`, replace the `client.put(...)` call with:

```python
    r = client.put("/v1/notes", json={"path": REL, "content": "plugin text"},
                   headers={**auth_headers, "If-Match": f'"{compute_etag(V1.encode())}"'})
```

In `ghostbrain/api/tests/test_routes_notes_upsert.py`, add `from ghostbrain.vault_write import compute_etag` below the module docstring. In `test_upsert_replaces_existing`, replace the `client.put(...)` line with the lines below. The etag is computed outside the f-string because CI runs Python 3.11, which forbids a backslash inside an f-string expression.

```python
    old_etag = compute_etag(b"old\n")
    r = client.put(
        "/v1/notes", json={"path": "Familiar/memory.md", "content": "new body\n"},
        headers={**auth_headers, "If-Match": f'"{old_etag}"'},
    )
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `cd "$B2" && python -m pytest tests/test_vault_write_changes.py tests/test_vault_write_history.py tests/test_vault_write_writer.py tests/test_vault_write_text.py tests/test_changes_log.py ghostbrain/api/tests -q`
Expected: PASS

- [ ] **Step 9: Add the test file to CI**

In `.github/workflows/ci.yml`, add after `tests/test_changes_log.py \`:

```yaml
            tests/test_vault_write_changes.py \
```

- [ ] **Step 10: Commit**

```bash
cd "$B2" && git add ghostbrain/vault_write ghostbrain/api/vault_http.py ghostbrain/api/repo/notes_manual.py tests/test_vault_write_changes.py tests/test_vault_write_history.py ghostbrain/api/tests .github/workflows/ci.yml && git commit -m "feat(vault-write): record non-user changes, require base_etag for AI writers, B3 hold hook (B2)"
```

---

### Task 3: Revert and undo

**Files:**
- Create: `ghostbrain/changes/revert.py`
- Test: `tests/test_changes_revert.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: Task 1 (`log.get`, `log.set_status`, `log.mark_degraded`, `Change.current_path`); Task 2 (`vault_write.write(..., verbatim=True)`, move with `content`); A3 (`history.get_blob`, `history.blob_id`, `history.BlobNotFound`, `vault_write.RESTORE`).
- Produces (`ghostbrain.changes.revert`):
  - `CHANGED_SINCE_MESSAGE: str`.
  - Exceptions: `RevertError(Exception)`, then `ChangeNotFound`, `NotRevertable`, `VersionGone`, and `ChangedSince(path: str, expected: bytes | None, current: bytes | None)`, which exposes `.path`, `.expected` and `.current`.
  - `@dataclass(frozen=True) Flip(at: str, expect: str | None, to: str, target: str | None)`: "the file at `at` should hold blob `expect`; put `target` at `to`". `None` means "absent".
  - `revert_flip(c: Change) -> Flip`, `undo_flip(c: Change) -> Flip`, `expected_state(c: Change) -> Flip | None` (`applied` → revert, `reverted` → undo, otherwise `None`).
  - `read_current(rel: str) -> bytes | None`, `matches_blob(data: bytes | None, blob: str | None) -> bool`, `drift(c: Change) -> tuple[Flip, bytes | None] | None`, `changed_since(c: Change) -> bool`.
  - `@dataclass(frozen=True) RevertResult(change: Change, path: str, etag: str | None)`.
  - `revert(change_id: int, *, force: bool = False) -> RevertResult` (`applied` → `reverted`) and `undo_revert(change_id: int, *, force: bool = False) -> RevertResult` (`reverted` → `applied`). Both write as `restore`. They raise `ChangeNotFound`, `NotRevertable`, `ChangedSince`, `VersionGone`, `vault_write.WriteConflict` (when a move-back target is occupied), `HistoryUnavailable` or `ChangeLogError`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_changes_revert.py`:

```python
"""B2: revert and undo of change-log rows."""
from __future__ import annotations

from pathlib import Path

import pytest

from ghostbrain import vault_write
from ghostbrain.changes import log as changes
from ghostbrain.changes import revert as rv
from ghostbrain.history import store
from ghostbrain.vault_write import (
    ASSISTANT,
    USER,
    WriteConflict,
    compute_etag,
    plugin_actor,
    write,
    write_new,
)

REL = "20-contexts/work/plan.md"
DEST = "20-contexts/work/projects/plan.md"
V1 = b"---\ntitle: Plan\n---\n\nfirst draft\n"


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    note = root / REL
    note.parent.mkdir(parents=True)
    note.write_bytes(V1)
    return root


def _ai_edit(text: str = "polished draft") -> int:
    res = write(REL, body=text, actor=ASSISTANT, base_etag=vault_write.current_etag(REL),
                reason="polish")
    assert res.change_id is not None
    return int(res.change_id)


def _move() -> int:
    res = write(REL, op="move", dest=DEST, fields={"context": "work"},
                actor=plugin_actor("familiar"), base_etag=compute_etag(V1))
    return int(res.change_id)


def test_revert_restores_the_before_bytes_and_marks_the_row(vault):
    cid = _ai_edit()
    after = (vault / REL).read_bytes()
    res = rv.revert(cid)
    assert (vault / REL).read_bytes() == V1
    assert res.change.status == "reverted" and res.change.resolved_ts is not None
    assert res.path == REL and res.etag == compute_etag(V1)
    newest = store.list_snapshots(REL)[0]
    assert newest.actor == "restore" and store.get_blob(newest.blob) == after
    assert [c.id for c in changes.list_changes()] == [cid]  # a revert adds no row


def test_revert_is_refused_when_the_note_changed_since(vault):
    cid = _ai_edit()
    after = (vault / REL).read_bytes()
    write(REL, body="my later edit", actor=USER)
    mine = (vault / REL).read_bytes()
    assert rv.changed_since(changes.get(cid)) is True
    with pytest.raises(rv.ChangedSince) as exc:
        rv.revert(cid)
    assert (exc.value.path, exc.value.expected, exc.value.current) == (REL, after, mine)
    assert (vault / REL).read_bytes() == mine
    assert changes.get(cid).status == "applied"


def test_forced_revert_keeps_the_overwritten_version_in_history(vault):
    cid = _ai_edit()
    write(REL, body="my later edit", actor=USER)
    mine = (vault / REL).read_bytes()
    rv.revert(cid, force=True)
    assert (vault / REL).read_bytes() == V1
    assert store.get_blob(store.list_snapshots(REL)[0].blob) == mine


def test_undo_reapplies_and_round_trips(vault):
    cid = _ai_edit()
    after = (vault / REL).read_bytes()
    assert rv.changed_since(changes.get(cid)) is False
    rv.revert(cid)
    res = rv.undo_revert(cid)
    assert (vault / REL).read_bytes() == after
    assert res.change.status == "applied" and res.change.resolved_ts is None
    rv.revert(cid)
    assert (vault / REL).read_bytes() == V1


def test_round_trip_is_byte_exact_without_a_trailing_newline_and_with_crlf(vault):
    raw = b"---\r\ntitle: Plan\r\n---\r\n\r\nno newline at the end"
    (vault / REL).write_bytes(raw)
    cid = _ai_edit("ai text")
    after = (vault / REL).read_bytes()
    rv.revert(cid)
    assert (vault / REL).read_bytes() == raw
    rv.undo_revert(cid)
    assert (vault / REL).read_bytes() == after


def test_revert_of_a_created_note_deletes_it_and_undo_brings_it_back(vault):
    res = write_new("20-contexts/work/new.md", "# New\n", actor=ASSISTANT)
    cid = int(res.change_id)
    rv.revert(cid)
    assert not (vault / "20-contexts/work/new.md").exists()
    rv.undo_revert(cid)
    assert (vault / "20-contexts/work/new.md").read_bytes() == b"# New\n"


def test_revert_of_a_delete_recreates_the_note(vault):
    res = write(REL, op="delete", actor=ASSISTANT, base_etag=compute_etag(V1))
    rv.revert(int(res.change_id))
    assert (vault / REL).read_bytes() == V1


def test_revert_of_a_move_moves_it_back(vault):
    cid = _move()
    rv.revert(cid)
    assert (vault / REL).read_bytes() == V1
    assert not (vault / DEST).exists()
    rv.undo_revert(cid)
    assert not (vault / REL).exists() and (vault / DEST).exists()


def test_revert_of_a_move_never_overwrites_a_note_now_at_the_old_path(vault):
    cid = _move()
    (vault / REL).write_bytes(b"someone else\n")
    with pytest.raises(WriteConflict):
        rv.revert(cid)
    assert (vault / REL).read_bytes() == b"someone else\n"
    assert (vault / DEST).exists()
    assert changes.get(cid).status == "applied"


def test_states_that_cannot_be_reverted(vault):
    with pytest.raises(rv.ChangeNotFound):
        rv.revert(999)
    cid = _ai_edit()
    with pytest.raises(rv.NotRevertable):
        rv.undo_revert(cid)
    pid = changes.record(actor="assistant", rel_path=REL, op="modify", status="pending",
                         pending_bytes_blob=store.put_blob(b"x\n"))
    with pytest.raises(rv.NotRevertable):
        rv.revert(pid)
    assert rv.expected_state(changes.get(pid)) is None


def test_a_collected_version_is_reported_gone(vault):
    cid = _ai_edit()
    store._blob_path(changes.get(cid).before_blob).unlink()
    with pytest.raises(rv.VersionGone):
        rv.revert(cid)
    assert changes.get(cid).status == "applied"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "$B2" && python -m pytest tests/test_changes_revert.py -q`
Expected: FAIL with `ImportError: cannot import name 'revert' from 'ghostbrain.changes'`

- [ ] **Step 3: Write the revert engine**

Create `ghostbrain/changes/revert.py`:

```python
"""Revert and undo for change-log rows (spec B §5, §6; slice B2).

A revert puts a row's before-version back; undo puts its after-version back.
Both refuse when the file no longer holds what the row expects
(``ChangedSince``) unless forced. Both write as ``restore``: the version being
replaced is always snapshotted (A3: never coalesced), a history failure
refuses the write, and no change row is added, because a revert is the user's
own write (spec B §5).
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from ghostbrain import history, vault_write
from ghostbrain.changes import log as changes_log
from ghostbrain.changes.log import Change
from ghostbrain.vault_write import RESTORE, WriteResult, compute_etag

log = logging.getLogger("ghostbrain.changes")

CHANGED_SINCE_MESSAGE = (
    "the note changed since this change; resend with force to overwrite it "
    "(the current version stays in page history)"
)


class RevertError(Exception):
    """Base class for revert / undo failures."""


class ChangeNotFound(RevertError):
    pass


class NotRevertable(RevertError):
    pass


class VersionGone(RevertError):
    pass


class ChangedSince(RevertError):
    def __init__(self, path: str, expected: bytes | None, current: bytes | None) -> None:
        super().__init__(CHANGED_SINCE_MESSAGE)
        self.path = path
        self.expected = expected
        self.current = current


@dataclass(frozen=True)
class Flip:
    """The file at ``at`` should hold blob ``expect``; put ``target`` at ``to``.
    ``None`` means the file is (or becomes) absent."""

    at: str
    expect: str | None
    to: str
    target: str | None


@dataclass(frozen=True)
class RevertResult:
    change: Change
    path: str
    etag: str | None


_lock = threading.Lock()


def revert_flip(c: Change) -> Flip:
    return Flip(at=c.current_path, expect=c.after_blob, to=c.rel_path, target=c.before_blob)


def undo_flip(c: Change) -> Flip:
    return Flip(at=c.rel_path, expect=c.before_blob, to=c.current_path, target=c.after_blob)


def expected_state(c: Change) -> Flip | None:
    if c.status == "applied":
        return revert_flip(c)
    if c.status == "reverted":
        return undo_flip(c)
    return None


def read_current(rel: str) -> bytes | None:
    try:
        return vault_write.resolve_safe(rel).read_bytes()
    except FileNotFoundError:
        return None


def matches_blob(data: bytes | None, blob: str | None) -> bool:
    if blob is None:
        return data is None
    return data is not None and history.blob_id(data) == blob


def drift(c: Change) -> tuple[Flip, bytes | None] | None:
    flip = expected_state(c)
    return None if flip is None else (flip, read_current(flip.at))


def changed_since(c: Change) -> bool:
    d = drift(c)
    return d is not None and not matches_blob(d[1], d[0].expect)


def _blob_bytes(blob: str | None) -> bytes | None:
    if blob is None:
        return None
    try:
        return history.get_blob(blob)
    except history.BlobNotFound:
        raise VersionGone("this version is no longer available") from None


def _text(blob: str) -> str:
    data = _blob_bytes(blob)
    assert data is not None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise NotRevertable("this version is not UTF-8 text") from None


def _apply(flip: Flip, *, force: bool, reason: str) -> WriteResult:
    text = _text(flip.target) if flip.target is not None else None  # fail before any write
    current = read_current(flip.at)
    if not matches_blob(current, flip.expect) and not force:
        try:
            expected = _blob_bytes(flip.expect)
        except VersionGone:
            expected = None
        raise ChangedSince(flip.at, expected, current)
    base = compute_etag(current) if current is not None else None
    if text is None:
        if current is None:
            return WriteResult("applied", None, None, flip.at, None)
        return vault_write.write(flip.at, op="delete", actor=RESTORE, reason=reason, base_etag=base)
    if current is None:
        return vault_write.write(
            flip.to, content=text, op="create", actor=RESTORE, reason=reason, verbatim=True,
        )
    if flip.at != flip.to:
        return vault_write.write(
            flip.at, op="move", dest=flip.to, content=text, actor=RESTORE, reason=reason,
            base_etag=base, verbatim=True,
        )
    return vault_write.write(
        flip.at, content=text, actor=RESTORE, reason=reason, base_etag=base, verbatim=True,
    )


def _transition(
    change_id: int, *, from_status: str, to_status: str, flip_of, verb: str, force: bool
) -> RevertResult:
    with _lock:
        c = changes_log.get(change_id)
        if c is None:
            raise ChangeNotFound(f"no change #{change_id}")
        if c.status != from_status:
            raise NotRevertable(f"change #{change_id} is {c.status}")
        res = _apply(flip_of(c), force=force, reason=f"{verb} change #{c.id} by {c.actor}")
        try:
            changes_log.set_status(c.id, to_status, expect=(from_status,))
            c = changes_log.get(c.id) or c
        except changes_log.ChangeLogError:
            log.exception("could not mark change #%s %s", change_id, to_status)
            changes_log.mark_degraded(f"change #{change_id} was {verb} but not marked")
    return RevertResult(c, res.path, res.etag)


def revert(change_id: int, *, force: bool = False) -> RevertResult:
    return _transition(change_id, from_status="applied", to_status="reverted",
                       flip_of=revert_flip, verb="reverted", force=force)


def undo_revert(change_id: int, *, force: bool = False) -> RevertResult:
    return _transition(change_id, from_status="reverted", to_status="applied",
                       flip_of=undo_flip, verb="re-applied", force=force)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd "$B2" && python -m pytest tests/test_changes_revert.py tests/test_vault_write_changes.py -q`
Expected: PASS

- [ ] **Step 5: Add the test file to CI**

In `.github/workflows/ci.yml`, add after `tests/test_vault_write_changes.py \`:

```yaml
            tests/test_changes_revert.py \
```

- [ ] **Step 6: Commit**

```bash
cd "$B2" && git add ghostbrain/changes/revert.py tests/test_changes_revert.py .github/workflows/ci.yml && git commit -m "feat(changes): revert and undo through the write path as restore, refused when changed since (B2)"
```

---

### Task 4: Retention inside the daily history prune

**Files:**
- Create: `ghostbrain/changes/maintenance.py`
- Modify: `ghostbrain/scheduler_jobs.py` (`_history_prune_job`, added by A3)
- Modify: `tests/test_scheduler_history_prune_job.py` (A3)
- Test: `tests/test_changes_maintenance.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: Task 1 (`log.prune`, `log.register_with_history`, `log.referenced_blobs`, `ChangeLogError`); A3 (`history.store.prune(now) -> PruneResult`, `.to_details()`).
- Produces: `ghostbrain.changes.maintenance.run_prune(now: datetime | None = None) -> dict`. It returns A3's details (`notes, kept, dropped, blobsDeleted, gcSkipped`) plus `changesPruned: int | None` (`None` when the change log could not be pruned). The `history-prune` job reports exactly this dict.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_changes_maintenance.py`:

```python
"""B2: change-log retention inside the daily history prune."""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

from ghostbrain.changes import log as changes
from ghostbrain.changes.maintenance import run_prune
from ghostbrain.history import store


def _age(blob: str, days: int = 3) -> None:
    old = time.time() - days * 86400
    os.utime(store._blob_path(blob), (old, old))


def test_rows_older_than_a_year_are_pruned_with_the_history(monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(changes, "_now", lambda: now - timedelta(days=400))
    changes.record(actor="assistant", rel_path="a.md", op="modify")
    monkeypatch.setattr(changes, "_now", lambda: now)
    keep = changes.record(actor="assistant", rel_path="b.md", op="modify")
    details = run_prune(now)
    assert details["changesPruned"] == 1
    assert details["gcSkipped"] is False
    assert [c.id for c in changes.list_changes()] == [keep]


def test_blobs_named_only_by_change_rows_survive_gc():
    blob = store.put_blob(b"assistant version\n")
    _age(blob)
    changes.record(actor="assistant", rel_path="a.md", op="create", after_blob=blob)
    assert run_prune()["gcSkipped"] is False
    assert store.has_blob(blob)
    run_prune(datetime.now(timezone.utc) + timedelta(days=800))  # the row expires
    assert not store.has_blob(blob)


def test_a_broken_change_log_skips_blob_gc(monkeypatch):
    orphan = store.put_blob(b"orphan\n")
    _age(orphan)

    def boom():
        raise changes.ChangeLogError("database is locked")

    monkeypatch.setattr(changes, "referenced_blobs", boom)
    details = run_prune()
    assert details["gcSkipped"] is True
    assert store.has_blob(orphan)


def test_a_failing_change_prune_still_runs_the_history_prune(monkeypatch):
    def boom(*_a, **_k):
        raise changes.ChangeLogError("database is locked")

    monkeypatch.setattr(changes, "prune", boom)
    details = run_prune()
    assert details["changesPruned"] is None
    assert "notes" in details
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "$B2" && python -m pytest tests/test_changes_maintenance.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.changes.maintenance'`

- [ ] **Step 3: Write `run_prune`**

Create `ghostbrain/changes/maintenance.py`:

```python
"""Daily maintenance shared by page history (A3) and the change log (B2).

Change rows older than a year go first. Then A3's retention + blob GC runs,
which keeps every blob a remaining row names (the "changes" ref source) and
skips GC entirely when the change log can't be read."""
from __future__ import annotations

import logging
from datetime import datetime

from ghostbrain.changes import log as changes_log

log = logging.getLogger("ghostbrain.changes")


def run_prune(now: datetime | None = None) -> dict:
    from ghostbrain.history import store

    try:
        pruned: int | None = changes_log.prune(now)
    except changes_log.ChangeLogError:
        log.exception("change-log retention failed; history prune continues")
        pruned = None
    changes_log.register_with_history()
    details = store.prune(now).to_details()
    return {**details, "changesPruned": pruned}
```

- [ ] **Step 4: Run it from the daily job**

In `ghostbrain/scheduler_jobs.py`, replace the body of `_history_prune_job`'s inner `work()` (A3) with:

```python
    def work() -> dict:
        from ghostbrain.changes.maintenance import run_prune

        return run_prune()
```

and update its docstring's first line to `"""Daily page-history + change-log retention and blob GC (specs A3, B §4).`

In `tests/test_scheduler_history_prune_job.py` (A3), in `test_history_prune_job_reports_counts`, replace the `assert result.details == {...}` statement with:

```python
    assert result.details == {"notes": 0, "kept": 0, "dropped": 0, "blobsDeleted": 0,
                              "gcSkipped": False, "changesPruned": 0}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd "$B2" && python -m pytest tests/test_changes_maintenance.py tests/test_scheduler_history_prune_job.py tests/test_history_retention.py -q`
Expected: PASS

- [ ] **Step 6: Add the test file to CI**

In `.github/workflows/ci.yml`, add after `tests/test_changes_revert.py \`:

```yaml
            tests/test_changes_maintenance.py \
```

- [ ] **Step 7: Commit**

```bash
cd "$B2" && git add ghostbrain/changes/maintenance.py ghostbrain/scheduler_jobs.py tests/test_changes_maintenance.py tests/test_scheduler_history_prune_job.py .github/workflows/ci.yml && git commit -m "feat(changes): one-year change-log retention in the daily history prune (B2)"
```

---

### Task 5: Actor attribution from the request header

**Files:**
- Modify: `ghostbrain/api/vault_http.py` (`ACTOR_HEADER`, `request_actor`)
- Modify: `ghostbrain/api/routes/notes.py`
- Modify: `ghostbrain/api/routes/docs.py`
- Modify: `ghostbrain/api/repo/note.py` (`save_note_body(reason=…)`)
- Modify: `ghostbrain/api/repo/notes_manual.py` (`move_jot`/`delete_jot` take `base_etag`, `create_and_route_jot` takes `actor`)
- Modify: `ghostbrain/api/repo/generated_docs.py` (`write_doc(actor=…)`)
- Test: `ghostbrain/api/tests/test_actor_header.py`

**Interfaces:**
- Consumes: Task 2 (`EtagRequired` → 428, implicit base); `vault_write.parse_actor`, `USER`, `ASSISTANT`, `MCP`, `RESTORE`, `plugin_actor`.
- Produces:
  - `ghostbrain.api.vault_http.ACTOR_HEADER = "X-Poltergeist-Actor"`.
  - `request_actor(value: str | None = Header(None, alias=ACTOR_HEADER)) -> Actor`: a FastAPI dependency. Missing or blank means `user`. A malformed value, `worker:*` or `restore` raises `HTTPException(400)`.
  - Header-attributed routes: `PATCH /v1/notes/body`, `PATCH /v1/notes/{jot_id}`, `PUT /v1/notes` (missing header means `plugin:unattributed`), `POST /v1/notes`, `POST /v1/notes/{jot_id}/route` and `DELETE /v1/notes/{jot_id}` (both now honour `If-Match`), and `POST /v1/docs/write` (missing header means `mcp`).
  - Repo signatures: `save_note_body(rel_path, body, *, actor=USER, base_etag=None, reason="edited in the editor")`, `move_jot(..., actor=USER, base_etag=None)`, `delete_jot(jot_id, *, actor=USER, base_etag=None)`, `create_and_route_jot(body, *, captured_at=None, actor=USER)`, `generated_docs.write_doc(title, html, *, actor=MCP)`.

- [ ] **Step 1: Write the failing tests**

Create `ghostbrain/api/tests/test_actor_header.py`:

```python
"""B2: X-Poltergeist-Actor attribution on the write routes (spec B §2)."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from ghostbrain.api.repo.notes_manual import write_inbox_jot
from ghostbrain.api.tests.conftest import write_note
from ghostbrain.api.vault_http import ACTOR_HEADER, request_actor
from ghostbrain.changes import log as changes
from ghostbrain.vault_write import compute_etag

REL = "20-contexts/work/notes/plan.md"
V1 = "---\ntitle: Plan\n---\n\nfirst draft\n"


def _h(auth: dict, actor: str | None = None, etag: str | None = None) -> dict:
    h = dict(auth)
    if actor is not None:
        h[ACTOR_HEADER] = actor
    if etag is not None:
        h["If-Match"] = f'"{etag}"'
    return h


def test_request_actor_parsing():
    assert request_actor(None) == "user"
    assert request_actor("   ") == "user"
    assert request_actor("assistant") == "assistant"
    assert request_actor(" plugin:familiar ") == "plugin:familiar"
    for bad in ("admin", "worker:reversal", "restore", "plugin:../x"):
        with pytest.raises(HTTPException) as exc:
            request_actor(bad)
        assert exc.value.status_code == 400


def test_a_missing_header_is_the_user_and_gets_no_row(tmp_vault, client, auth_headers):
    write_note(tmp_vault, REL, V1)
    r = client.patch("/v1/notes/body", json={"path": REL, "body": "mine"}, headers=auth_headers)
    assert r.status_code == 200
    assert changes.list_changes() == []


def test_assistant_header_records_an_assistant_change(tmp_vault, client, auth_headers):
    write_note(tmp_vault, REL, V1)
    r = client.patch("/v1/notes/body", json={"path": REL, "body": "polished"},
                     headers=_h(auth_headers, "assistant", compute_etag(V1.encode())))
    assert r.status_code == 200
    [row] = changes.list_changes()
    assert (row.actor, row.op, row.rel_path, row.reason) == (
        "assistant", "modify", REL, "accepted an assistant edit")


def test_assistant_edit_without_if_match_is_428(tmp_vault, client, auth_headers):
    note = write_note(tmp_vault, REL, V1)
    r = client.patch("/v1/notes/body", json={"path": REL, "body": "polished"},
                     headers=_h(auth_headers, "assistant"))
    assert r.status_code == 428
    assert r.json()["currentEtag"] == compute_etag(V1.encode())
    assert note.read_text() == V1


def test_reserved_or_malformed_actor_headers_are_400(tmp_vault, client, auth_headers):
    note = write_note(tmp_vault, REL, V1)
    for bad in ("worker:reversal", "restore", "admin"):
        r = client.patch("/v1/notes/body", json={"path": REL, "body": "x"},
                         headers=_h(auth_headers, bad))
        assert r.status_code == 400
    assert note.read_text() == V1


def test_upsert_without_a_header_stays_attributed_to_a_plugin(tmp_vault, client, auth_headers):
    r = client.put("/v1/notes", json={"path": "Familiar/m.md", "content": "v1"},
                   headers=auth_headers)
    assert r.status_code == 200
    [row] = changes.list_changes()
    assert (row.actor, row.op) == ("plugin:unattributed", "create")


def test_plugin_header_attributes_and_allows_rewriting_its_own_note(
    tmp_vault, client, auth_headers
):
    h = _h(auth_headers, "plugin:familiar")
    assert client.put("/v1/notes", json={"path": "Familiar/m.md", "content": "v1"},
                      headers=h).status_code == 200
    assert client.put("/v1/notes", json={"path": "Familiar/m.md", "content": "v2"},
                      headers=h).status_code == 200
    (tmp_vault / "Familiar/m.md").write_text("user edit\n")
    r = client.put("/v1/notes", json={"path": "Familiar/m.md", "content": "v3"}, headers=h)
    assert r.status_code == 428
    assert (tmp_vault / "Familiar/m.md").read_text() == "user edit\n"
    assert [c.actor for c in changes.list_changes()] == ["plugin:familiar", "plugin:familiar"]


def test_generated_docs_are_mcp_changes(tmp_vault, client, auth_headers):
    r = client.post("/v1/docs/write", json={"title": "Plan", "html": "<p>x</p>"},
                    headers=auth_headers)
    assert r.status_code == 200
    [row] = changes.list_changes()
    assert (row.actor, row.op, row.rel_path) == ("mcp", "create", r.json()["path"])


def test_a_plugin_creating_a_jot_is_recorded(tmp_vault, client, auth_headers):
    r = client.post("/v1/notes", json={"body": "from a plugin", "route": False},
                    headers=_h(auth_headers, "plugin:familiar"))
    assert r.status_code == 200
    [row] = changes.list_changes()
    assert (row.actor, row.op, row.rel_path) == ("plugin:familiar", "create", r.json()["path"])


def test_a_plugin_deleting_a_users_jot_needs_its_etag(tmp_vault, client, auth_headers):
    rec = write_inbox_jot("my jot")
    path = tmp_vault / rec["path"]
    h = _h(auth_headers, "plugin:familiar")
    assert client.delete(f"/v1/notes/{rec['id']}", headers=h).status_code == 428
    assert path.exists()
    etag = compute_etag(path.read_bytes())
    r = client.delete(f"/v1/notes/{rec['id']}", headers={**h, "If-Match": f'"{etag}"'})
    assert r.status_code == 204
    [row] = changes.list_changes()
    assert (row.actor, row.op) == ("plugin:familiar", "delete")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "$B2" && python -m pytest ghostbrain/api/tests/test_actor_header.py -q`
Expected: FAIL with `ImportError: cannot import name 'ACTOR_HEADER' from 'ghostbrain.api.vault_http'`

- [ ] **Step 3: Add the header dependency**

In `ghostbrain/api/vault_http.py`, change the FastAPI import to `from fastapi import FastAPI, Header, HTTPException, Request` and add `RESTORE`, `USER`, `Actor` and `parse_actor` to the `from ghostbrain.vault_write import (...)` list. Add below `if_match`:

```python
ACTOR_HEADER = "X-Poltergeist-Actor"


def request_actor(value: str | None = Header(default=None, alias=ACTOR_HEADER)) -> Actor:
    """FastAPI dependency (spec B §2): who is writing. A missing header means
    the user. ``worker:*`` and ``restore`` are in-process only."""
    if value is None or not value.strip():
        return USER
    try:
        actor = parse_actor(value.strip())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"invalid {ACTOR_HEADER} header") from None
    if actor == RESTORE or actor.startswith("worker:"):
        raise HTTPException(
            status_code=400, detail=f"{ACTOR_HEADER}: {actor!r} is reserved for in-process writers",
        )
    return actor
```

- [ ] **Step 4: Thread the actor through the repo functions**

In `ghostbrain/api/repo/note.py`, replace `save_note_body` with:

```python
def save_note_body(
    rel_path: str,
    body: str,
    *,
    actor: Actor = USER,
    base_etag: str | None = None,
    reason: str = "edited in the editor",
) -> dict:
    """Rewrite only the markdown body; the frontmatter block's bytes are kept
    exactly (spec B1). ``updated`` is bumped only when the key already exists.
    A stale ``base_etag`` raises WriteConflict (→ 409)."""
    target = _resolve_safe(rel_path)
    if not target.exists() or not target.is_file():
        raise NoteNotFound(rel_path)
    res = vault_write.write(
        rel_path, body=body, actor=actor, base_etag=base_etag, reason=reason,
    )
    return {"path": rel_path, "updated": res.updated, "etag": res.etag,
            "historyOk": res.history_ok}
```

In `ghostbrain/api/repo/notes_manual.py`:

- `move_jot`: add `base_etag: str | None = None,` after `actor: Actor = USER,` in the signature, and add `base_etag=base_etag,` to its `vault_write.write(...)` call.
- Replace `delete_jot` with:

```python
def delete_jot(jot_id: str, *, actor: Actor = USER, base_etag: str | None = None) -> None:
    path = _find_file(jot_id)
    vault_write.write(
        _vault_rel(path), op="delete", actor=actor, reason="deleted jot", base_etag=base_etag,
    )
```

- In `create_and_route_jot`, change the signature to `def create_and_route_jot(body: str, *, captured_at: "datetime | None" = None, actor: Actor = USER) -> dict:` and its first line to `record = write_inbox_jot(body, captured_at=captured_at, actor=actor)`.

In `ghostbrain/api/repo/generated_docs.py`, change the import to `from ghostbrain.vault_write import MCP, Actor`, the signature to `def write_doc(title: str, html: str, *, actor: Actor = MCP) -> dict:`, and `actor=MCP,` inside `write_new(...)` to `actor=actor,`.

- [ ] **Step 5: Read the header in the routes**

In `ghostbrain/api/routes/notes.py`, replace the import `from ghostbrain.api.vault_http import if_match` with `from ghostbrain.api.vault_http import if_match, request_actor`, and the `vault_write` import plus the `_PLUGIN_WRITER` comment block with:

```python
from ghostbrain.vault_write import ASSISTANT, USER, Actor, plugin_actor

# PUT /v1/notes is the plugin write-back route. The desktop main process
# stamps X-Poltergeist-Actor: plugin:<id> (spec B §2); a request without the
# header (an older client) is still never invisible on the Changes screen.
_PLUGIN_WRITER = plugin_actor("unattributed")


def _edit_reason(actor: Actor, user_reason: str) -> str:
    if actor == USER:
        return user_reason
    if actor == ASSISTANT:
        return "accepted an assistant edit"
    return "edited through the API"
```

Replace `upsert_note` with:

```python
@router.put("", status_code=status.HTTP_200_OK)
def upsert_note(
    req: UpsertNoteRequest,
    base_etag: str | None = Depends(if_match),
    actor: Actor = Depends(request_actor),
) -> dict:
    """Create or replace a vault note at an explicit path (plugin write-back)."""
    if not req.content.strip():
        raise HTTPException(status_code=422, detail="content must not be empty")
    writer = _PLUGIN_WRITER if actor == USER else actor
    try:
        return save_note_at_path(req.path, req.content, actor=writer, base_etag=base_etag)
    except NoteInvalidPath as e:
        raise HTTPException(status_code=400, detail=str(e))
```

In `create_note`, change the signature to `def create_note(req: CreateNoteRequest, actor: Actor = Depends(request_actor)) -> dict:`, the call `write_inbox_jot(body, captured_at=captured)` to `write_inbox_jot(body, captured_at=captured, actor=actor)`, and `return create_and_route_jot(body, captured_at=captured)` to `return create_and_route_jot(body, captured_at=captured, actor=actor)`.

Replace `patch_note_body`'s signature and its `return save_note_body(...)` line with:

```python
def patch_note_body(
    req: UpdateNoteBodyRequest,
    base_etag: str | None = Depends(if_match),
    actor: Actor = Depends(request_actor),
) -> dict:
```

```python
        return save_note_body(req.path, req.body, actor=actor, base_etag=base_etag,
                              reason=_edit_reason(actor, "edited in the editor"))
```

Replace `patch_note`'s signature and its `return update_jot_body(...)` line with:

```python
def patch_note(
    req: UpdateNoteRequest,
    jot_id: str = PathParam(..., min_length=8, max_length=128),
    base_etag: str | None = Depends(if_match),
    actor: Actor = Depends(request_actor),
) -> dict:
```

```python
        return update_jot_body(jot_id, body, actor=actor, base_etag=base_etag,
                               reason=_edit_reason(actor, "edited jot"))
```

In `route_note`, add the parameters `base_etag: str | None = Depends(if_match),` and `actor: Actor = Depends(request_actor),` after `jot_id`. In its `move_jot(...)` call, replace `actor=USER,` with:

```python
            actor=actor,
            base_etag=base_etag,
```

Replace `delete_note` with:

```python
@router.delete("/{jot_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(
    jot_id: str = PathParam(..., min_length=8, max_length=128),
    base_etag: str | None = Depends(if_match),
    actor: Actor = Depends(request_actor),
) -> Response:
    """Delete a jot permanently."""
    try:
        delete_jot(jot_id, actor=actor, base_etag=base_etag)
    except JotNotFound:
        raise HTTPException(status_code=404, detail=f"Jot not found: {jot_id}")
    return Response(status_code=204)
```

In `ghostbrain/api/routes/docs.py`, change `from fastapi import APIRouter, HTTPException` to `from fastapi import APIRouter, Depends, HTTPException`, add `from ghostbrain.api.vault_http import request_actor` and `from ghostbrain.vault_write import MCP, USER, Actor`, and replace `write_doc` with:

```python
@router.post("/write", response_model=WriteDocResponse)
def write_doc(payload: WriteDocRequest, actor: Actor = Depends(request_actor)) -> dict:
    # Agent-only tool: a request without the header is still the MCP agent.
    writer = MCP if actor == USER else actor
    try:
        return generated_docs.write_doc(payload.title, payload.html, actor=writer)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd "$B2" && python -m pytest ghostbrain/api/tests -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
cd "$B2" && git add ghostbrain/api tests && git commit -m "feat(api): X-Poltergeist-Actor attribution on every write route (B2)"
```

---

### Task 6: `/v1/changes` routes

**Files:**
- Create: `ghostbrain/api/models/changes.py`
- Create: `ghostbrain/api/routes/changes.py`
- Modify: `ghostbrain/api/main.py`
- Test: `ghostbrain/api/tests/test_routes_changes.py`

**Interfaces:**
- Consumes: Task 1 (`log.list_changes`, `get`, `counts`, `degraded`, `clear_degraded`, `ChangeLogError`, `Change.to_api`); Task 3 (`revert`, `undo_revert`, `drift`, `read_current`, `matches_blob`, the exceptions); Task 5 (`request_actor`); `history.get_blob`.
- Produces (HTTP; the desktop relies on these shapes):
  - `GET /v1/changes?status=&actor=&since=&q=&limit=100` (limit 1–500) → `{"items": [ChangeSummary], "pendingCount": int, "degraded": bool}`, newest first. `ChangeSummary` is `Change.to_api()`. A bad `status` or `since` → 422. Change log unreadable → 503.
  - `GET /v1/changes/{id}` → `ChangeSummary` plus `{"before": str | null, "after": str | null, "current": str | null, "changedSince": bool, "diff": str}`. For a pending row, `after` holds the pending bytes. `diff` is a unified diff of before → after. `changedSince` compares the file with what a revert (applied) or an undo (reverted) expects. Unknown id → 404.
  - `POST /v1/changes/{id}/revert` and `POST /v1/changes/{id}/undo`, body `{"force": bool}` (optional; default false) → `{"id": int, "status": str, "path": str, "etag": str | null}`. Non-user actor header → 403. Wrong state → 400. Changed since → 409 `{"detail": CHANGED_SINCE_MESSAGE}`. Unknown id → 404. Version GC'd → 410. Move-back target occupied → 409 (write-path handler). History failure → 500.
  - `DELETE /v1/changes/degraded` → 204. It clears the "some changes may be missing" marker.

- [ ] **Step 1: Write the failing tests**

Create `ghostbrain/api/tests/test_routes_changes.py`:

```python
"""B2: /v1/changes — list, detail, revert, undo (spec B §5)."""
from __future__ import annotations

from ghostbrain.changes import log as changes
from ghostbrain.history import store
from ghostbrain.vault_write import compute_etag

FAM = {"X-Poltergeist-Actor": "plugin:familiar"}
REL = "Familiar/memory.md"


def _seed(client, auth) -> tuple[int, int]:
    h = {**auth, **FAM}
    assert client.put("/v1/notes", json={"path": REL, "content": "v1"}, headers=h).status_code == 200
    assert client.put("/v1/notes", json={"path": REL, "content": "v2"}, headers=h).status_code == 200
    created, modified = sorted(c.id for c in changes.list_changes())
    return created, modified


def test_list_is_empty_at_first(client, auth_headers):
    r = client.get("/v1/changes", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == {"items": [], "pendingCount": 0, "degraded": False}


def test_list_is_newest_first_and_filters(tmp_vault, client, auth_headers):
    created, modified = _seed(client, auth_headers)
    items = client.get("/v1/changes", headers=auth_headers).json()["items"]
    assert [i["id"] for i in items] == [modified, created]
    assert items[0] == {
        "id": modified, "ts": items[0]["ts"], "actor": "plugin:familiar", "path": REL,
        "destPath": None, "op": "modify", "reason": "plugin write-back", "status": "applied",
        "riskReasons": [], "resolvedTs": None,
    }
    get = lambda **p: client.get("/v1/changes", params=p, headers=auth_headers)  # noqa: E731
    assert get(actor="assistant").json()["items"] == []
    assert len(get(actor="plugin", q="memory").json()["items"]) == 2
    assert get(status="nope").status_code == 422
    assert get(since="yesterday").status_code == 422
    assert len(get(since="2000-01-01T00:00:00Z").json()["items"]) == 2


def test_detail_has_before_after_current_and_a_unified_diff(tmp_vault, client, auth_headers):
    _, modified = _seed(client, auth_headers)
    d = client.get(f"/v1/changes/{modified}", headers=auth_headers).json()
    assert (d["before"], d["after"], d["current"], d["changedSince"]) == ("v1\n", "v2\n", "v2\n", False)
    assert "-v1" in d["diff"] and "+v2" in d["diff"]
    (tmp_vault / REL).write_text("user edit\n")
    assert client.get(f"/v1/changes/{modified}", headers=auth_headers).json()["changedSince"] is True
    assert client.get("/v1/changes/9999", headers=auth_headers).status_code == 404


def test_revert_then_undo(tmp_vault, client, auth_headers):
    _, modified = _seed(client, auth_headers)
    r = client.post(f"/v1/changes/{modified}/revert", json={"force": False}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == {"id": modified, "status": "reverted", "path": REL,
                        "etag": compute_etag(b"v1\n")}
    assert (tmp_vault / REL).read_text() == "v1\n"
    assert client.post(f"/v1/changes/{modified}/revert", json={},
                       headers=auth_headers).status_code == 400
    u = client.post(f"/v1/changes/{modified}/undo", json={}, headers=auth_headers)
    assert u.status_code == 200 and u.json()["status"] == "applied"
    assert (tmp_vault / REL).read_text() == "v2\n"


def test_revert_without_a_body_defaults_to_no_force(tmp_vault, client, auth_headers):
    _, modified = _seed(client, auth_headers)
    assert client.post(f"/v1/changes/{modified}/revert", headers=auth_headers).status_code == 200


def test_revert_after_an_outside_edit_is_409_until_forced(tmp_vault, client, auth_headers):
    _, modified = _seed(client, auth_headers)
    (tmp_vault / REL).write_text("user edit\n")
    r = client.post(f"/v1/changes/{modified}/revert", json={}, headers=auth_headers)
    assert r.status_code == 409 and "changed since" in r.json()["detail"]
    assert (tmp_vault / REL).read_text() == "user edit\n"
    f = client.post(f"/v1/changes/{modified}/revert", json={"force": True}, headers=auth_headers)
    assert f.status_code == 200
    assert (tmp_vault / REL).read_text() == "v1\n"
    assert store.get_blob(store.list_snapshots(REL)[0].blob) == b"user edit\n"


def test_only_the_user_can_revert_or_undo(tmp_vault, client, auth_headers):
    _, modified = _seed(client, auth_headers)
    for action in ("revert", "undo"):
        r = client.post(f"/v1/changes/{modified}/{action}", json={},
                        headers={**auth_headers, **FAM})
        assert r.status_code == 403


def test_a_collected_version_is_410(tmp_vault, client, auth_headers):
    _, modified = _seed(client, auth_headers)
    store._blob_path(changes.get(modified).before_blob).unlink()
    r = client.post(f"/v1/changes/{modified}/revert", json={}, headers=auth_headers)
    assert r.status_code == 410


def test_degraded_flag_and_dismiss(client, auth_headers):
    changes.mark_degraded("insert failed")
    assert client.get("/v1/changes", headers=auth_headers).json()["degraded"] is True
    assert client.delete("/v1/changes/degraded", headers=auth_headers).status_code == 204
    assert client.get("/v1/changes", headers=auth_headers).json()["degraded"] is False


def test_an_unavailable_change_log_is_503(client, auth_headers, monkeypatch):
    def boom(**_k):
        raise changes.ChangeLogError("database is locked")

    monkeypatch.setattr(changes, "list_changes", boom)
    assert client.get("/v1/changes", headers=auth_headers).status_code == 503
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "$B2" && python -m pytest ghostbrain/api/tests/test_routes_changes.py -q`
Expected: FAIL. `GET /v1/changes` returns 404 (no router yet).

- [ ] **Step 3: Add the model**

Create `ghostbrain/api/models/changes.py`:

```python
"""Change-log request schemas (spec B §5, slice B2)."""
from pydantic import BaseModel

STATUS_PATTERN = r"^(applied|pending|reverted|rejected|conflicted)$"


class ChangeActionRequest(BaseModel):
    force: bool = False
```

- [ ] **Step 4: Add the routes**

Create `ghostbrain/api/routes/changes.py`:

```python
"""Change log routes (spec B §5; slice B2): list, detail, revert, undo.

Approve / reject of pending changes are B3. Revert and undo are user-only and
go through ``ghostbrain.changes.revert``, which writes as ``restore``."""
from __future__ import annotations

import difflib
from datetime import datetime
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from ghostbrain import history
from ghostbrain.api.models.changes import STATUS_PATTERN, ChangeActionRequest
from ghostbrain.api.vault_http import request_actor
from ghostbrain.changes import log as changes_log
from ghostbrain.changes import revert as changes_revert
from ghostbrain.vault_write import USER, Actor

router = APIRouter(prefix="/v1/changes", tags=["changes"])

_UNAVAILABLE = "change log unavailable"


def _since(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=422, detail="since must be ISO 8601") from None
    if when.tzinfo is None:
        raise HTTPException(status_code=422, detail="since must include a timezone offset")
    return when


@router.get("")
def list_route(
    status: str | None = Query(None, pattern=STATUS_PATTERN),
    actor: str | None = Query(None, min_length=1, max_length=80),
    since: str | None = Query(None, max_length=40),
    q: str | None = Query(None, max_length=200),
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    when = _since(since)
    try:
        items = changes_log.list_changes(
            status=status, actor=actor, since=when, path_query=q, limit=limit,
        )
        pending = changes_log.counts().get("pending", 0)
    except changes_log.ChangeLogError:
        raise HTTPException(status_code=503, detail=_UNAVAILABLE) from None
    return {
        "items": [c.to_api() for c in items],
        "pendingCount": pending,
        "degraded": changes_log.degraded() is not None,
    }


@router.delete("/degraded", status_code=204)
def dismiss_degraded() -> Response:
    changes_log.clear_degraded()
    return Response(status_code=204)


def _get(change_id: int) -> changes_log.Change:
    try:
        c = changes_log.get(change_id)
    except changes_log.ChangeLogError:
        raise HTTPException(status_code=503, detail=_UNAVAILABLE) from None
    if c is None:
        raise HTTPException(status_code=404, detail="no such change")
    return c


def _text(blob: str | None) -> str | None:
    if blob is None:
        return None
    try:
        return history.get_blob(blob).decode("utf-8", errors="replace")
    except (history.BlobNotFound, ValueError):
        return None


@router.get("/{change_id}")
def get_route(change_id: int) -> dict:
    c = _get(change_id)
    before = _text(c.before_blob)
    after = _text(c.pending_bytes_blob if c.status == "pending" else c.after_blob)
    state = changes_revert.drift(c)
    current_bytes = state[1] if state is not None else changes_revert.read_current(c.current_path)
    changed = state is not None and not changes_revert.matches_blob(state[1], state[0].expect)
    diff = "".join(difflib.unified_diff(
        (before or "").splitlines(keepends=True),
        (after or "").splitlines(keepends=True),
        fromfile=f"a/{c.rel_path}",
        tofile=f"b/{c.current_path}",
    ))
    return {
        **c.to_api(),
        "before": before,
        "after": after,
        "current": (
            current_bytes.decode("utf-8", errors="replace") if current_bytes is not None else None
        ),
        "changedSince": changed,
        "diff": diff,
    }


def _act(
    change_id: int,
    req: ChangeActionRequest | None,
    actor: Actor,
    fn: Callable[..., changes_revert.RevertResult],
) -> dict:
    if actor != USER:
        raise HTTPException(status_code=403, detail="only you can revert or re-apply changes")
    force = req.force if req is not None else False
    try:
        res = fn(change_id, force=force)
    except changes_revert.ChangeNotFound:
        raise HTTPException(status_code=404, detail="no such change") from None
    except changes_revert.NotRevertable as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except changes_revert.ChangedSince as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    except changes_revert.VersionGone as e:
        raise HTTPException(status_code=410, detail=str(e)) from None
    except changes_log.ChangeLogError:
        raise HTTPException(status_code=503, detail=_UNAVAILABLE) from None
    return {"id": res.change.id, "status": res.change.status, "path": res.path, "etag": res.etag}


@router.post("/{change_id}/revert")
def revert_route(
    change_id: int,
    req: ChangeActionRequest | None = None,
    actor: Actor = Depends(request_actor),
) -> dict:
    return _act(change_id, req, actor, changes_revert.revert)


@router.post("/{change_id}/undo")
def undo_route(
    change_id: int,
    req: ChangeActionRequest | None = None,
    actor: Actor = Depends(request_actor),
) -> dict:
    return _act(change_id, req, actor, changes_revert.undo_revert)
```

- [ ] **Step 5: Register the router**

In `ghostbrain/api/main.py`, add `from ghostbrain.api.routes import changes as changes_routes` to the route imports (alphabetical, after `captures`), and add `app.include_router(changes_routes.router)` directly after `app.include_router(library_routes.router)`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd "$B2" && python -m pytest ghostbrain/api/tests -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
cd "$B2" && git add ghostbrain/api && git commit -m "feat(api): /v1/changes list, detail with diff, user-only revert and undo (B2)"
```

---

### Task 7: The MCP client attributes its writes

**Files:**
- Modify: `ghostbrain/mcp/client.py`
- Modify: `tests/test_mcp_client.py` (append)
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: Task 5's header name (`X-Poltergeist-Actor`).
- Produces: `SidecarClient(..., actor: str = "mcp")`. Every request carries `X-Poltergeist-Actor: <actor>`. This covers the MCP server and the local-provider vault tools (`llm/providers/vault_tools.py`, `openai_http.py`), which build `SidecarClient()` with the default.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mcp_client.py`:

```python
def test_every_request_carries_the_mcp_actor_header():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["actor"] = request.headers.get("x-poltergeist-actor")
        return httpx.Response(200, json={"path": "p.html", "title": "t"})

    _client(handler, DESCRIPTOR).write_doc("t", "<p>x</p>")
    assert seen["actor"] == "mcp"


def test_the_actor_can_be_set_per_client():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["actor"] = request.headers.get("x-poltergeist-actor")
        return httpx.Response(200, json={"items": [], "total": 0, "query": "x"})

    client = SidecarClient(
        loader=lambda: DESCRIPTOR,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        actor="assistant",
    )
    client.search("x")
    assert seen["actor"] == "assistant"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "$B2" && python -m pytest tests/test_mcp_client.py -q`
Expected: FAIL. `seen["actor"]` is `None`, and `SidecarClient` rejects the `actor` keyword with a `TypeError`.

- [ ] **Step 3: Send the header**

In `ghostbrain/mcp/client.py`, add below `DEFAULT_TIMEOUT = 60.0`:

```python
# Spec B §2: every vault write the agent makes is attributed to the MCP actor.
ACTOR_HEADER = "X-Poltergeist-Actor"
```

Replace `__init__` with:

```python
    def __init__(
        self,
        *,
        loader: Callable[[], dict | None] = load_descriptor,
        http_client: httpx.Client | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        actor: str = "mcp",
    ) -> None:
        self._loader = loader
        self._http = http_client or httpx.Client(timeout=timeout)
        self._actor = actor
```

and in `_request`, replace the `headers = …` line with:

```python
        headers = {"Authorization": f"Bearer {descriptor['token']}", ACTOR_HEADER: self._actor}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd "$B2" && python -m pytest tests/test_mcp_client.py -q`
Expected: PASS

- [ ] **Step 5: Add the test file to CI**

The file needs only `httpx` and `ghostbrain.api.runtime`, both of which are in `[dev,api]`. In `.github/workflows/ci.yml`, add after `tests/test_changes_maintenance.py \`:

```yaml
            tests/test_mcp_client.py \
```

- [ ] **Step 6: Commit**

```bash
cd "$B2" && git add ghostbrain/mcp/client.py tests/test_mcp_client.py .github/workflows/ci.yml && git commit -m "feat(mcp): stamp X-Poltergeist-Actor: mcp on every sidecar call (B2)"
```

---

### Task 8: Desktop main: forwarder actor + plugin stamping

**Files:**
- Modify: `desktop/src/shared/types.ts` (`WriteActor`; `api.request` opts; plugin `sidecar.request` opts)
- Modify: `desktop/src/main/api-forwarder.ts`
- Modify: `desktop/src/main/plugins/ipc.ts`
- Modify: `desktop/src/main/plugins/loader.ts`
- Modify: `desktop/src/main/index.ts`
- Modify: `desktop/src/preload/index.ts`
- Test: `desktop/src/main/__tests__/api-forwarder.test.ts` (update + append)
- Test: `desktop/src/main/plugins/__tests__/ipc-sidecar.test.ts` (rewrite)
- Test: `desktop/src/main/plugins/__tests__/loader.test.ts` (update one test)

**Interfaces:**
- Consumes: the sidecar's header contract (Task 5).
- Produces:
  - `shared/types.ts`: `export type WriteActor = 'assistant';`. `GbBridge.api.request(method, path, body?, opts?: { ifMatch?: string; actor?: WriteActor })`. `plugin(id).sidecar.request(method, path, body?, opts?: { ifMatch?: string })`.
  - `api-forwarder.ts`: `ACTOR_HEADER = 'X-Poltergeist-Actor'`. `requestHeadersFrom(opts: unknown): Record<string, string>` always sets the actor header (`'assistant'` only when `opts.actor === 'assistant'`, otherwise `'user'`), plus `If-Match` for a 16-hex etag. `pluginHeadersFrom(pluginId: string, opts?: unknown): Record<string, string> | null` returns `plugin:<id>` plus `If-Match`, or `null` when the id fails the manifest rule `/^[a-z][a-z0-9-]{1,31}$/`.
  - `makeSidecarHandler(deps)`: `deps.forward(m, p, body, headers)` and `deps.isKnownPlugin(id)`. The handler signature becomes `(pluginId, method, path, body?, opts?)`. `gb:plugins:sidecar` IPC args are `(pluginId, method, path, body, opts)`.
  - `LoaderDeps.fetchApi(method, path, body, headers: Record<string, string>)`. `PluginContext.api.fetch(method, path, body?, opts?: { ifMatch?: string })`.

- [ ] **Step 1: Write the failing tests**

In `desktop/src/main/__tests__/api-forwarder.test.ts`, change the import to `import { ACTOR_HEADER, forward, isAllowedMethod, isSafeApiPath, pluginHeadersFrom, requestHeadersFrom } from '../api-forwarder';`. Replace the two `requestHeadersFrom` tests inside `describe('If-Match passthrough', …)` with:

```ts
  it('requestHeadersFrom maps a 16-hex etag to a quoted If-Match and stamps the user', () => {
    expect(requestHeadersFrom({ ifMatch: '0123456789abcdef' })).toEqual({
      'If-Match': '"0123456789abcdef"',
      [ACTOR_HEADER]: 'user',
    });
  });

  it('requestHeadersFrom drops everything else but always names the actor', () => {
    const userOnly = { [ACTOR_HEADER]: 'user' };
    expect(requestHeadersFrom(undefined)).toEqual(userOnly);
    expect(requestHeadersFrom(null)).toEqual(userOnly);
    expect(requestHeadersFrom({ ifMatch: 'x\r\nX-Evil: 1' })).toEqual(userOnly);
    expect(requestHeadersFrom({ ifMatch: 'ABCDEF0123456789' })).toEqual(userOnly);
    expect(requestHeadersFrom({ authorization: 'Bearer x' })).toEqual(userOnly);
  });
```

Append to the end of the file:

```ts
describe('actor attribution (spec B §2)', () => {
  it('lets the renderer claim only the assistant', () => {
    expect(requestHeadersFrom({ actor: 'assistant' })).toEqual({ [ACTOR_HEADER]: 'assistant' });
    for (const forged of ['mcp', 'plugin:familiar', 'worker:reversal', 'restore', 'user ', 7]) {
      expect(requestHeadersFrom({ actor: forged })).toEqual({ [ACTOR_HEADER]: 'user' });
    }
  });

  it('stamps plugin calls with the plugin id and passes If-Match', () => {
    expect(pluginHeadersFrom('familiar')).toEqual({ [ACTOR_HEADER]: 'plugin:familiar' });
    expect(pluginHeadersFrom('familiar', { ifMatch: '0123456789abcdef' })).toEqual({
      [ACTOR_HEADER]: 'plugin:familiar',
      'If-Match': '"0123456789abcdef"',
    });
    expect(pluginHeadersFrom('familiar', { actor: 'assistant' })).toEqual({
      [ACTOR_HEADER]: 'plugin:familiar',
    });
  });

  it('refuses ids that are not plugin ids', () => {
    for (const bad of ['', 'Familiar', '../x', 'a', 'x:y', 'a'.repeat(40)]) {
      expect(pluginHeadersFrom(bad)).toBeNull();
    }
  });

  it('sends the actor header to the sidecar', async () => {
    await forward(sidecar(), 'PUT', '/v1/notes', { path: 'a.md', content: 'x' }, undefined,
      pluginHeadersFrom('familiar')!);
    expect(lastReq.headers['x-poltergeist-actor']).toBe('plugin:familiar');
  });
});
```

Replace the whole of `desktop/src/main/plugins/__tests__/ipc-sidecar.test.ts` with:

```ts
import { describe, it, expect, vi, beforeEach } from 'vitest';

// The handler factory is pure over its deps; we test it directly (no ipcMain).
import { makeSidecarHandler } from '../ipc';

const ACTOR = 'X-Poltergeist-Actor';

describe('gb:plugins:sidecar', () => {
  const forward = vi.fn(async () => ({ ok: true as const, data: { hi: 1 } }));
  const handler = makeSidecarHandler({
    forward: forward as never,
    isAllowedMethod: (m: string) => ['GET', 'POST', 'PATCH', 'DELETE', 'PUT'].includes(m),
    isKnownPlugin: (id: string) => id === 'familiar',
    demo: false,
    handleDemoApi: vi.fn(),
  });

  beforeEach(() => forward.mockClear());

  it('rejects non-/v1 paths', async () => {
    expect(await handler('familiar', 'GET', '/etc/passwd')).toEqual({
      ok: false,
      error: expect.stringContaining('/v1/'),
    });
    expect(forward).not.toHaveBeenCalled();
  });

  it('rejects disallowed methods', async () => {
    expect(await handler('familiar', 'OPTIONS', '/v1/import/jira/issues')).toEqual({
      ok: false,
      error: expect.stringContaining('Method'),
    });
  });

  it('forwards a valid /v1 call stamped with the plugin id', async () => {
    const r = await handler('familiar', 'get', '/v1/import/confluence/spaces');
    expect(forward).toHaveBeenCalledWith('GET', '/v1/import/confluence/spaces', undefined, {
      [ACTOR]: 'plugin:familiar',
    });
    expect(r).toEqual({ ok: true, data: { hi: 1 } });
  });

  it('passes a well-formed If-Match through', async () => {
    await handler('familiar', 'PUT', '/v1/notes', { path: 'a.md', content: 'x' }, {
      ifMatch: '0123456789abcdef',
    });
    expect(forward).toHaveBeenCalledWith('PUT', '/v1/notes', { path: 'a.md', content: 'x' }, {
      [ACTOR]: 'plugin:familiar',
      'If-Match': '"0123456789abcdef"',
    });
  });

  it('refuses an unknown or malformed plugin id', async () => {
    expect(await handler('someone-else', 'GET', '/v1/x')).toEqual({
      ok: false,
      error: 'unknown plugin',
    });
    expect(await handler(undefined, 'GET', '/v1/x')).toEqual({ ok: false, error: 'unknown plugin' });
    expect(forward).not.toHaveBeenCalled();
  });

  it('uses the demo handler in demo mode', async () => {
    const demoFn = vi.fn(async () => ({ ok: true as const, data: 'demo' }));
    const h = makeSidecarHandler({
      forward: forward as never,
      isAllowedMethod: () => true,
      isKnownPlugin: () => true,
      demo: true,
      handleDemoApi: demoFn as never,
    });
    expect(await h('familiar', 'GET', '/v1/x')).toEqual({ ok: true, data: 'demo' });
  });

  it('rejects a non-string path/method', async () => {
    expect(await handler('familiar', 5 as never, '/v1/x')).toEqual({
      ok: false,
      error: 'Invalid request shape',
    });
  });
});
```

In `desktop/src/main/plugins/__tests__/loader.test.ts`, in `'exposes api.fetch that validates and delegates to deps.fetchApi'` (the fixture plugin's id is `ctx-capture`), replace everything from `const ok = await ctx!.api.fetch('GET', '/v1/vault/stats');` to the end of the test with:

```ts
    const ok = await ctx!.api.fetch('GET', '/v1/vault/stats');
    expect(ok).toEqual({ ok: true, data: { hello: 1 } });
    expect(calls).toEqual([
      ['GET', '/v1/vault/stats', undefined, { 'X-Poltergeist-Actor': 'plugin:ctx-capture' }],
    ]);

    await ctx!.api.fetch('PUT', '/v1/notes', { path: 'a.md', content: 'x' }, {
      ifMatch: '0123456789abcdef',
    });
    expect(calls[1]).toEqual([
      'PUT',
      '/v1/notes',
      { path: 'a.md', content: 'x' },
      { 'X-Poltergeist-Actor': 'plugin:ctx-capture', 'If-Match': '"0123456789abcdef"' },
    ]);

    const badMethod = await ctx!.api.fetch('TRACE', '/v1/x');
    expect(badMethod.ok).toBe(false);

    const badPath = await ctx!.api.fetch('GET', 'v1/../x');
    expect(badPath.ok).toBe(false);
    expect(calls.length).toBe(2); // invalid calls never reach fetchApi
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "$B2/desktop" && npx vitest run src/main/__tests__/api-forwarder.test.ts src/main/plugins/__tests__/ipc-sidecar.test.ts src/main/plugins/__tests__/loader.test.ts`
Expected: FAIL. `ACTOR_HEADER`/`pluginHeadersFrom` are not exported, the sidecar handler forwards without headers, and the loader passes only three arguments.

- [ ] **Step 3: Shared types**

In `desktop/src/shared/types.ts`, add next to the `HttpMethod` export:

```ts
/** The only non-user actor the renderer may claim (spec B §2): inline AI and
 * the docs panel's Accept. The main process sends everything else as user. */
export type WriteActor = 'assistant';
```

In `GbBridge.api.request`, change `opts?: { ifMatch?: string },` to `opts?: { ifMatch?: string; actor?: WriteActor },`. In `plugin(id).sidecar.request`, add a fourth parameter after `body?: unknown,`:

```ts
        opts?: { ifMatch?: string },
```

- [ ] **Step 4: Forwarder headers**

In `desktop/src/main/api-forwarder.ts`, change the type import to `import type { HttpMethod, WriteActor } from '../shared/types';` and replace the `requestHeadersFrom` doc comment and function with:

```ts
/** Spec B §2: who is writing. The sidecar reads it; a missing header = user. */
export const ACTOR_HEADER = 'X-Poltergeist-Actor';

/** Same rule as the plugin manifest id (shared/plugin-types.ts). */
const PLUGIN_ID_RE = /^[a-z][a-z0-9-]{1,31}$/;

function ifMatchFrom(opts: unknown): Record<string, string> {
  if (!opts || typeof opts !== 'object') return {};
  const ifMatch = (opts as { ifMatch?: unknown }).ifMatch;
  return typeof ifMatch === 'string' && ETAG_RE.test(ifMatch)
    ? { 'If-Match': `"${ifMatch}"` }
    : {};
}

/** Headers the renderer may ask the forwarder to set: If-Match (a 16-hex
 * etag, spec B §7) and the actor. The renderer may only claim `assistant`;
 * anything else is sent as `user`. Every other key is dropped. */
export function requestHeadersFrom(opts: unknown): Record<string, string> {
  const claimed = opts && typeof opts === 'object' ? (opts as { actor?: unknown }).actor : undefined;
  const actor: WriteActor | 'user' = claimed === 'assistant' ? 'assistant' : 'user';
  return { ...ifMatchFrom(opts), [ACTOR_HEADER]: actor };
}

/** Headers for a plugin's sidecar call (main-process `api.fetch` and the
 * renderer bridge): always `plugin:<id>`, plus If-Match. null for a string
 * that is not a plugin id. Best-effort (spec B §2): renderer-side plugin
 * code shares the renderer and could reach gb:api:request directly. */
export function pluginHeadersFrom(pluginId: string, opts?: unknown): Record<string, string> | null {
  if (!PLUGIN_ID_RE.test(pluginId)) return null;
  return { ...ifMatchFrom(opts), [ACTOR_HEADER]: `plugin:${pluginId}` };
}
```

- [ ] **Step 5: Plugin renderer bridge**

In `desktop/src/main/plugins/ipc.ts`, add `import { pluginHeadersFrom } from '../api-forwarder';` and replace `makeSidecarHandler` with:

```ts
/**
 * The plugin sidecar bridge, factored as a pure function over injected deps so
 * it is unit-testable without electron. Guards mirror the app's own
 * gb:api:request handler (method allowlist, path under /v1/); every call is
 * stamped `X-Poltergeist-Actor: plugin:<id>` for the change log (spec B §2).
 */
export function makeSidecarHandler(deps: {
  forward: (m: string, p: string, b: unknown, headers: Record<string, string>) => Promise<ApiResult>;
  isAllowedMethod: (m: string) => boolean;
  isKnownPlugin: (id: string) => boolean;
  demo: boolean;
  handleDemoApi: (m: string, p: string, b?: unknown) => Promise<ApiResult> | ApiResult;
}) {
  return async (
    pluginId: unknown,
    method: unknown,
    path: unknown,
    body?: unknown,
    opts?: unknown,
  ): Promise<ApiResult> => {
    if (typeof method !== 'string' || typeof path !== 'string') {
      return { ok: false, error: 'Invalid request shape' };
    }
    const headers =
      typeof pluginId === 'string' && deps.isKnownPlugin(pluginId)
        ? pluginHeadersFrom(pluginId, opts)
        : null;
    if (!headers) return { ok: false, error: 'unknown plugin' };
    const m = method.toUpperCase();
    if (!deps.isAllowedMethod(m)) return { ok: false, error: 'Method not allowed' };
    if (!path.startsWith('/v1/')) return { ok: false, error: 'Path not allowed (must start with /v1/)' };
    if (deps.demo) return deps.handleDemoApi(m, path, body);
    return deps.forward(m, path, body, headers);
  };
}
```

In `installPluginsIpc`, change the `sidecarBridge` option type to:

```ts
  sidecarBridge: (
    pluginId: unknown,
    method: unknown,
    path: unknown,
    body?: unknown,
    reqOpts?: unknown,
  ) => Promise<ApiResult>;
```

and the handler to:

```ts
  ipcMain.handle('gb:plugins:sidecar', (_e, pluginId, method, path, body, reqOpts) =>
    opts.sidecarBridge(pluginId, method, path, body, reqOpts),
  );
```

In `desktop/src/preload/index.ts`, replace the plugin `sidecar` block with:

```ts
    sidecar: {
      request: (method: string, path: string, body?: unknown, opts?: { ifMatch?: string }) =>
        ipcRenderer.invoke('gb:plugins:sidecar', id, method, path, body, opts),
    },
```

- [ ] **Step 6: Plugin main-process `api.fetch`**

In `desktop/src/main/plugins/loader.ts`, change the forwarder import to `import { isAllowedMethod, isSafeApiPath, pluginHeadersFrom, type ApiResult, type HttpMethod } from '../api-forwarder';`. In `PluginContext.api`, change the signature to:

```ts
    fetch(method: string, path: string, body?: unknown, opts?: { ifMatch?: string }): Promise<ApiResult>;
```

In `LoaderDeps`, change `fetchApi` to:

```ts
  fetchApi(
    method: HttpMethod,
    path: string,
    body: unknown,
    headers: Record<string, string>,
  ): Promise<ApiResult>;
```

and replace the `api: { fetch: … }` block in the context builder with:

```ts
      api: {
        fetch: async (method, path, body, opts) => {
          if (!isAllowedMethod(method)) {
            return { ok: false, error: `method not allowed: ${method}` };
          }
          if (typeof path !== 'string' || !isSafeApiPath(path)) {
            return { ok: false, error: 'invalid api path' };
          }
          const headers = pluginHeadersFrom(record.id, opts);
          if (!headers) return { ok: false, error: 'invalid plugin id' };
          return deps.fetchApi(method, path, body, headers);
        },
      },
```

In `desktop/src/main/index.ts`, inside `installPlugins()`, replace the `fetchApi` line with:

```ts
    fetchApi: (method, path, body, headers) => forward(sidecar, method, path, body, 900_000, headers),
```

and the `makeSidecarHandler({...})` call with:

```ts
  const sidecarBridge = makeSidecarHandler({
    forward: (m, p, b, h) => forward(sidecar, m as never, p, b, undefined, h),
    isAllowedMethod,
    isKnownPlugin: (id) => loader.records().some((r) => r.id === id),
    demo: DEMO,
    handleDemoApi: (m, p, b) => handleDemoApi(m as never, p, b),
  });
```

- [ ] **Step 7: Run the tests, typecheck and lint**

Run: `cd "$B2/desktop" && npx vitest run src/main && npm run typecheck && npm run lint`
Expected: PASS. If `loader.test.ts`'s `makeDeps` default `fetchApi` stub fails typecheck, give it the new four-parameter signature: `fetchApi: async () => ({ ok: false, error: 'fetchApi not stubbed in this test' })` already satisfies it.

- [ ] **Step 8: Commit**

```bash
cd "$B2" && git add desktop/src && git commit -m "feat(desktop): stamp X-Poltergeist-Actor in the forwarder and both plugin bridges (B2)"
```

---

### Task 9: Desktop renderer: the docs panel's Accept is an assistant write

**Files:**
- Modify: `desktop/src/renderer/lib/api/client.ts` (`patch` opts `actor`)
- Modify: `desktop/src/renderer/lib/api/hooks.ts` (`useUpdateJot` vars `actor`)
- Modify: `desktop/src/renderer/lib/use-guarded-save.ts` (`attributeNext`)
- Modify: `desktop/src/renderer/components/GuardedNoteEditor.tsx` (`GuardHandle.attributeNext`)
- Modify: `desktop/src/renderer/components/DocsAssistPanel.tsx` (`onAccept`)
- Modify: `desktop/src/renderer/screens/jots.tsx`
- Test: `desktop/src/renderer/__tests__/use-guarded-save.test.tsx` (append)
- Test: `desktop/src/renderer/__tests__/api-client.test.ts` (append)
- Test: `desktop/src/renderer/__tests__/DocsAssistPanel.test.tsx` (append)

**Interfaces:**
- Consumes: `WriteActor` (Task 8); the forwarder accepts `opts.actor === 'assistant'`.
- Produces:
  - `patch<T>(path, body?, opts?: { ifMatch?: string | null; actor?: WriteActor })`. The 4th bridge argument is sent only when it has a key.
  - `useUpdateJot()` vars: `{ id; body; ifMatch?; actor?: WriteActor }`.
  - `SaveTarget.send(body, ifMatch, actor?: WriteActor)`. The third argument is passed **only** for an attributed save, so existing call-shape assertions hold.
  - `GuardedSave.attributeNext(actor: WriteActor): void` marks the next `save()` (and only it) as that actor's. The mark rides with a queued body and with the auto-resolve resend, and is dropped when the save lands in a conflict (the user then decides).
  - `GuardHandle.attributeNext(actor: WriteActor): void`.
  - `<DocsAssistPanel onAccept?: () => void />` is called before the editor text is replaced.

- [ ] **Step 1: Write the failing tests**

Append inside `describe('useGuardedSave', …)` in `desktop/src/renderer/__tests__/use-guarded-save.test.tsx`:

```tsx
  it('attributeNext marks only the next save', async () => {
    const send = vi.fn().mockResolvedValueOnce({ etag: 'e2' }).mockResolvedValueOnce({ etag: 'e3' });
    const { result } = renderHook(() =>
      useGuardedSave({ body: 'a', etag: 'e1' }, { send, fetchLatest: vi.fn() }),
    );
    act(() => {
      result.current.attributeNext('assistant');
      result.current.save('ai text');
    });
    await waitFor(() => expect(send).toHaveBeenCalledTimes(1));
    await act(async () => {});
    act(() => result.current.save('typed after'));
    await waitFor(() => expect(send).toHaveBeenCalledTimes(2));
    expect(send.mock.calls).toEqual([
      ['ai text', 'e1', 'assistant'],
      ['typed after', 'e2'],
    ]);
  });

  it('an attributed save queued behind an in-flight save keeps its mark', async () => {
    const first = deferred<{ etag: string }>();
    const send = vi.fn().mockReturnValueOnce(first.promise).mockResolvedValueOnce({ etag: 'e3' });
    const { result } = renderHook(() =>
      useGuardedSave({ body: 'a', etag: 'e1' }, { send, fetchLatest: vi.fn() }),
    );
    act(() => result.current.save('typing'));
    act(() => {
      result.current.attributeNext('assistant');
      result.current.save('ai text');
    });
    act(() => result.current.save('ai text + a keystroke'));
    await act(async () => first.resolve({ etag: 'e2' }));
    await waitFor(() => expect(send).toHaveBeenCalledTimes(2));
    expect(send.mock.calls[1]).toEqual(['ai text + a keystroke', 'e2', 'assistant']);
  });

  it('the auto-resolve resend after a frontmatter-only change keeps the mark', async () => {
    const send = vi.fn().mockRejectedValueOnce(conflict()).mockResolvedValueOnce({ etag: 'e9' });
    const fetchLatest = vi.fn().mockResolvedValue({ body: 'a', etag: 'e5' });
    const { result } = renderHook(() =>
      useGuardedSave({ body: 'a', etag: 'e1' }, { send, fetchLatest }),
    );
    act(() => {
      result.current.attributeNext('assistant');
      result.current.save('ai text');
    });
    await waitFor(() => expect(send).toHaveBeenCalledTimes(2));
    expect(send.mock.calls[1]).toEqual(['ai text', 'e5', 'assistant']);
  });
```

Append inside the existing `describe` block in `desktop/src/renderer/__tests__/api-client.test.ts` (it already stubs `window.gb.api.request` as `request`; reuse that name):

```ts
  it('passes the assistant actor as a bridge option', async () => {
    await patch('/v1/notes/x', { body: 'b' }, { ifMatch: 'aaaaaaaaaaaaaaaa', actor: 'assistant' });
    expect(request).toHaveBeenLastCalledWith('PATCH', '/v1/notes/x', { body: 'b' }, {
      ifMatch: 'aaaaaaaaaaaaaaaa',
      actor: 'assistant',
    });
    await patch('/v1/notes/x', { body: 'b' }, { actor: 'assistant' });
    expect(request).toHaveBeenLastCalledWith('PATCH', '/v1/notes/x', { body: 'b' }, { actor: 'assistant' });
  });
```

(If that file names the stub differently, use its name. The assertion targets the `window.gb.api.request` mock.)

Append inside `describe` in `desktop/src/renderer/__tests__/DocsAssistPanel.test.tsx`:

```tsx
  it('Accept tells the editor the next save is the assistant’s before replacing the text', async () => {
    const { fire } = captureDocsListener();
    const order: string[] = [];
    const handle = makeHandle({ replaceWith: vi.fn(() => order.push('replace')) });
    const onAccept = vi.fn(() => order.push('attribute'));
    render(<DocsAssistPanel jotId={JOTID} editorHandle={handle} onAccept={onAccept} />);
    fireEvent.click(screen.getByRole('button', { name: 'polish' }));
    await waitFor(() => expect(useDocsAssist.getState().phase).toBe('streaming'));
    act(() => {
      fire({ jotId: JOTID, event: { type: 'done', text: 'polished' } });
    });
    fireEvent.click(await screen.findByRole('button', { name: /accept/i }));
    expect(order).toEqual(['attribute', 'replace']);
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "$B2/desktop" && npx vitest run src/renderer/__tests__/use-guarded-save.test.tsx src/renderer/__tests__/api-client.test.ts src/renderer/__tests__/DocsAssistPanel.test.tsx`
Expected: FAIL. `result.current.attributeNext is not a function`, the bridge receives `{ ifMatch }` only, and `onAccept` is never called.

- [ ] **Step 3: Client and hook**

In `desktop/src/renderer/lib/api/client.ts`, add `import type { WriteActor } from '../../../shared/types';` and replace `patch` with:

```ts
export async function patch<T>(
  path: string,
  body?: unknown,
  opts?: { ifMatch?: string | null; actor?: WriteActor },
): Promise<T> {
  // Only send the 4th bridge arg when it carries something — keeps the
  // common call shape (and existing assertions on it) unchanged.
  const bridgeOpts: { ifMatch?: string; actor?: WriteActor } = {};
  if (opts?.ifMatch) bridgeOpts.ifMatch = opts.ifMatch;
  if (opts?.actor) bridgeOpts.actor = opts.actor;
  const result =
    Object.keys(bridgeOpts).length > 0
      ? await window.gb.api.request<T>('PATCH', path, body, bridgeOpts)
      : await window.gb.api.request<T>('PATCH', path, body);
  if (!result.ok) throw new ApiError(result.error, result.status);
  return result.data;
}
```

In `desktop/src/renderer/lib/api/hooks.ts`, add `import type { WriteActor } from '../../../shared/types';` and replace `useUpdateJot`'s `mutationFn` with:

```ts
    mutationFn: (vars: { id: string; body: string; ifMatch?: string | null; actor?: WriteActor }) =>
      patch<UpdateJotResponse>(
        `/v1/notes/${encodeURIComponent(vars.id)}`,
        { body: vars.body },
        { ifMatch: vars.ifMatch, ...(vars.actor ? { actor: vars.actor } : {}) },
      ),
```

- [ ] **Step 4: Guarded save**

In `desktop/src/renderer/lib/use-guarded-save.ts`, add `import type { WriteActor } from '../../shared/types';`. Change `SaveTarget.send` to:

```ts
  /** Persist `body`; `ifMatch` is the etag the save is based on (null = unconditional).
   * `actor` is passed only for an attributed save (spec B §2: docs Accept). */
  send: (body: string, ifMatch: string | null, actor?: WriteActor) => Promise<{ etag?: string | null }>;
```

Add to the `GuardedSave` interface:

```ts
  /** The next save() is `actor`'s write (the docs panel's Accept), not a
   * keystroke. Rides with that body through the queue and the auto-resolve
   * resend; dropped if the save lands in a conflict (the user decides then). */
  attributeNext: (actor: WriteActor) => void;
```

Directly below `const queuedRef = useRef<string | null>(null);`, add:

```ts
  const nextActorRef = useRef<WriteActor | null>(null);
  const queuedActorRef = useRef<WriteActor | null>(null);
  const sendAs = (body: string, ifMatch: string | null, actor?: WriteActor) =>
    actor ? targetRef.current.send(body, ifMatch, actor) : targetRef.current.send(body, ifMatch);
```

Replace `handleConflict`, `run` and `save` with:

```ts
  const handleConflict = async (
    mine: string,
    allowAutoResolve: boolean,
    actor?: WriteActor,
  ): Promise<void> => {
    let latest: { body: string; etag?: string | null };
    try {
      latest = await targetRef.current.fetchLatest();
    } catch (err) {
      onErrorRef.current?.(asError(err));
      // Keystrokes may have landed in the conflict while we awaited.
      setConflict({ mine: conflictRef.current?.mine ?? mine, theirs: '', theirsEtag: null, unread: true });
      return;
    }
    if (sameBody(latest.body, mine)) {
      // Disk already holds my text: nothing to resolve, just take its etag.
      markSaved(mine, latest.etag);
      const c = conflictRef.current;
      if (c && sameBody(c.mine, mine)) setConflict(null);
      return;
    }
    if (allowAutoResolve && sameBody(latest.body, baseBodyRef.current)) {
      try {
        const res = await sendAs(mine, latest.etag ?? null, actor);
        markSaved(mine, res.etag);
      } catch (err) {
        if (isConflict(err)) await handleConflict(mine, false, actor);
        else onErrorRef.current?.(asError(err));
      }
      return;
    }
    setConflict({
      mine: conflictRef.current?.mine ?? mine,
      theirs: latest.body,
      theirsEtag: latest.etag ?? null,
    });
  };

  const run = async (body: string, actor?: WriteActor): Promise<void> => {
    inFlightRef.current = true;
    try {
      const res = await sendAs(body, etagRef.current, actor);
      markSaved(body, res.etag);
    } catch (err) {
      if (isConflict(err)) await handleConflict(body, true, actor);
      else onErrorRef.current?.(asError(err));
    } finally {
      inFlightRef.current = false;
    }
    const next = queuedRef.current;
    const nextActor = queuedActorRef.current ?? undefined;
    queuedRef.current = null;
    queuedActorRef.current = null;
    if (next === null) return;
    if (conflictRef.current) setConflict({ ...conflictRef.current, mine: next });
    else await run(next, nextActor);
  };

  const save = (body: string) => {
    const actor = nextActorRef.current ?? undefined;
    nextActorRef.current = null;
    if (conflictRef.current) {
      setConflict({ ...conflictRef.current, mine: body });
      return;
    }
    if (inFlightRef.current) {
      // A newer body replaces the queued one but still holds the AI text,
      // so an assistant mark already queued is kept.
      queuedRef.current = body;
      if (actor) queuedActorRef.current = actor;
      return;
    }
    void run(body, actor);
  };
```

In A3's `runExclusive`, replace the three lines of its `finally` block that read the queue:

```ts
      const next = queuedRef.current;
      queuedRef.current = null;
      if (!ok && next !== null) void run(next);
```

with:

```ts
      const next = queuedRef.current;
      const nextActor = queuedActorRef.current ?? undefined;
      queuedRef.current = null;
      queuedActorRef.current = null;
      if (!ok && next !== null) void run(next, nextActor);
```

Add before the hook's `return`:

```ts
  const attributeNext = (actor: WriteActor) => {
    nextActorRef.current = actor;
  };
```

and add `attributeNext` to the returned object.

- [ ] **Step 5: Editor handle, panel and jots screen**

In `desktop/src/renderer/components/GuardedNoteEditor.tsx`, add `import type { WriteActor } from '../../shared/types';`. Add to `GuardHandle`:

```ts
  /** The next autosave is `actor`'s write (docs panel Accept, spec B §2). */
  attributeNext: (actor: WriteActor) => void;
```

and add this entry to the `useState<GuardHandle>(() => ({ … }))` initializer:

```tsx
    attributeNext: (actor) => guardLatest.current.attributeNext(actor),
```

In `desktop/src/renderer/components/DocsAssistPanel.tsx`, add to `Props`:

```ts
  /** Called just before an accepted proposal replaces the editor text, so the
   * resulting save is recorded as the assistant's (spec B §2). */
  onAccept?: () => void;
```

Change the component signature to `export function DocsAssistPanel({ jotId, editorHandle, onAccept }: Props) {`, and make `onAccept?.();` the first line of `handleAccept`.

In `desktop/src/renderer/screens/jots.tsx`, replace the `GuardedNoteEditor`'s `send=` prop with:

```tsx
                  send={(body, ifMatch, actor) =>
                    updateJot.mutateAsync({ id: selectedId!, body, ifMatch, actor })
                  }
```

and the `<DocsAssistPanel … />` element with:

```tsx
            <DocsAssistPanel
              jotId={selectedId}
              editorHandle={editorHandle}
              onAccept={() => guardRef.current?.attributeNext('assistant')}
            />
```

- [ ] **Step 6: Run the tests, typecheck and lint**

Run: `cd "$B2/desktop" && npx vitest run src/renderer && npm run typecheck && npm run lint`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
cd "$B2" && git add desktop/src && git commit -m "feat(desktop): docs-panel Accept saves as the assistant (B2)"
```

---

### Task 10: The Changes screen

**Files:**
- Modify: `desktop/src/shared/api-types.ts` (change-log types)
- Modify: `desktop/src/renderer/lib/api/hooks.ts` (change-log hooks)
- Create: `desktop/src/renderer/screens/changes.tsx`
- Modify: `desktop/src/renderer/stores/navigation.ts` (`'changes'`)
- Modify: `desktop/src/renderer/components/Sidebar.tsx` (nav item)
- Modify: `desktop/src/renderer/App.tsx` (route)
- Test: `desktop/src/renderer/__tests__/ChangesScreen.test.tsx`

**Interfaces:**
- Consumes: Task 6 HTTP shapes; A3's `LineDiffView` (`desktop/src/renderer/components/LineDiffView.tsx`) and `actorLabel` (`components/HistoryDrawer.tsx`); `useNoteView().open(path)`; `formatRelativeTime`; `toast`; `ApiError`.
- Produces:
  - Types: `ChangeStatus`, `ChangeOp`, `ChangeSummary { id: number; ts; actor; path; destPath: string | null; op: ChangeOp; reason; status: ChangeStatus; riskReasons: string[]; resolvedTs: string | null }`, `ChangesListResponse { items; pendingCount; degraded }`, `ChangeDetailResponse extends ChangeSummary { before; after; current: string | null; changedSince: boolean; diff: string }`, `ChangeActionResponse { id; status; path; etag: string | null }`.
  - Hooks: `changesQueryPath(f: ChangesFilter): string`, `useChanges(f: ChangesFilter)` (polls every 30 s), `useChange(id: number | null)`, `useRevertChange()` and `useUndoRevert()` (mutations over `{ id: number; force?: boolean }`), `useDismissChangesWarning()`. Here `ChangesFilter = { actor: string | null; q: string | null }`.
  - `ChangesScreen`, `dayKey(ts: string): string` (local `YYYY-MM-DD`), `groupByDay(items)`, `ACTOR_FILTERS`.
  - `ScreenId` gains `'changes'`. B3 adds the Pending section above the history list and the nav badge (`pendingCount` is already in the list response).

- [ ] **Step 1: Write the failing tests**

Create `desktop/src/renderer/__tests__/ChangesScreen.test.tsx`:

```tsx
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as client from '../lib/api/client';
import { ChangesScreen, dayKey } from '../screens/changes';
import { useNoteView } from '../stores/note-view';
import { useToasts } from '../stores/toast';
import type {
  ChangeDetailResponse,
  ChangesListResponse,
  ChangeSummary,
} from '../../shared/api-types';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ApiError: actual.ApiError, get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn() };
});
const getMock = vi.mocked(client.get);
const postMock = vi.mocked(client.post);
const delMock = vi.mocked(client.del);

const AI: ChangeSummary = {
  id: 2, ts: '2026-10-09T12:00:00+00:00', actor: 'assistant', path: '20-contexts/work/plan.md',
  destPath: null, op: 'modify', reason: 'polished intro', status: 'applied', riskReasons: [],
  resolvedTs: null,
};
const PLUGIN: ChangeSummary = {
  id: 1, ts: '2026-10-07T12:00:00+00:00', actor: 'plugin:familiar', path: 'Familiar/brief.md',
  destPath: null, op: 'create', reason: 'plugin write-back', status: 'reverted', riskReasons: [],
  resolvedTs: '2026-10-08T12:00:00+00:00',
};
const DETAIL: ChangeDetailResponse = {
  ...AI, before: 'old intro', after: 'new intro', current: 'typed since', changedSince: true,
  diff: '',
};

function list(over: Partial<ChangesListResponse> = {}): ChangesListResponse {
  return { items: [AI, PLUGIN], pendingCount: 0, degraded: false, ...over };
}

function setup(listResponse: ChangesListResponse = list()) {
  getMock.mockImplementation(async (path: string) => {
    if (path.startsWith('/v1/changes?')) return listResponse;
    if (path === '/v1/changes/2') return DETAIL;
    throw new Error(`unexpected GET ${path}`);
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ChangesScreen />
    </QueryClientProvider>,
  );
}

const messages = () => useToasts.getState().toasts.map((t) => t.message);

afterEach(() => {
  getMock.mockReset();
  postMock.mockReset();
  delMock.mockReset();
  useToasts.setState({ toasts: [] });
  useNoteView.setState({ path: null });
});

describe('ChangesScreen', () => {
  it('lists changes grouped by day with actor chips and reasons', async () => {
    setup();
    expect(await screen.findByText('polished intro')).toBeInTheDocument();
    // Scoped to the rows: the "✦ assistant" filter chip carries the same label.
    expect(within(screen.getByTestId('change-2')).getByText('✦ assistant')).toBeInTheDocument();
    expect(within(screen.getByTestId('change-1')).getByText('⧉ familiar')).toBeInTheDocument();
    const day = screen.getByRole('region', { name: dayKey(AI.ts) });
    expect(within(day).getByText('polished intro')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: dayKey(PLUGIN.ts) })).toBeInTheDocument();
  });

  it('filters by actor kind and by path', async () => {
    setup();
    await screen.findByText('polished intro');
    expect(getMock).toHaveBeenCalledWith('/v1/changes?limit=200');
    fireEvent.click(screen.getByRole('button', { name: '⧉ plugins' }));
    await waitFor(() => expect(getMock).toHaveBeenCalledWith('/v1/changes?limit=200&actor=plugin'));
    fireEvent.click(screen.getByRole('button', { name: 'all' }));
    fireEvent.change(screen.getByLabelText('filter by path'), { target: { value: 'plan' } });
    await waitFor(() => expect(getMock).toHaveBeenCalledWith('/v1/changes?limit=200&q=plan'));
  });

  it('shows the per-change diff on demand', async () => {
    setup();
    const row = await screen.findByTestId('change-2');
    fireEvent.click(within(row).getByRole('button', { name: 'diff' }));
    const diff = await screen.findByTestId('change-diff-2');
    expect(diff).toHaveTextContent('- old intro');
    expect(diff).toHaveTextContent('+ new intro');
  });

  it('reverts with one click', async () => {
    postMock.mockResolvedValue({ id: 2, status: 'reverted', path: AI.path, etag: 'e' });
    setup();
    const row = await screen.findByTestId('change-2');
    fireEvent.click(within(row).getByRole('button', { name: 'revert' }));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith('/v1/changes/2/revert', { force: false }));
    await waitFor(() => expect(messages().some((m) => m.includes('reverted'))).toBe(true));
  });

  it('asks before reverting a note that changed since, then forces', async () => {
    postMock
      .mockRejectedValueOnce(new client.ApiError('the note changed since this change', 409))
      .mockResolvedValueOnce({ id: 2, status: 'reverted', path: AI.path, etag: 'e' });
    setup();
    const row = await screen.findByTestId('change-2');
    fireEvent.click(within(row).getByRole('button', { name: 'revert' }));
    const prompt = await within(row).findByRole('alert');
    expect(prompt).toHaveTextContent('changed since');
    const drift = await screen.findByTestId('change-drift-2');
    expect(drift).toHaveTextContent('+ typed since');
    fireEvent.click(within(row).getByRole('button', { name: 'revert anyway' }));
    await waitFor(() => expect(postMock).toHaveBeenLastCalledWith('/v1/changes/2/revert', { force: true }));
  });

  it('a reverted row offers undo', async () => {
    postMock.mockResolvedValue({ id: 1, status: 'applied', path: PLUGIN.path, etag: 'e' });
    setup();
    const row = await screen.findByTestId('change-1');
    expect(within(row).getByText('reverted')).toBeInTheDocument();
    expect(within(row).queryByRole('button', { name: 'revert' })).toBeNull();
    fireEvent.click(within(row).getByRole('button', { name: 'undo' }));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith('/v1/changes/1/undo', { force: false }));
  });

  it('warns when the change log missed something, and can dismiss it', async () => {
    delMock.mockResolvedValue(null);
    setup(list({ degraded: true }));
    expect(await screen.findByText('some changes may be missing; see page history')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'dismiss' }));
    await waitFor(() => expect(delMock).toHaveBeenCalledWith('/v1/changes/degraded'));
  });

  it('opens the note when its path is clicked', async () => {
    setup();
    fireEvent.click(await screen.findByRole('button', { name: AI.path }));
    expect(useNoteView.getState().path).toBe(AI.path);
  });

  it('shows an empty state', async () => {
    setup(list({ items: [] }));
    expect(await screen.findByText('nothing has changed your notes yet')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "$B2/desktop" && npx vitest run src/renderer/__tests__/ChangesScreen.test.tsx`
Expected: FAIL. Resolving `../screens/changes` fails.

- [ ] **Step 3: Types**

Append to `desktop/src/shared/api-types.ts`:

```ts
export type ChangeStatus = 'applied' | 'pending' | 'reverted' | 'rejected' | 'conflicted';
export type ChangeOp = 'create' | 'modify' | 'delete' | 'move';

/** One row of the change log (spec B §4): a non-user write to the vault. */
export interface ChangeSummary {
  id: number;
  ts: string;
  /** assistant | mcp | plugin:<id> | worker:<job> */
  actor: string;
  /** Vault-relative path before the change. */
  path: string;
  /** Destination of a move; null otherwise. */
  destPath: string | null;
  op: ChangeOp;
  reason: string;
  status: ChangeStatus;
  /** Why the change was held (B3); empty otherwise. */
  riskReasons: string[];
  /** When it was reverted / rejected; null while applied or pending. */
  resolvedTs: string | null;
}

export interface ChangesListResponse {
  /** Newest first. */
  items: ChangeSummary[];
  pendingCount: number;
  /** A change-log insert failed after a write: some changes may be missing. */
  degraded: boolean;
}

export interface ChangeDetailResponse extends ChangeSummary {
  /** Whole file before the change; null for a create (or a GC'd version). */
  before: string | null;
  /** Whole file after (pending bytes for a pending change); null for a delete. */
  after: string | null;
  /** Whole file on disk now at the path a revert / undo acts on. */
  current: string | null;
  /** The file no longer holds what a revert (or undo) expects. */
  changedSince: boolean;
  /** Unified diff before → after. */
  diff: string;
}

export interface ChangeActionResponse {
  id: number;
  status: ChangeStatus;
  path: string;
  etag: string | null;
}
```

- [ ] **Step 4: Hooks**

In `desktop/src/renderer/lib/api/hooks.ts`, add `ChangeActionResponse`, `ChangeDetailResponse` and `ChangesListResponse` to the `from '../../../shared/api-types'` type import, and add at the end of the file:

```ts
// ── Change log (spec B, slice B2) ────────────────────────────────────────────

export interface ChangesFilter {
  /** assistant | mcp | plugin | worker | an exact actor; null = all */
  actor: string | null;
  /** Path substring; null = no filter. */
  q: string | null;
}

export function changesQueryPath(f: ChangesFilter): string {
  const params = new URLSearchParams({ limit: '200' });
  if (f.actor) params.set('actor', f.actor);
  if (f.q) params.set('q', f.q);
  return `/v1/changes?${params.toString()}`;
}

export function useChanges(f: ChangesFilter) {
  return useQuery({
    queryKey: ['changes', f.actor, f.q],
    queryFn: () => get<ChangesListResponse>(changesQueryPath(f)),
    refetchInterval: 30_000,
  });
}

export function useChange(id: number | null) {
  return useQuery({
    queryKey: ['change', id],
    queryFn: () => get<ChangeDetailResponse>(`/v1/changes/${id}`),
    enabled: id !== null,
    staleTime: 0,
  });
}

function useChangeAction(action: 'revert' | 'undo') {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: number; force?: boolean }) =>
      post<ChangeActionResponse>(`/v1/changes/${vars.id}/${action}`, { force: vars.force ?? false }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['changes'] });
      qc.invalidateQueries({ queryKey: ['change'] });
      qc.invalidateQueries({ queryKey: ['note'] });
      qc.invalidateQueries({ queryKey: ['note-by-path'] });
      qc.invalidateQueries({ queryKey: ['note-history'] });
      qc.invalidateQueries({ queryKey: JOTS_KEY });
      qc.invalidateQueries({ queryKey: ['vault', 'backlinks'] });
    },
  });
}

export function useRevertChange() {
  return useChangeAction('revert');
}

export function useUndoRevert() {
  return useChangeAction('undo');
}

export function useDismissChangesWarning() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => del('/v1/changes/degraded'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['changes'] }),
  });
}
```

- [ ] **Step 5: The screen**

Create `desktop/src/renderer/screens/changes.tsx`:

```tsx
import { useMemo, useState } from 'react';
import { ApiError } from '../lib/api/client';
import {
  useChange,
  useChanges,
  useDismissChangesWarning,
  useRevertChange,
  useUndoRevert,
} from '../lib/api/hooks';
import { formatRelativeTime } from '../lib/format';
import { actorLabel } from '../components/HistoryDrawer';
import { LineDiffView } from '../components/LineDiffView';
import { Btn } from '../components/Btn';
import { PanelEmpty } from '../components/PanelEmpty';
import { PanelError } from '../components/PanelError';
import { TopBar } from '../components/TopBar';
import { useNoteView } from '../stores/note-view';
import { toast } from '../stores/toast';
import type { ChangeOp, ChangeSummary } from '../../shared/api-types';

export const ACTOR_FILTERS: ReadonlyArray<{ id: string | null; label: string }> = [
  { id: null, label: 'all' },
  { id: 'assistant', label: '✦ assistant' },
  { id: 'mcp', label: '⌁ mcp' },
  { id: 'plugin', label: '⧉ plugins' },
  { id: 'worker', label: '⚙ jobs' },
];

const OP_LABEL: Record<ChangeOp, string> = {
  create: 'created',
  modify: 'edited',
  delete: 'deleted',
  move: 'moved',
};

/** Local calendar day of an ISO timestamp, as YYYY-MM-DD (locale-free). */
export function dayKey(ts: string): string {
  const d = new Date(ts);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Items arrive newest first, so days come out newest first too. */
export function groupByDay(items: ChangeSummary[]): Array<[string, ChangeSummary[]]> {
  const groups = new Map<string, ChangeSummary[]>();
  for (const c of items) {
    const key = dayKey(c.ts);
    const list = groups.get(key);
    if (list) list.push(c);
    else groups.set(key, [c]);
  }
  return [...groups.entries()];
}

function ChangeRow({ change }: { change: ChangeSummary }) {
  const [showDiff, setShowDiff] = useState(false);
  const [conflict, setConflict] = useState(false);
  const detail = useChange(showDiff || conflict ? change.id : null);
  const revert = useRevertChange();
  const undo = useUndoRevert();
  const openNote = useNoteView((s) => s.open);
  const reverted = change.status === 'reverted';
  const busy = revert.isPending || undo.isPending;
  const path = change.destPath ?? change.path;

  const act = async (force: boolean) => {
    const mutation = reverted ? undo : revert;
    try {
      await mutation.mutateAsync({ id: change.id, force });
      setConflict(false);
      toast.success(reverted ? 'change re-applied' : 'change reverted — the previous version is back');
    } catch (err) {
      if (!force && err instanceof ApiError && err.status === 409) {
        setConflict(true);
        return;
      }
      const message = err instanceof Error ? err.message : String(err);
      toast.error(`${reverted ? 'undo' : 'revert'} failed: ${message}`);
    }
  };

  const expected = detail.data ? (reverted ? detail.data.before : detail.data.after) : null;

  return (
    <li data-testid={`change-${change.id}`} className="border-b border-hairline py-2">
      <div className="flex items-center gap-3 text-12">
        <span className="flex-shrink-0 rounded-sm bg-fog px-[6px] py-[1px] font-mono text-10 text-ink-1">
          {actorLabel(change.actor)}
        </span>
        {path.endsWith('.md') ? (
          <button
            type="button"
            onClick={() => openNote(path)}
            className="min-w-0 cursor-pointer truncate border-none bg-transparent p-0 text-left text-ink-0 hover:underline"
          >
            {path}
          </button>
        ) : (
          <span className="min-w-0 truncate text-ink-0">{path}</span>
        )}
        <span className="flex-shrink-0 text-ink-2">{OP_LABEL[change.op]}</span>
        <span className="min-w-0 flex-1 truncate text-ink-2">{change.reason}</span>
        <span className="flex-shrink-0 font-mono text-10 text-ink-3">
          {formatRelativeTime(change.ts)}
        </span>
        <Btn variant="ghost" size="sm" onClick={() => setShowDiff((v) => !v)}>
          {showDiff ? 'hide diff' : 'diff'}
        </Btn>
        {change.status === 'applied' && (
          <Btn variant="secondary" size="sm" disabled={busy} onClick={() => void act(false)}>
            revert
          </Btn>
        )}
        {reverted && (
          <>
            <span className="font-mono text-10 text-ink-3">reverted</span>
            <Btn variant="ghost" size="sm" disabled={busy} onClick={() => void act(false)}>
              undo
            </Btn>
          </>
        )}
      </div>
      {showDiff && detail.data && (
        <LineDiffView
          testId={`change-diff-${change.id}`}
          className="mt-2 max-h-[320px]"
          oldText={detail.data.before ?? ''}
          newText={detail.data.after ?? ''}
          legend="- before · + after"
        />
      )}
      {conflict && (
        <div role="alert" className="mt-2 rounded-sm border border-oxblood/30 bg-oxblood/10 p-2 text-12">
          <p className="m-0 mb-2 text-ink-0">
            This note changed since. {reverted ? 'Re-apply' : 'Revert'} anyway? The current version
            stays in page history.
          </p>
          {detail.data && (
            <LineDiffView
              testId={`change-drift-${change.id}`}
              className="mb-2 max-h-[240px]"
              oldText={expected ?? ''}
              newText={detail.data.current ?? ''}
              legend="- expected · + on disk now"
            />
          )}
          <div className="flex gap-2">
            <Btn variant="danger" size="sm" disabled={busy} onClick={() => void act(true)}>
              {reverted ? 'undo anyway' : 'revert anyway'}
            </Btn>
            <Btn variant="ghost" size="sm" onClick={() => setConflict(false)}>
              cancel
            </Btn>
          </div>
        </div>
      )}
    </li>
  );
}

/** Spec B §6 (slice B2): every assistant / MCP / plugin / job change, with a
 * diff and one-click revert. B3 adds the Pending section above the history. */
export function ChangesScreen() {
  const [actor, setActor] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const changes = useChanges({ actor, q: query.trim() || null });
  const dismiss = useDismissChangesWarning();
  const groups = useMemo(
    () => groupByDay((changes.data?.items ?? []).filter((c) => c.status !== 'pending')),
    [changes.data],
  );

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <TopBar title="changes" subtitle="what assistants, plugins and jobs changed in your notes" />
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {changes.data?.degraded && (
          <div
            role="alert"
            className="mb-3 flex items-center gap-3 rounded-sm border border-oxblood/30 bg-oxblood/10 px-3 py-2 text-12 text-oxblood"
          >
            <span className="flex-1">some changes may be missing; see page history</span>
            <Btn variant="ghost" size="sm" onClick={() => dismiss.mutate()}>
              dismiss
            </Btn>
          </div>
        )}
        <div className="mb-4 flex flex-wrap items-center gap-2">
          {ACTOR_FILTERS.map((f) => (
            <button
              key={f.label}
              type="button"
              aria-pressed={actor === f.id}
              onClick={() => setActor(f.id)}
              className={`cursor-pointer rounded-r6 border px-[10px] py-[3px] text-12 ${
                actor === f.id
                  ? 'border-hairline-2 bg-vellum text-ink-0'
                  : 'border-transparent bg-transparent text-ink-2 hover:bg-vellum'
              }`}
            >
              {f.label}
            </button>
          ))}
          <input
            aria-label="filter by path"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="path contains…"
            className="ml-auto w-[220px] rounded-r6 border border-hairline bg-paper px-2 py-[3px] text-12 text-ink-0"
          />
        </div>
        {changes.isError ? (
          <PanelError
            message={`could not load changes: ${changes.error instanceof Error ? changes.error.message : 'unknown error'}`}
            onRetry={() => void changes.refetch()}
          />
        ) : changes.isLoading ? null : groups.length === 0 ? (
          <PanelEmpty icon="history" message="nothing has changed your notes yet" />
        ) : (
          groups.map(([day, items]) => (
            <section key={day} aria-label={day} className="mb-5">
              <h2 className="m-0 mb-2 font-mono text-10 uppercase tracking-eyebrow text-ink-2">
                {day}
              </h2>
              <ul className="m-0 list-none p-0">
                {items.map((c) => (
                  <ChangeRow key={c.id} change={c} />
                ))}
              </ul>
            </section>
          ))
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Navigation**

In `desktop/src/renderer/stores/navigation.ts`, add `| 'changes'` to `ScreenId` after `| 'docs'`.

In `desktop/src/renderer/components/Sidebar.tsx`, add to `NAV_ITEMS` directly after the `docs` entry:

```ts
  { id: 'changes', icon: 'history', label: 'changes' },
```

In `desktop/src/renderer/App.tsx`, add `import { ChangesScreen } from './screens/changes';` after the `DocsScreen` import, and `{active === 'changes' && <ChangesScreen />}` after the `docs` line in `<main>`.

- [ ] **Step 7: Run the full desktop gates**

Run: `cd "$B2/desktop" && npx vitest run && npm run typecheck && npm run lint`
Expected: PASS. If an existing Sidebar/App test counts nav items, update its expected count by one.

- [ ] **Step 8: Run the full backend suite once more**

Run: `cd "$B2" && python -m pytest ghostbrain/api/tests tests/test_changes_log.py tests/test_vault_write_changes.py tests/test_changes_revert.py tests/test_changes_maintenance.py tests/test_mcp_client.py tests/test_vault_write_history.py tests/test_vault_write_writer.py tests/test_vault_write_text.py tests/test_history_store.py tests/test_history_retention.py tests/test_scheduler_history_prune_job.py -q`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
cd "$B2" && git add desktop/src && git commit -m "feat(desktop): Changes screen — per-change diff, one-click revert, undo, filters (B2)"
```

---

## Manual check (after Task 10, by the user, not the agent)

Spec B "Manual" rows that B2 covers. Agents must not run the app.
- Let Familiar run a sweep. Its notes appear under ⧉ familiar and revert cleanly.
- Ask chat to write a doc. It appears under ⌁ mcp as "created", and Revert deletes it.
- Accept a docs-panel proposal on a jot. It appears under ✦ assistant. Then type in the jot and click Revert: the "changed since" prompt shows your text, and "revert anyway" keeps your text in page history.

## Self-review

- **Spec coverage.** §2 header, forwarder, plugin stamping in both bridges, MCP → Tasks 5, 7, 8 and 9. Worker jobs calling `write` in-process with `worker:<job>` already work through the write path; B4 migrates them. §4 change log, columns, statuses, indexes, SQLite and retention → Tasks 1 and 4. §1 step 7 (row skipped for user) → Task 2. §5 list, detail with diff, revert with 409/force, "revert recorded as a user write" (as `restore`, no row), and "original row becomes reverted" → Tasks 3 and 6. Approve/reject are B3. "Read routes gain an etag" already shipped in B1. §6 nav item, history grouped by day, actor chips, path, op, reason, expandable diff, Revert, "reverted · undo", filter chips, path search, click-through to `NoteView` → Task 10. The Pending section and badge are B3. Error handling: insert fails after write → degraded banner (Tasks 1, 2, 6, 10). Snapshot fails for a non-user write → refused (A3, plus Task 2 for creates). Revert of a deleted file recreates it (Task 3). B1 deferral, `base_etag` required where the spec says → Task 2 (writer and every in-repo caller) and Task 5 (routes).
- **Placeholder scan.** Every code step has full code. Edits to A3-owned code name the exact function or test and give the replacement text.
- **Type consistency.** `change_id` is `str` in `WriteResult` and `int` in the DB, API and TS (`id: number`). `ChangeSummary` keys match `Change.to_api()`. Mutation vars are `{ id: number; force?: boolean }` and the body is `{ force }`. `pluginHeadersFrom`/`requestHeadersFrom` return `Record<string, string>`, and `LoaderDeps.fetchApi`/`makeSidecarHandler` take that as the 4th argument. `WriteActor` is defined once in `shared/types.ts`.
- **Review Focus.** All five lines are pinned by named tests in their owning tasks.

## Decisions on ambiguities (resolved in this plan)

1. **Who gets a row:** every write by an actor other than `user`/`restore`, except worker creates (ingest). The jot router (`worker:jot-router`) re-filing and manual-review stamps are listed, because they are an LLM job modifying the user's notes.
2. **Revert/undo write as `restore`,** not `user`. That way the replaced version is always snapshotted (user writes coalesce within 5 minutes) and a history failure refuses the revert. Both produce no change row, which matches "recorded as a user write". Only the user may revert or undo (403).
3. **`base_etag` required** for assistant, mcp and plugin edits, deletes and moves. The implicit base is "your own last write, untouched". User writes stay optional. Fails closed (428).
4. **Undo of a revert** is a separate route (`POST /v1/changes/{id}/undo`); it isn't in the spec. The row flips `reverted` → `applied`.
5. **Detail returns full before/after/current texts plus a `difflib` unified diff.** The renderer diffs with `LineDiffView`, because the forwarder only passes `detail` strings on errors. After a 409 the client fetches the detail route to show the drift.
6. **The degraded marker** is a state-dir file, dismissable from the screen.
7. **`write()` gains `verbatim`** and moves may carry `content`, both for byte-exact revert of moves and of notes without a trailing newline.
8. **The docs library (#144)** is not attributed (see Global Constraints).
