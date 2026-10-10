"""SQLite store: the append-only event log (the source of truth for gold) plus
working state (identities, bindings, extractions, candidates, backlog items).

Gold is always reconstructible from `log` alone; every other table is
convenience state for the pipeline and the backlog.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid as uuidlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ghostbrain.ontology.schema import EVENT_TYPES

_SCHEMA = """
CREATE TABLE IF NOT EXISTS log(
  seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, type TEXT NOT NULL,
  payload TEXT NOT NULL, actor TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS log_no_update BEFORE UPDATE ON log
  BEGIN SELECT RAISE(ABORT, 'log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS log_no_delete BEFORE DELETE ON log
  BEGIN SELECT RAISE(ABORT, 'log is append-only'); END;
CREATE TABLE IF NOT EXISTS identities(
  uuid TEXT PRIMARY KEY, kind TEXT NOT NULL, key TEXT NOT NULL, name TEXT NOT NULL,
  UNIQUE(kind, key));
CREATE TABLE IF NOT EXISTS projects_enabled(
  project_uuid TEXT PRIMARY KEY, seeds TEXT NOT NULL, enabled_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bindings(
  project_uuid TEXT NOT NULL, aid TEXT NOT NULL, path TEXT NOT NULL, title TEXT NOT NULL,
  status TEXT NOT NULL, PRIMARY KEY(project_uuid, aid));
CREATE TABLE IF NOT EXISTS extractions(
  project_uuid TEXT NOT NULL, aid TEXT NOT NULL, content_hash TEXT NOT NULL,
  extractor_version TEXT NOT NULL, status TEXT NOT NULL, error TEXT, ts TEXT NOT NULL,
  PRIMARY KEY(project_uuid, aid, content_hash, extractor_version));
CREATE TABLE IF NOT EXISTS candidates(
  id INTEGER PRIMARY KEY AUTOINCREMENT, project_uuid TEXT NOT NULL, kind TEXT NOT NULL,
  name TEXT NOT NULL, statement TEXT NOT NULL, value TEXT, existing_uid TEXT,
  relations TEXT NOT NULL DEFAULT '[]', confidence REAL NOT NULL,
  extractor_version TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
  embedding BLOB, created TEXT NOT NULL, updated TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS evidence(
  id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id INTEGER NOT NULL,
  aid TEXT NOT NULL, quote TEXT NOT NULL, locator TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS items(
  id INTEGER PRIMARY KEY AUTOINCREMENT, project_uuid TEXT NOT NULL, type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open', candidate_id INTEGER,
  payload TEXT NOT NULL DEFAULT '{}', created TEXT NOT NULL,
  resolved_at TEXT, resolution TEXT);
CREATE TABLE IF NOT EXISTS topics(
  uid TEXT PRIMARY KEY, project_uuid TEXT NOT NULL, name TEXT NOT NULL, norm TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', created TEXT NOT NULL, UNIQUE(project_uuid, norm));
CREATE TABLE IF NOT EXISTS note_topics(
  project_uuid TEXT NOT NULL, aid TEXT NOT NULL, topic_uid TEXT NOT NULL,
  PRIMARY KEY(project_uuid, aid));
"""
_WS_RE = re.compile(r"\s+")
_STATUS_ORDER = {"in": 0, "pending": 1, "out": 2}


def norm_topic(name: str) -> str:
    return _WS_RE.sub(" ", name).strip().casefold()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Event:
    seq: int
    ts: str
    type: str
    payload: dict
    actor: str


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA)
        self._lock = threading.RLock()
        cols = {r[1] for r in self._db.execute("PRAGMA table_info(candidates)")}
        if "topic_uid" not in cols:
            self._db.execute("ALTER TABLE candidates ADD COLUMN topic_uid TEXT")

    def close(self) -> None:
        self._db.close()

    def _rows(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._db.execute(sql, args).fetchall()]

    # -- log ---------------------------------------------------------------
    def append_event(self, type: str, payload: dict, actor: str = "user") -> int:
        if type not in EVENT_TYPES:
            raise ValueError(f"unknown event type: {type!r}")
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO log(ts, type, payload, actor) VALUES (?, ?, ?, ?)",
                (_now(), type, json.dumps(payload, sort_keys=True), actor),
            )
            return int(cur.lastrowid)

    def events(self, after: int = 0) -> list[Event]:
        return [
            Event(r["seq"], r["ts"], r["type"], json.loads(r["payload"]), r["actor"])
            for r in self._rows("SELECT * FROM log WHERE seq > ? ORDER BY seq", (after,))
        ]

    def head(self) -> int:
        with self._lock:
            row = self._db.execute("SELECT COALESCE(MAX(seq), 0) FROM log").fetchone()
        return int(row[0])

    # -- identities ----------------------------------------------------------
    def ensure_identity(self, kind: str, key: str, name: str) -> str:
        with self._lock:
            row = self.identity_by_key(kind, key)
            if row:
                if row["name"] != name:
                    self._db.execute("UPDATE identities SET name=? WHERE uuid=?", (name, row["uuid"]))
                return row["uuid"]
            new = uuidlib.uuid4().hex
            self._db.execute(
                "INSERT INTO identities(uuid, kind, key, name) VALUES (?, ?, ?, ?)",
                (new, kind, key, name),
            )
            return new

    def identity_by_key(self, kind: str, key: str) -> dict | None:
        rows = self._rows("SELECT * FROM identities WHERE kind=? AND key=?", (kind, key))
        return rows[0] if rows else None

    def relabel_identity(self, uuid: str, key: str, name: str) -> None:
        with self._lock:
            self._db.execute("UPDATE identities SET key=?, name=? WHERE uuid=?", (key, name, uuid))

    # -- enabled projects ----------------------------------------------------
    def enable_project(self, project_uuid: str, seeds: list[str]) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO projects_enabled(project_uuid, seeds, enabled_at) VALUES (?, ?, ?) "
                "ON CONFLICT(project_uuid) DO UPDATE SET seeds=excluded.seeds",
                (project_uuid, json.dumps(seeds), _now()),
            )

    def enabled_projects(self) -> list[dict]:
        rows = self._rows("SELECT * FROM projects_enabled ORDER BY enabled_at")
        for r in rows:
            r["seeds"] = json.loads(r["seeds"])
        return rows

    def project_seeds(self, project_uuid: str) -> list[str] | None:
        rows = self._rows("SELECT seeds FROM projects_enabled WHERE project_uuid=?", (project_uuid,))
        return json.loads(rows[0]["seeds"]) if rows else None

    # -- bindings / extractions ---------------------------------------------
    def upsert_binding(self, project_uuid: str, aid: str, path: str, title: str, status: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO bindings(project_uuid, aid, path, title, status) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(project_uuid, aid) DO UPDATE SET path=excluded.path, "
                "title=excluded.title, status=excluded.status",
                (project_uuid, aid, path, title, status),
            )

    def bindings(self, project_uuid: str, status: str | None = None) -> list[dict]:
        if status is None:
            return self._rows("SELECT * FROM bindings WHERE project_uuid=? ORDER BY path", (project_uuid,))
        return self._rows(
            "SELECT * FROM bindings WHERE project_uuid=? AND status=? ORDER BY path",
            (project_uuid, status),
        )

    def extraction_done(self, project_uuid: str, aid: str, content_hash: str, version: str) -> bool:
        with self._lock:
            row = self._db.execute(
                "SELECT 1 FROM extractions WHERE project_uuid=? AND aid=? AND content_hash=? "
                "AND extractor_version=? AND status='ok'",
                (project_uuid, aid, content_hash, version),
            ).fetchone()
        return row is not None

    def record_extraction(self, project_uuid: str, aid: str, content_hash: str, version: str,
                          status: str, error: str | None = None) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO extractions VALUES (?, ?, ?, ?, ?, ?, ?)",
                (project_uuid, aid, content_hash, version, status, error, _now()),
            )

    # -- topics --------------------------------------------------------------
    def ensure_topic(self, project_uuid: str, name: str, *, status: str = "pending") -> dict:
        return self.ensure_topic_created(project_uuid, name, status=status)[0]

    def ensure_topic_created(self, project_uuid: str, name: str, *,
                             status: str = "pending") -> tuple[dict, bool]:
        """The topic row, and whether this call created it."""
        norm = norm_topic(name)
        with self._lock:
            rows = self._rows("SELECT * FROM topics WHERE project_uuid=? AND norm=?", (project_uuid, norm))
            if rows:
                return rows[0], False
            uid = uuidlib.uuid4().hex
            self._db.execute(
                "INSERT INTO topics(uid, project_uuid, name, norm, status, created) VALUES (?, ?, ?, ?, ?, ?)",
                (uid, project_uuid, name.strip(), norm, status, _now()),
            )
            return self._rows("SELECT * FROM topics WHERE uid=?", (uid,))[0], True

    def topic(self, uid: str) -> dict | None:
        rows = self._rows("SELECT * FROM topics WHERE uid=?", (uid,))
        return rows[0] if rows else None

    def topics(self, project_uuid: str) -> list[dict]:
        rows = self._rows("SELECT * FROM topics WHERE project_uuid=?", (project_uuid,))
        return sorted(rows, key=lambda r: (_STATUS_ORDER.get(r["status"], 9), r["created"], r["name"]))

    def set_topic_status(self, uid: str, status: str) -> None:
        with self._lock:
            self._db.execute("UPDATE topics SET status=? WHERE uid=?", (status, uid))

    def set_note_topic(self, project_uuid: str, aid: str, topic_uid: str) -> None:
        with self._lock:
            self._db.execute("INSERT INTO note_topics VALUES (?, ?, ?) ON CONFLICT(project_uuid, aid) "
                             "DO UPDATE SET topic_uid=excluded.topic_uid", (project_uuid, aid, topic_uid))

    def note_topic(self, project_uuid: str, aid: str) -> str | None:
        rows = self._rows("SELECT topic_uid FROM note_topics WHERE project_uuid=? AND aid=?", (project_uuid, aid))
        return rows[0]["topic_uid"] if rows else None

    def notes_for_topic(self, project_uuid: str, topic_uid: str) -> list[str]:
        return [r["aid"] for r in self._rows(
            "SELECT aid FROM note_topics WHERE project_uuid=? AND topic_uid=? ORDER BY aid",
            (project_uuid, topic_uid))]

    # -- candidates / evidence ----------------------------------------------
    def add_candidate(self, project_uuid: str, *, kind: str, name: str, statement: str,
                      value: str | None, existing_uid: str | None, relations: list[dict],
                      confidence: float, extractor_version: str, embedding: bytes | None,
                      topic_uid: str | None = None, status: str = "pending") -> int:
        now = _now()
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO candidates(project_uuid, kind, name, statement, value, existing_uid, "
                "relations, confidence, extractor_version, embedding, topic_uid, status, created, updated) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (project_uuid, kind, name, statement, value, existing_uid, json.dumps(relations),
                 confidence, extractor_version, embedding, topic_uid, status, now, now),
            )
            return int(cur.lastrowid)

    def _decode_candidate(self, r: dict) -> dict:
        r["relations"] = json.loads(r["relations"])
        return r

    def candidate(self, cid: int) -> dict | None:
        rows = self._rows("SELECT * FROM candidates WHERE id=?", (cid,))
        return self._decode_candidate(rows[0]) if rows else None

    def candidates(self, project_uuid: str, status: str) -> list[dict]:
        return [self._decode_candidate(r) for r in self._rows(
            "SELECT * FROM candidates WHERE project_uuid=? AND status=? ORDER BY id",
            (project_uuid, status))]

    def candidates_for_topic(self, project_uuid: str, topic_uid: str, status: str) -> list[dict]:
        return [self._decode_candidate(r) for r in self._rows(
            "SELECT * FROM candidates WHERE project_uuid=? AND topic_uid=? AND status=? ORDER BY id",
            (project_uuid, topic_uid, status))]

    def set_candidate_status(self, cid: int, status: str) -> None:
        with self._lock:
            self._db.execute("UPDATE candidates SET status=?, updated=? WHERE id=?", (status, _now(), cid))

    def set_candidate_confidence(self, cid: int, confidence: float) -> None:
        with self._lock:
            self._db.execute("UPDATE candidates SET confidence=?, updated=? WHERE id=?",
                             (confidence, _now(), cid))

    def add_evidence(self, cid: int, aid: str, quote: str, locator: str) -> None:
        with self._lock:
            self._db.execute("INSERT INTO evidence(candidate_id, aid, quote, locator) VALUES (?, ?, ?, ?)",
                             (cid, aid, quote, locator))

    def evidence(self, cid: int) -> list[dict]:
        return self._rows("SELECT aid, quote, locator FROM evidence WHERE candidate_id=? ORDER BY id", (cid,))

    # -- items ---------------------------------------------------------------
    def add_item(self, project_uuid: str, type: str, *, candidate_id: int | None = None,
                 payload: dict | None = None) -> int:
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO items(project_uuid, type, candidate_id, payload, created) VALUES (?, ?, ?, ?, ?)",
                (project_uuid, type, candidate_id, json.dumps(payload or {}), _now()),
            )
            return int(cur.lastrowid)

    def _decode_item(self, r: dict) -> dict:
        r["payload"] = json.loads(r["payload"])
        return r

    def item(self, item_id: int) -> dict | None:
        rows = self._rows("SELECT * FROM items WHERE id=?", (item_id,))
        return self._decode_item(rows[0]) if rows else None

    def open_items(self, project_uuid: str) -> list[dict]:
        return [self._decode_item(r) for r in self._rows(
            "SELECT * FROM items WHERE project_uuid=? AND status='open' ORDER BY id", (project_uuid,))]

    def scope_items(self, project_uuid: str, topic_uid: str,
                    statuses: tuple[str, ...] = ("open", "parked")) -> list[dict]:
        marks = ", ".join("?" for _ in statuses)
        rows = self._rows(
            "SELECT * FROM items WHERE project_uuid=? AND type='scope' "
            f"AND status IN ({marks}) ORDER BY id", (project_uuid, *statuses))
        items = [self._decode_item(r) for r in rows]
        return [it for it in items if it["payload"].get("topic_uid") == topic_uid]

    def open_scope_item(self, project_uuid: str, topic_uid: str, *,
                        include_parked: bool = True) -> dict | None:
        """The live scope item for a topic: open, or parked by investigate (still undecided)."""
        statuses = ("open", "parked") if include_parked else ("open",)
        items = self.scope_items(project_uuid, topic_uid, statuses)
        return items[0] if items else None

    def update_item_payload(self, item_id: int, payload: dict) -> None:
        with self._lock:
            self._db.execute("UPDATE items SET payload=? WHERE id=?", (json.dumps(payload), item_id))

    def reopen_item(self, item_id: int) -> None:
        """Undo a claim made by resolve_item when the log append that should follow it failed."""
        with self._lock:
            self._db.execute(
                "UPDATE items SET status='open', resolution=NULL, resolved_at=NULL WHERE id=?",
                (item_id,),
            )

    def close_item(self, item_id: int, resolution: str) -> bool:
        """Resolve an open or parked item that a decision elsewhere made moot."""
        with self._lock:
            cur = self._db.execute(
                "UPDATE items SET status='resolved', resolution=?, resolved_at=? "
                "WHERE id=? AND status IN ('open', 'parked')",
                (resolution, _now(), item_id),
            )
            return cur.rowcount == 1

    def resolve_item(self, item_id: int, resolution: str, status: str = "resolved") -> bool:
        with self._lock:
            cur = self._db.execute(
                "UPDATE items SET status=?, resolution=?, resolved_at=? WHERE id=? AND status='open'",
                (status, resolution, _now(), item_id),
            )
            return cur.rowcount == 1
