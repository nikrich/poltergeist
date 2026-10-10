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
MAX_OWNERSHIP_HOPS = 50

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
CREATE INDEX IF NOT EXISTS changes_dest_path ON changes(dest_path);
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


def created_by(path: str, actor: str) -> bool:
    """Spec B §3 ownership: did ``actor`` create the file now at ``path``?
    Walks back in time: the newest applied row that put a file at the path
    must be ``actor``'s create, or ``actor``'s move from a path it owned at
    that moment, and nothing may have deleted or moved the file away since.
    Moving someone else's note never makes it yours. Fails closed."""
    current = path
    bound: int | None = None  # the hop must predate this row id
    with _connect() as conn:
        for _ in range(MAX_OWNERSHIP_HOPS):
            before = "" if bound is None else " AND id < ?"
            limit = () if bound is None else (bound,)
            placed = conn.execute(
                "SELECT id, actor, op, rel_path FROM changes WHERE status = 'applied'"
                " AND ((op = 'create' AND rel_path = ?) OR (op = 'move' AND dest_path = ?))"
                + before + " ORDER BY id DESC LIMIT 1",
                (current, current, *limit),
            ).fetchone()
            if placed is None or placed["actor"] != actor:
                return False
            vacated = conn.execute(
                "SELECT 1 FROM changes WHERE status = 'applied'"
                " AND op IN ('delete', 'move') AND rel_path = ? AND id > ?"
                + before + " LIMIT 1",
                (current, placed["id"], *limit),
            ).fetchone()
            if vacated is not None:
                return False
            if placed["op"] == "create":
                return True
            current, bound = placed["rel_path"], int(placed["id"])
    return False


def apply_pending(change_id: int, *, before_blob: str | None, after_blob: str | None) -> bool:
    """B3: an approved change. The pending row becomes the applied row."""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE changes SET status = 'applied', before_blob = ?, after_blob = ?,"
            " resolved_ts = NULL WHERE id = ? AND status = 'pending'",
            (before_blob, after_blob, change_id),
        )
        return cur.rowcount == 1


def referenced_blobs() -> list[str]:
    """A3 calls this while holding the history lock, so it is a plain
    read-only query: its own ``mode=ro`` connection, no schema DDL or PRAGMA,
    and no DB file is created. Any failure raises, so A3 skips blob GC."""
    try:
        path = db_path()
        if not path.exists():
            return []
        conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=5.0)
    except (OSError, sqlite3.Error) as e:
        raise ChangeLogError(f"change log unavailable: {e}") from e
    try:
        rows = conn.execute(
            "SELECT before_blob, after_blob, pending_bytes_blob FROM changes"
        ).fetchall()
    except sqlite3.Error as e:
        raise ChangeLogError(f"change log unavailable: {e}") from e
    finally:
        conn.close()
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
