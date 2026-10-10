# Ontology M1 — Walking Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ratified knowledge for one project can be viewed in Poltergeist's own graph view in a dev build, linked back to the notes that evidence it. The loop: scoping → bulk binding → LLM extraction → triage → plain backlog → ratify → ArcadeDB gold graph → Ontology screen.

**Architecture:**
- **Python.** A new package `ghostbrain/ontology/` sits behind a new `/v1/ontology` router.
  - SQLite (`ontology.db`) holds the append-only event log (the source of truth for gold) plus working state: candidates, evidence, bindings, backlog items.
  - An embedded ArcadeDB graph holds gold. A projector builds it from the log, and it can be rebuilt from the log at any time.
  - Gold is also written out as markdown into the vault.
- **Desktop.** A new Ontology screen. Its Backlog tab is a plain list; its Graph tab reuses the A6 `GraphCanvas` and `layoutEgo`, with the kind union widened.

**Tech Stack:**
- Python 3.11, FastAPI, sqlite3 (stdlib), `arcadedb-embedded` 26.10.x (JPype + bundled JRE, Cypher), `python-frontmatter`, the existing `ghostbrain.llm.client.run`, the existing MiniLM embedder.
- Electron + React 18, React Query v5, Zustand, d3-force (existing), Vitest.

**Spec:** `docs/superpowers/specs/2026-10-10-ontology-ratification-design.md`. This plan implements **Milestone 1** only.

## Global Constraints

- **Repo is public.** Never write the banned legacy context names in code, tests, docs or commit messages. Run `.venv/bin/python -m pytest tests/test_no_hardcoded_contexts.py -q` before every commit, and keep commit messages to generic wording. Use `work` / `personal` in examples. The guard test also covers the external knowledge-system brief's company name, so never write that name either.
- **Python:** `requires-python >=3.11`. New dependency is `arcadedb-embedded>=26.10.1,<27` under a new `ontology` extra.
- **Ontology data dir:** env `GHOSTBRAIN_ONTOLOGY_DIR`, default `~/ghostbrain/ontology`. It contains `ontology.db` and `gold/`.
- **JVM heap:** env `GHOSTBRAIN_ONTOLOGY_HEAP`, default `512m`. The JVM starts lazily, on first ontology use, never at sidecar start.
- **ArcadeDB embedded takes an exclusive per-process lock.** Only the sidecar process opens the graph. Everything else goes through HTTP.
- **Cypher rules** (verified in the spike):
  - Match nodes with `WHERE n.uid = $x`, never `MATCH (n {uid:$x})` without a label (that silently matches nothing).
  - Upsert with a labelled `MERGE (n:Label {uid:$uid})`.
  - Pass parameters as a single dict.
  - Labels and edge types interpolated into Cypher must come from the `schema.py` allowlists.
  - Property names interpolated into Cypher must match `^[a-z_][a-z0-9_]*$`.
- **Gold-only reads** go through `db.query()`, which rejects non-idempotent statements.
- **Nothing in the ontology is keyed by a human-readable name or path.**
  - Contexts are keyed by an `identities` uuid; projects by a `uuid` field in `projects.json`.
  - Artefacts are keyed by frontmatter `id`, else `doc_id`, else the file stem.
- **Generated ontology notes** (`type: ontology`, under `.../projects/<slug>/ontology/`) must never be scoped or extracted as artefacts.
- **LLM calls** go through `ghostbrain.llm.client.run`, always with an explicit `budget_usd`. The default $0.50 cap is too low for long notes.
- **Backend tests** live in `ghostbrain/api/tests/test_ontology_*.py`, a directory CI runs wholesale. Graph-touching tests start with `pytest.importorskip("arcadedb_embedded")`.
- **Desktop:** run `npm run typecheck` (not `tsc --noEmit`), `npm run lint` and `npm test` from `desktop/`.
- **Commits** end with:
  ```
  Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
  ```

## Review Focus

1. **Generated ontology notes get re-ingested.** After a ratify, the projection writes `type: ontology` notes into the vault. Re-running scoping must not propose them as artefacts. Pinned in Task 7.
2. **Graph locked by another process** (a stray dev sidecar). The Ontology screen shows "locked by another process" and every non-ontology route keeps working. Pinned in Task 6.
3. **A source note is moved or deleted** between binding and extraction. That artefact is recorded `failed` ("source missing") and the run continues. Pinned in Task 10.
4. **The LLM's quote differs only in whitespace, case or curly vs straight quotes.** Accepted. A paraphrased quote is discarded. Pinned in Task 8.
5. **The same backlog item is ratified twice** (double click, two windows). The second call returns 409, and exactly one `ratify` event is in the log. Pinned in Task 11.

---

## File Structure

**Backend — create:**
- `ghostbrain/ontology/__init__.py`: package docstring.
- `ghostbrain/ontology/schema.py`: vertex/edge/kind allowlists, event types, UI kind mapping.
- `ghostbrain/ontology/store.py`: SQLite store (log, identities, enabled projects, bindings, extractions, candidates, evidence, items).
- `ghostbrain/ontology/identity.py`: stable uuids for Self, contexts and projects; builds the `seed` event payload.
- `ghostbrain/ontology/graph.py`: the `GoldGraph` ArcadeDB adapter (JVM, schema, upserts, reads).
- `ghostbrain/ontology/projector.py`: applies log events to the graph; `catch_up` and `rebuild`.
- `ghostbrain/ontology/service.py`: the process-wide `OntologyService` (store, graph session, commit, status, extraction runner).
- `ghostbrain/ontology/scope.py`: artefact keys, candidate artefact discovery, bulk binding item.
- `ghostbrain/ontology/prompts.py`: the extraction prompt template.
- `ghostbrain/ontology/extract.py`: chunking, LLM call, validation (the quote must exist).
- `ghostbrain/ontology/triage.py`: embedder seam, merge duplicates, drop near-rejected.
- `ghostbrain/ontology/pipeline.py`: `run_extraction` over bound artefacts.
- `ghostbrain/ontology/backlog.py`: listing items and applying actions.
- `ghostbrain/ontology/projection_md.py`: writes gold out as vault markdown.
- `ghostbrain/ontology/selfcheck.py`: the frozen-build self-test subcommand.
- `ghostbrain/api/models/ontology.py`: request/response models.
- `ghostbrain/api/routes/ontology.py`: `/v1/ontology` router.
- `scripts/prune-arcadedb.py`: post-PyInstaller jar prune and lz4 native strip.
- Tests, all under `ghostbrain/api/tests/`:
  - `test_ontology_schema.py`, `test_ontology_store.py`, `test_ontology_identity.py`
  - `test_ontology_graph.py`, `test_ontology_projector.py`, `test_ontology_service.py`
  - `test_ontology_scope.py`, `test_ontology_extract.py`, `test_ontology_triage.py`
  - `test_ontology_pipeline.py`, `test_ontology_backlog.py`, `test_ontology_projection.py`
  - `test_ontology_routes.py`, `test_ontology_packaging.py`

**Backend — modify:**
- `ghostbrain/paths.py`: add `ontology_dir()`.
- `ghostbrain/api/repo/projects.py`: `uuid` on create, `ensure_project_uuids()`, `get_project_by_uuid()`.
- `ghostbrain/api/models/project.py`: optional `uuid`.
- `ghostbrain/api/main.py`: register the ontology router.
- `ghostbrain/api/__main__.py` and `pyproject.toml`: the `ontology-selfcheck` subcommand plus the `ontology` extra.
- `ghostbrain/api/tests/conftest.py`: `ontology_root` fixture.
- `packaging/sidecar.spec`: arcadedb datas and hidden imports.
- `scripts/smoke-sidecar.py`: ontology self-check step.
- `.github/workflows/ci.yml` and `.github/workflows/release.yml`: install the `ontology` extra; prune step.

**Desktop — create:**
- `desktop/src/renderer/lib/api/ontology-hooks.ts`: React Query hooks.
- `desktop/src/renderer/stores/ontology-view.ts`: screen UI state.
- `desktop/src/renderer/components/OntologyGraph.tsx`: graph tab.
- `desktop/src/renderer/components/OntologyBacklog.tsx`: backlog tab.
- `desktop/src/renderer/screens/ontology.tsx`: screen shell (status, project picker, enable form, tabs).
- Tests: `desktop/src/renderer/__tests__/OntologyScreen.test.tsx` and `ontology-graph-layout.test.ts`.

**Desktop — modify:**
- `desktop/src/shared/api-types.ts`: `OntologyKind`, `GraphKind`, ontology types.
- `desktop/src/renderer/lib/graph/kinds.ts`, `layout.ts`, `draw.ts`, `components/GraphCanvas.tsx`: `NoteKind` → `GraphKind` where the canvas is concerned.
- `desktop/colors_and_type.css`: `--kind-*` tokens for the ontology kinds.
- `desktop/src/renderer/__tests__/graph-kinds.test.ts`: cover the ontology kinds.
- `desktop/src/renderer/stores/navigation.ts`, `components/Sidebar.tsx`, `App.tsx`: the `ontology` screen.

---

### Task 1: Foundations — data dir, dependency, schema allowlists

**Files:**
- Modify: `ghostbrain/paths.py`, `pyproject.toml`, `.github/workflows/ci.yml:18`
- Create: `ghostbrain/ontology/__init__.py`, `ghostbrain/ontology/schema.py`
- Test: `ghostbrain/api/tests/test_ontology_schema.py`

**Interfaces:**
- Produces:
  - `ghostbrain.paths.ontology_dir() -> Path`
  - `schema.CORE_KINDS`, `DOMAIN_KINDS`, `VERTEX_TYPES`, `EDGE_TYPES`, `RELATION_TYPES`, `PROVENANCE`, `EVENT_TYPES` (all `tuple[str, ...]`)
  - `schema.SELF_UID = "self"`, `schema.META_UID = "meta"`
  - `schema.ui_kind(kind: str) -> str`
  - `schema.check_kind(kind) -> str`, `schema.check_edge(etype) -> str`, `schema.check_prop(name) -> str` (each raises `ValueError`)

- [ ] **Step 1: Set up the worktree venv** (once)

From the worktree root:

```bash
uv venv -q -p python3.11 .venv
uv pip install -q -p .venv/bin/python -e ".[dev,api]"
```

- [ ] **Step 2: Write the failing tests**

`ghostbrain/api/tests/test_ontology_schema.py`:
```python
from pathlib import Path

import pytest

from ghostbrain import paths
from ghostbrain.ontology import schema


def test_ontology_dir_default_under_home(monkeypatch, tmp_path):
    monkeypatch.delenv("GHOSTBRAIN_ONTOLOGY_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert paths.ontology_dir() == tmp_path / "ghostbrain" / "ontology"


def test_ontology_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("GHOSTBRAIN_ONTOLOGY_DIR", str(tmp_path / "x"))
    assert paths.ontology_dir() == tmp_path / "x"


def test_allowlists_are_disjoint_and_complete():
    assert not set(schema.CORE_KINDS) & set(schema.DOMAIN_KINDS)
    assert set(schema.RELATION_TYPES) <= set(schema.EDGE_TYPES)
    assert "Meta" in schema.VERTEX_TYPES
    assert {"PART_OF", "EVIDENCED_BY", "ABOUT", "IN", "WORKS_IN"} <= set(schema.EDGE_TYPES)


def test_ui_kind_covers_every_non_meta_vertex():
    for kind in schema.VERTEX_TYPES:
        if kind == "Meta":
            continue
        assert schema.ui_kind(kind).islower()
    assert schema.ui_kind("OpenQuestion") == "question"


@pytest.mark.parametrize("bad", ["Rule) DETACH DELETE (n", "", "rule"])
def test_check_kind_rejects_unknown(bad):
    with pytest.raises(ValueError):
        schema.check_kind(bad)


@pytest.mark.parametrize("bad", ["Name", "a-b", "x; MATCH", "1abc", ""])
def test_check_prop_rejects_non_identifiers(bad):
    with pytest.raises(ValueError):
        schema.check_prop(bad)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest ghostbrain/api/tests/test_ontology_schema.py -q`
Expected: FAIL. `ImportError: cannot import name 'schema'` / no attribute `ontology_dir`.

- [ ] **Step 4: Implement**

Append to `ghostbrain/paths.py` (it already imports `os` and `Path`):
```python
def ontology_dir() -> Path:
    """Ontology data: the SQLite log/working state and the ArcadeDB gold graph."""
    env = os.environ.get("GHOSTBRAIN_ONTOLOGY_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / "ghostbrain" / "ontology"
```

`ghostbrain/ontology/__init__.py`:
```python
"""Project ontologies: observed candidates, a ratification log, and the gold graph."""
```

`ghostbrain/ontology/schema.py`:
```python
"""Allowlists for the gold graph. Anything interpolated into Cypher comes from here."""
from __future__ import annotations

import re

CORE_KINDS: tuple[str, ...] = ("Self", "Context", "Project", "Artefact")
DOMAIN_KINDS: tuple[str, ...] = (
    "Concept", "Rule", "Decision", "Requirement", "System", "Role", "OpenQuestion",
)
VERTEX_TYPES: tuple[str, ...] = CORE_KINDS + DOMAIN_KINDS + ("Meta",)

BINDING_EDGES: tuple[str, ...] = ("WORKS_IN", "IN", "ABOUT", "RECORDED_IN")
DOMAIN_EDGES: tuple[str, ...] = (
    "PART_OF", "DEFINES", "CONSTRAINS", "DEPENDS_ON", "SUPERSEDES",
    "SAME_AS", "SCOPED_EXCEPTION", "EVIDENCED_BY",
)
EDGE_TYPES: tuple[str, ...] = BINDING_EDGES + DOMAIN_EDGES
# Relations the extractor may propose between domain nodes.
RELATION_TYPES: tuple[str, ...] = ("DEFINES", "CONSTRAINS", "DEPENDS_ON", "SUPERSEDES")

PROVENANCE: tuple[str, ...] = ("observed", "extracted", "answered", "seeded")
EVENT_TYPES: tuple[str, ...] = (
    "seed", "bind", "ratify", "reject", "by_design", "investigate", "revert", "relabel",
)

SELF_UID = "self"
META_UID = "meta"

_UI_KIND = {"OpenQuestion": "question"}
_PROP_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


def ui_kind(kind: str) -> str:
    """The lowercase kind the desktop graph colours by."""
    return _UI_KIND.get(kind, kind.lower())


def check_kind(kind: str) -> str:
    if kind not in VERTEX_TYPES:
        raise ValueError(f"unknown vertex type: {kind!r}")
    return kind


def check_edge(etype: str) -> str:
    if etype not in EDGE_TYPES:
        raise ValueError(f"unknown edge type: {etype!r}")
    return etype


def check_prop(name: str) -> str:
    if not _PROP_RE.match(name):
        raise ValueError(f"invalid property name: {name!r}")
    return name
```

`pyproject.toml`: add to `[project.optional-dependencies]`, after `mcp = [...]`:
```toml
ontology = [
    # Gold graph: embedded ArcadeDB (Cypher + vectors) with a bundled JRE.
    # Validated frozen on macOS arm64, Windows and Linux in the 2026-10-10 spike.
    "arcadedb-embedded>=26.10.1,<27",
]
```

`.github/workflows/ci.yml:18`: change `pip install -e ".[dev,api]"` to `pip install -e ".[dev,api,ontology]"`.

- [ ] **Step 5: Install the extra and run the tests to verify they pass**

```bash
uv pip install -q -p .venv/bin/python -e ".[dev,api,ontology]"
.venv/bin/python -m pytest ghostbrain/api/tests/test_ontology_schema.py -q
```
Expected: PASS (11 tests).

- [ ] **Step 6: Commit**

```bash
git add ghostbrain/paths.py ghostbrain/ontology pyproject.toml .github/workflows/ci.yml ghostbrain/api/tests/test_ontology_schema.py
git commit -m "feat(ontology): data dir, ontology extra, schema allowlists"
```

---

### Task 2: SQLite store

**Files:**
- Create: `ghostbrain/ontology/store.py`
- Test: `ghostbrain/api/tests/test_ontology_store.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - **Core:** `Event` (dataclass: `seq: int, ts: str, type: str, payload: dict, actor: str`); `Store(path: Path)` with `.close()`.
  - **Log:**
    - `append_event(type: str, payload: dict, actor: str = "user") -> int` (returns seq)
    - `events(after: int = 0) -> list[Event]`
    - `head() -> int`
  - **Identities:**
    - `ensure_identity(kind: str, key: str, name: str) -> str` (uuid; creates if missing, refreshes the name)
    - `identity_by_key(kind, key) -> dict | None`
    - `relabel_identity(uuid: str, key: str, name: str) -> None`
  - **Enabled projects:**
    - `enable_project(project_uuid: str, seeds: list[str]) -> None`
    - `enabled_projects() -> list[dict]` (`project_uuid`, `seeds: list[str]`, `enabled_at`)
    - `project_seeds(project_uuid) -> list[str] | None`
  - **Bindings:**
    - `upsert_binding(project_uuid, aid, path, title, status) -> None` (status `bound|excluded|proposed`)
    - `bindings(project_uuid, status: str | None = None) -> list[dict]`
  - **Extractions:**
    - `extraction_done(project_uuid, aid, content_hash, version) -> bool`
    - `record_extraction(project_uuid, aid, content_hash, version, status, error=None) -> None`
  - **Candidates:**
    - `add_candidate(project_uuid, *, kind, name, statement, value, existing_uid, relations: list[dict], confidence: float, extractor_version: str, embedding: bytes | None) -> int`
    - `candidate(cid) -> dict | None` (`relations` decoded)
    - `candidates(project_uuid, status: str) -> list[dict]`
    - `set_candidate_status(cid, status) -> None`
    - `set_candidate_confidence(cid, confidence) -> None`
  - **Evidence:**
    - `add_evidence(cid, aid, quote, locator) -> None`
    - `evidence(cid) -> list[dict]`
  - **Items:**
    - `add_item(project_uuid, type, *, candidate_id: int | None = None, payload: dict | None = None) -> int`
    - `item(item_id) -> dict | None` (payload decoded)
    - `open_items(project_uuid) -> list[dict]`
    - `resolve_item(item_id, resolution: str, status: str = "resolved") -> bool`. Returns False if the item was not `open`; that is the double-ratify guard.

- [ ] **Step 1: Write the failing tests**

`ghostbrain/api/tests/test_ontology_store.py`:
```python
import sqlite3

import pytest

from ghostbrain.ontology.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "ontology.db")
    yield s
    s.close()


def test_log_appends_monotonic_and_reads_back(store):
    a = store.append_event("seed", {"nodes": []})
    b = store.append_event("bind", {"project": "p"}, actor="system")
    assert b == a + 1
    evs = store.events()
    assert [(e.seq, e.type, e.actor) for e in evs] == [(a, "seed", "user"), (b, "bind", "system")]
    assert evs[1].payload == {"project": "p"}
    assert [e.seq for e in store.events(after=a)] == [b]
    assert store.head() == b


def test_log_is_append_only(store):
    store.append_event("seed", {})
    with pytest.raises(sqlite3.DatabaseError):
        store._db.execute("UPDATE log SET type = 'x'")
    with pytest.raises(sqlite3.DatabaseError):
        store._db.execute("DELETE FROM log")


def test_unknown_event_type_rejected(store):
    with pytest.raises(ValueError):
        store.append_event("nope", {})


def test_identity_is_stable_and_relabels(store):
    u = store.ensure_identity("context", "work", "work")
    assert store.ensure_identity("context", "work", "work") == u
    store.relabel_identity(u, "job", "job")
    assert store.identity_by_key("context", "job")["uuid"] == u
    assert store.identity_by_key("context", "work") is None


def test_candidates_evidence_and_items(store):
    cid = store.add_candidate(
        "p1", kind="Rule", name="lapse day", statement="Policies lapse on day 31.",
        value="31", existing_uid=None, relations=[{"type": "DEFINES", "target_uid": "x"}],
        confidence=0.7, extractor_version="v1", embedding=b"\x00\x00\x80?",
    )
    store.add_evidence(cid, "a1", "lapse on day 31", "## Rules")
    c = store.candidate(cid)
    assert c["status"] == "pending" and c["relations"][0]["type"] == "DEFINES"
    assert store.evidence(cid) == [{"aid": "a1", "quote": "lapse on day 31", "locator": "## Rules"}]
    item = store.add_item("p1", "candidate", candidate_id=cid)
    assert [i["id"] for i in store.open_items("p1")] == [item]
    assert store.resolve_item(item, "ratified") is True
    assert store.resolve_item(item, "ratified") is False  # double-ratify guard
    assert store.open_items("p1") == []


def test_extraction_idempotency_key(store):
    assert not store.extraction_done("p", "a", "h", "v1")
    store.record_extraction("p", "a", "h", "v1", "ok")
    assert store.extraction_done("p", "a", "h", "v1")
    assert not store.extraction_done("p", "a", "h", "v2")


def test_bindings_and_enabled_projects(store):
    store.enable_project("p1", ["Orbit", "lapse"])
    assert store.project_seeds("p1") == ["Orbit", "lapse"]
    store.upsert_binding("p1", "a1", "20-contexts/work/x.md", "X", "proposed")
    store.upsert_binding("p1", "a1", "20-contexts/work/x.md", "X", "bound")
    assert [b["status"] for b in store.bindings("p1")] == ["bound"]
    assert store.bindings("p1", "excluded") == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest ghostbrain/api/tests/test_ontology_store.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.ontology.store'`.

- [ ] **Step 3: Implement**

`ghostbrain/ontology/store.py`:
```python
"""SQLite store: the append-only event log (the source of truth for gold) plus
working state (identities, bindings, extractions, candidates, backlog items).

Gold is always reconstructible from `log` alone; every other table is
convenience state for the pipeline and the backlog.
"""
from __future__ import annotations

import json
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
"""


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

    def close(self) -> None:
        self._db.close()

    def _rows(self, sql: str, args: tuple = ()) -> list[dict]:
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

    # -- candidates / evidence ----------------------------------------------
    def add_candidate(self, project_uuid: str, *, kind: str, name: str, statement: str,
                      value: str | None, existing_uid: str | None, relations: list[dict],
                      confidence: float, extractor_version: str, embedding: bytes | None) -> int:
        now = _now()
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO candidates(project_uuid, kind, name, statement, value, existing_uid, "
                "relations, confidence, extractor_version, embedding, created, updated) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (project_uuid, kind, name, statement, value, existing_uid, json.dumps(relations),
                 confidence, extractor_version, embedding, now, now),
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

    def resolve_item(self, item_id: int, resolution: str, status: str = "resolved") -> bool:
        with self._lock:
            cur = self._db.execute(
                "UPDATE items SET status=?, resolution=?, resolved_at=? WHERE id=? AND status='open'",
                (status, resolution, _now(), item_id),
            )
            return cur.rowcount == 1
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest ghostbrain/api/tests/test_ontology_store.py -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/ontology/store.py ghostbrain/api/tests/test_ontology_store.py
git commit -m "feat(ontology): SQLite store with append-only event log"
```

---

### Task 3: Stable identities and the seed payload

**Files:**
- Modify: `ghostbrain/api/repo/projects.py` (`create_project` at line 108; add two functions after `list_projects`), `ghostbrain/api/models/project.py`
- Create: `ghostbrain/ontology/identity.py`
- Test: `ghostbrain/api/tests/test_ontology_identity.py`

**Interfaces:**
- Consumes: `Store.ensure_identity`; `schema.SELF_UID`.
- Produces:
  - `projects.ensure_project_uuids() -> list[dict]` (every entry has `uuid`)
  - `projects.get_project_by_uuid(uuid: str) -> dict | None`
  - `identity.context_uuid(store, name: str) -> str`
  - `identity.seed_payload(store) -> dict`, with shape `{"nodes": [{"uid","kind","props"}], "edges": [{"type","src","dst","props"}]}`

- [ ] **Step 1: Write the failing tests**

`ghostbrain/api/tests/test_ontology_identity.py`:
```python
from ghostbrain.api.repo import projects
from ghostbrain.ontology import identity
from ghostbrain.ontology.schema import SELF_UID
from ghostbrain.ontology.store import Store


def test_create_project_assigns_uuid(tmp_vault):
    p = projects.create_project("work", "Orbit")
    assert len(p["uuid"]) == 32


def test_ensure_project_uuids_backfills_and_is_stable(tmp_vault):
    p = projects.create_project("work", "Orbit")
    items = projects._read()
    items[0].pop("uuid")
    projects._write(items)
    first = projects.ensure_project_uuids()
    second = projects.ensure_project_uuids()
    assert first[0]["uuid"] == second[0]["uuid"]
    assert projects.get_project_by_uuid(first[0]["uuid"])["id"] == p["id"]


def test_rename_keeps_uuid(tmp_vault):
    p = projects.create_project("work", "Orbit")
    projects.rename_project("work", p["slug"], name="Orbit Programme")
    renamed = projects.get_project_by_uuid(p["uuid"])
    assert renamed is not None and renamed["name"] == "Orbit Programme"


def test_seed_payload_has_self_contexts_projects(tmp_vault, tmp_path):
    store = Store(tmp_path / "o.db")
    p = projects.create_project("work", "Orbit")
    payload = identity.seed_payload(store)
    uids = {n["uid"]: n for n in payload["nodes"]}
    assert uids[SELF_UID]["kind"] == "Self"
    work = identity.context_uuid(store, "work")
    assert uids[work]["kind"] == "Context" and uids[work]["props"]["name"] == "work"
    assert uids[p["uuid"]]["kind"] == "Project"
    assert {"type": "IN", "src": p["uuid"], "dst": work, "props": {}} in payload["edges"]
    assert {"type": "WORKS_IN", "src": SELF_UID, "dst": work, "props": {}} in payload["edges"]
    # stable across calls
    assert identity.seed_payload(store) == payload
```

Check `rename_project`'s keyword names at `projects.py:314` before running. If the new-name keyword differs from `name=`, adjust the call in `test_rename_keeps_uuid` to match it.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest ghostbrain/api/tests/test_ontology_identity.py -q`
Expected: FAIL with `KeyError: 'uuid'` / `ModuleNotFoundError: ...identity`.

- [ ] **Step 3: Implement**

In `ghostbrain/api/repo/projects.py`:
- add `import uuid` to the imports;
- in `create_project`'s `project = {...}` dict add `"uuid": uuid.uuid4().hex,` after `"created_at"`;
- add after `list_projects`:
```python
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
```

In `ghostbrain/api/models/project.py` add to `Project`: `uuid: str | None = None`.

`ghostbrain/ontology/identity.py`:
```python
"""Permanent identities for the core layer, and the `seed` event that puts
Self, contexts and projects into the gold graph."""
from __future__ import annotations

from ghostbrain import routing_config
from ghostbrain.api.repo import projects as projects_repo
from ghostbrain.ontology.schema import SELF_UID
from ghostbrain.ontology.store import Store


def context_uuid(store: Store, name: str) -> str:
    return store.ensure_identity("context", name, name)


def seed_payload(store: Store) -> dict:
    nodes: list[dict] = [{"uid": SELF_UID, "kind": "Self", "props": {"name": "me"}}]
    edges: list[dict] = []
    ctx_uids: dict[str, str] = {}
    for name in sorted(routing_config.contexts()):
        uid = context_uuid(store, name)
        ctx_uids[name] = uid
        nodes.append({"uid": uid, "kind": "Context", "props": {"name": name}})
        edges.append({"type": "WORKS_IN", "src": SELF_UID, "dst": uid, "props": {}})
    for p in sorted(projects_repo.ensure_project_uuids(), key=lambda p: p["uuid"]):
        if p.get("archived") or p["context"] not in ctx_uids:
            continue
        nodes.append({"uid": p["uuid"], "kind": "Project", "props": {"name": p["name"]}})
        edges.append({"type": "IN", "src": p["uuid"], "dst": ctx_uids[p["context"]], "props": {}})
    return {"nodes": nodes, "edges": edges}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest ghostbrain/api/tests/test_ontology_identity.py ghostbrain/api/tests -q -k "project or ontology_identity"`
Expected: PASS. The existing project tests still pass.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/repo/projects.py ghostbrain/api/models/project.py ghostbrain/ontology/identity.py ghostbrain/api/tests/test_ontology_identity.py
git commit -m "feat(ontology): permanent project/context uuids and seed payload"
```

---

### Task 4: GoldGraph — the ArcadeDB adapter

**Files:**
- Create: `ghostbrain/ontology/graph.py`
- Test: `ghostbrain/api/tests/test_ontology_graph.py`

**Interfaces:**
- Consumes: `schema.*` allowlists and checks.
- Produces:
  - **Exceptions:** `GraphUnavailable(RuntimeError)`; `GraphLocked(GraphUnavailable)`.
  - **Lifecycle:**
    - `GoldGraph(path: Path, heap: str | None = None)`
    - `.open() -> GoldGraph`, `.close()`
    - `.transaction()` (a context manager)
  - **Writes:**
    - `.upsert_node(uid: str, kind: str, props: dict) -> None`. If the uid exists under another label, the existing node is updated in place.
    - `.upsert_edge(etype: str, src: str, dst: str, props: dict) -> bool` (False if either endpoint is missing)
    - `.set_props(uid: str, props: dict) -> None`
    - `.delete_node(uid: str) -> None`
    - `.clear() -> None`
  - **Meta:** `.get_meta() -> int` and `.set_meta(seq: int) -> None` (`last_applied_seq`).
  - **Reads:**
    - `.node(uid) -> dict | None` (`uid`, `kind`, plus props)
    - `.neighbourhood(focus: str, depth: int, cap: int = 300) -> tuple[list[dict], list[dict], bool]`. Returns nodes (`uid, kind, name, note_path, hop`), edges (`src, type, dst`) and `truncated`.
    - `.domain_nodes(project_uid: str, limit: int = 500) -> list[dict]` (`uid, kind, name, statement, value, valid_from, provenance`)
    - `.project_export(project_uid) -> list[dict]`. Each domain node also carries `evidence: [{note_path, title, quote}]` and `relations: [{type, target_uid, target_name}]`.
    - `.snapshot() -> dict` (`nodes` and `edges`, sorted; used by the determinism tests)

- [ ] **Step 1: Write the failing tests**

`ghostbrain/api/tests/test_ontology_graph.py`:
```python
import pytest

pytest.importorskip("arcadedb_embedded")

from ghostbrain.ontology.graph import GoldGraph  # noqa: E402


@pytest.fixture
def graph(tmp_path):
    g = GoldGraph(tmp_path / "gold").open()
    yield g
    g.close()


def _seed(g):
    with g.transaction():
        g.upsert_node("p1", "Project", {"name": "Orbit"})
        g.upsert_node("r1", "Rule", {"name": "lapse day", "value": "31", "statement": "Lapse on day 31."})
        g.upsert_node("a1", "Artefact", {"name": "Spec", "note_path": "20-contexts/work/spec.md"})
        assert g.upsert_edge("PART_OF", "r1", "p1", {})
        assert g.upsert_edge("EVIDENCED_BY", "r1", "a1", {"quote": "day 31"})


def test_upsert_is_idempotent_and_updates(graph):
    _seed(graph)
    with graph.transaction():
        graph.upsert_node("p1", "Project", {"name": "Orbit v2"})
        graph.upsert_edge("PART_OF", "r1", "p1", {})
    snap = graph.snapshot()
    assert [n["uid"] for n in snap["nodes"]].count("p1") == 1
    assert graph.node("p1")["name"] == "Orbit v2"
    assert len([e for e in snap["edges"] if e["type"] == "PART_OF"]) == 1


def test_kind_change_keeps_single_node(graph):
    _seed(graph)
    with graph.transaction():
        graph.upsert_node("r1", "Concept", {"name": "lapse"})
    assert [n["uid"] for n in graph.snapshot()["nodes"]].count("r1") == 1


def test_edge_to_missing_node_returns_false(graph):
    _seed(graph)
    with graph.transaction():
        assert graph.upsert_edge("PART_OF", "nope", "p1", {}) is False


def test_neighbourhood_hops_and_cap(graph):
    _seed(graph)
    nodes, edges, truncated = graph.neighbourhood("p1", depth=2)
    hops = {n["uid"]: n["hop"] for n in nodes}
    assert hops == {"p1": 0, "r1": 1, "a1": 2}
    assert {"src": "r1", "type": "EVIDENCED_BY", "dst": "a1"} in edges
    assert truncated is False
    nodes, _, truncated = graph.neighbourhood("p1", depth=2, cap=2)
    assert len(nodes) == 2 and truncated is True


def test_domain_nodes_and_export(graph):
    _seed(graph)
    [n] = graph.domain_nodes("p1")
    assert (n["uid"], n["kind"], n["value"]) == ("r1", "Rule", "31")
    [x] = graph.project_export("p1")
    assert x["evidence"] == [{"note_path": "20-contexts/work/spec.md", "title": "Spec", "quote": "day 31"}]


def test_meta_and_clear_and_delete(graph):
    _seed(graph)
    with graph.transaction():
        graph.set_meta(7)
    assert graph.get_meta() == 7
    with graph.transaction():
        graph.delete_node("a1")
    assert graph.node("a1") is None
    with graph.transaction():
        graph.clear()
    assert graph.snapshot() == {"nodes": [], "edges": []}
    assert graph.get_meta() == 0


def test_rejects_unknown_kind_and_bad_prop(graph):
    with pytest.raises(ValueError):
        with graph.transaction():
            graph.upsert_node("x", "Bogus", {})
    with pytest.raises(ValueError):
        with graph.transaction():
            graph.upsert_node("x", "Rule", {"Bad-Name": 1})


def test_reopen_persists(tmp_path):
    g = GoldGraph(tmp_path / "gold").open()
    _seed(g)
    g.close()
    g2 = GoldGraph(tmp_path / "gold").open()
    assert g2.node("r1")["value"] == "31"
    g2.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest ghostbrain/api/tests/test_ontology_graph.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.ontology.graph'`.

- [ ] **Step 3: Implement**

`ghostbrain/ontology/graph.py`:
```python
"""The gold graph: an embedded ArcadeDB database holding only ratified facts.

It is a projection of the ratification log (see projector.py) and can be
rebuilt from it at any time. Only the sidecar process may open it: ArcadeDB
embedded holds an exclusive per-process lock.
"""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from ghostbrain.ontology.schema import (
    DOMAIN_KINDS, EDGE_TYPES, META_UID, RELATION_TYPES, VERTEX_TYPES,
    check_edge, check_kind, check_prop,
)

DEFAULT_HEAP = "512m"
_jvm_lock = threading.Lock()


class GraphUnavailable(RuntimeError):
    """The gold graph cannot be opened (missing extra, JVM failure, corrupt store)."""


class GraphLocked(GraphUnavailable):
    """Another process holds the graph's lock."""


def _ensure_jvm(heap: str) -> None:
    import jpype  # noqa: PLC0415
    from arcadedb_embedded import jvm  # noqa: PLC0415

    with _jvm_lock:
        if not jpype.isJVMStarted():
            jvm.start_jvm(heap_size=heap)


def _set_clause(var: str, props: dict) -> tuple[str, dict]:
    parts, params = [], {}
    for key, value in props.items():
        if value is None:
            continue
        check_prop(key)
        parts.append(f"{var}.{key} = $p_{key}")
        params[f"p_{key}"] = value
    return (" SET " + ", ".join(parts)) if parts else "", params


class GoldGraph:
    def __init__(self, path: Path, heap: str | None = None) -> None:
        self._path = path
        self._heap = heap or os.environ.get("GHOSTBRAIN_ONTOLOGY_HEAP", DEFAULT_HEAP)
        self._db: Any = None

    # -- lifecycle -----------------------------------------------------------
    def open(self) -> "GoldGraph":
        try:
            import arcadedb_embedded as arc  # noqa: PLC0415
        except ImportError as e:
            raise GraphUnavailable("the ontology extra (arcadedb-embedded) is not installed") from e
        try:
            _ensure_jvm(self._heap)
        except Exception as e:  # noqa: BLE001 - surfaced as a status reason
            raise GraphUnavailable(f"could not start the JVM: {e}") from e
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if arc.database_exists(str(self._path)):
                self._db = arc.open_database(str(self._path))
            else:
                self._db = arc.create_database(str(self._path))
        except Exception as e:  # noqa: BLE001
            if "locked by another process" in str(e):
                raise GraphLocked(f"the gold graph is locked by another process ({self._path})") from e
            raise GraphUnavailable(f"could not open the gold graph: {e}") from e
        self._ensure_schema(arc)
        return self

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None

    def _ensure_schema(self, arc: Any) -> None:
        schema = self._db.schema
        for t in VERTEX_TYPES:
            schema.get_or_create_vertex_type(t)
            schema.get_or_create_property(t, "uid", arc.PropertyType.STRING)
            schema.get_or_create_index(t, ["uid"], unique=True)
        for e in EDGE_TYPES:
            schema.get_or_create_edge_type(e)

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._db.transaction():
            yield

    # -- primitives ------------------------------------------------------------
    def _rows(self, cypher: str, params: dict | None = None) -> list[dict]:
        rs = self._db.query("opencypher", cypher, params) if params else self._db.query("opencypher", cypher)
        return [{k: r.get(k) for k in r.get_property_names()} for r in rs]

    def _cmd(self, cypher: str, params: dict | None = None) -> list[dict]:
        rs = self._db.command("opencypher", cypher, params) if params else self._db.command("opencypher", cypher)
        if rs is None:
            return []
        return [{k: r.get(k) for k in r.get_property_names()} for r in rs]

    @staticmethod
    def _label(labels: Any) -> str:
        if isinstance(labels, str):
            return labels
        return list(labels)[0]

    # -- writes --------------------------------------------------------------
    def upsert_node(self, uid: str, kind: str, props: dict) -> None:
        check_kind(kind)
        existing = self._rows("MATCH (n) WHERE n.uid = $u RETURN labels(n) AS labels", {"u": uid})
        if existing and self._label(existing[0]["labels"]) != kind:
            self.set_props(uid, props)
            return
        set_sql, params = _set_clause("n", props)
        self._cmd(f"MERGE (n:{kind} {{uid: $uid}}){set_sql}", {"uid": uid, **params})

    def set_props(self, uid: str, props: dict) -> None:
        set_sql, params = _set_clause("n", props)
        if set_sql:
            self._cmd(f"MATCH (n) WHERE n.uid = $uid{set_sql}", {"uid": uid, **params})

    def upsert_edge(self, etype: str, src: str, dst: str, props: dict) -> bool:
        check_edge(etype)
        set_sql, params = _set_clause("e", props)
        rows = self._cmd(
            f"MATCH (a), (b) WHERE a.uid = $s AND b.uid = $d "
            f"MERGE (a)-[e:{etype}]->(b){set_sql} RETURN count(e) AS c",
            {"s": src, "d": dst, **params},
        )
        return bool(rows) and int(rows[0]["c"] or 0) > 0

    def delete_node(self, uid: str) -> None:
        self._cmd("MATCH (n) WHERE n.uid = $u DETACH DELETE n", {"u": uid})

    def clear(self) -> None:
        self._cmd("MATCH (n) DETACH DELETE n")

    def get_meta(self) -> int:
        rows = self._rows("MATCH (m:Meta) WHERE m.uid = $u RETURN m.last_applied_seq AS s", {"u": META_UID})
        return int(rows[0]["s"] or 0) if rows else 0

    def set_meta(self, seq: int) -> None:
        self._cmd("MERGE (m:Meta {uid: $u}) SET m.last_applied_seq = $s", {"u": META_UID, "s": seq})

    # -- reads ---------------------------------------------------------------
    def node(self, uid: str) -> dict | None:
        rows = self._rows(
            "MATCH (n) WHERE n.uid = $u RETURN labels(n) AS labels, n.name AS name, "
            "n.statement AS statement, n.value AS value, n.note_path AS note_path, "
            "n.provenance AS provenance, n.valid_from AS valid_from, n.ratification_id AS ratification_id",
            {"u": uid},
        )
        if not rows:
            return None
        row = rows[0]
        kind = self._label(row.pop("labels"))
        return {"uid": uid, "kind": kind, **row}

    def neighbourhood(self, focus: str, depth: int, cap: int = 300) -> tuple[list[dict], list[dict], bool]:
        hops: dict[str, int] = {}
        if self.node(focus) is None:
            return [], [], False
        hops[focus] = 0
        frontier = [focus]
        edges: set[tuple[str, str, str]] = set()
        truncated = False
        for hop in range(1, depth + 1):
            if not frontier:
                break
            rows = self._rows(
                "MATCH (a)-[e]->(b) WHERE a.uid IN $u OR b.uid IN $u "
                "RETURN a.uid AS s, type(e) AS t, b.uid AS d",
                {"u": frontier},
            )
            nxt: list[str] = []
            for r in rows:
                s, t, d = r["s"], r["t"], r["d"]
                for x in (s, d):
                    if x not in hops:
                        if len(hops) >= cap:
                            truncated = True
                            continue
                        hops[x] = hop
                        nxt.append(x)
                if s in hops and d in hops:
                    edges.add((s, t, d))
            frontier = nxt
        info = self._rows(
            "MATCH (n) WHERE n.uid IN $u RETURN n.uid AS uid, labels(n) AS labels, "
            "n.name AS name, n.note_path AS note_path",
            {"u": list(hops)},
        )
        nodes = [
            {"uid": r["uid"], "kind": self._label(r["labels"]), "name": r["name"] or r["uid"],
             "note_path": r["note_path"], "hop": hops[r["uid"]]}
            for r in info
        ]
        nodes.sort(key=lambda n: (n["hop"], n["uid"]))
        return nodes, [{"src": s, "type": t, "dst": d} for s, t, d in sorted(edges)], truncated

    def domain_nodes(self, project_uid: str, limit: int = 500) -> list[dict]:
        rows = self._rows(
            "MATCH (n)-[:PART_OF]->(p) WHERE p.uid = $p RETURN n.uid AS uid, labels(n) AS labels, "
            "n.name AS name, n.statement AS statement, n.value AS value, "
            "n.valid_from AS valid_from, n.provenance AS provenance",
            {"p": project_uid},
        )
        out = [{"kind": self._label(r.pop("labels")), **r} for r in rows]
        out = [n for n in out if n["kind"] in DOMAIN_KINDS]
        out.sort(key=lambda n: n["uid"])
        return out[:limit]

    def project_export(self, project_uid: str) -> list[dict]:
        nodes = self.domain_nodes(project_uid)
        uids = [n["uid"] for n in nodes]
        if not uids:
            return []
        ev = self._rows(
            "MATCH (n)-[e:EVIDENCED_BY]->(a) WHERE n.uid IN $u "
            "RETURN n.uid AS uid, a.note_path AS note_path, a.name AS title, e.quote AS quote",
            {"u": uids},
        )
        rel = self._rows(
            "MATCH (n)-[e]->(m) WHERE n.uid IN $u AND type(e) IN $types "
            "RETURN n.uid AS uid, type(e) AS t, m.uid AS target, m.name AS target_name",
            {"u": uids, "types": list(RELATION_TYPES)},
        )
        by_uid = {n["uid"]: {**n, "evidence": [], "relations": []} for n in nodes}
        for r in sorted(ev, key=lambda r: (r["uid"], r["note_path"] or "", r["quote"] or "")):
            by_uid[r["uid"]]["evidence"].append(
                {"note_path": r["note_path"], "title": r["title"], "quote": r["quote"]})
        for r in sorted(rel, key=lambda r: (r["uid"], r["t"], r["target"])):
            by_uid[r["uid"]]["relations"].append(
                {"type": r["t"], "target_uid": r["target"], "target_name": r["target_name"]})
        return [by_uid[u] for u in sorted(by_uid)]

    def snapshot(self) -> dict:
        nodes = self._rows(
            "MATCH (n) WHERE NOT n:Meta RETURN n.uid AS uid, labels(n) AS labels, n.name AS name, "
            "n.statement AS statement, n.value AS value, n.note_path AS note_path, "
            "n.provenance AS provenance, n.ratification_id AS ratification_id, n.valid_from AS valid_from"
        )
        for n in nodes:
            n["kind"] = self._label(n.pop("labels"))
        edges = self._rows(
            "MATCH (a)-[e]->(b) RETURN a.uid AS src, type(e) AS type, b.uid AS dst, "
            "e.quote AS quote, e.locator AS locator"
        )
        return {
            "nodes": sorted(nodes, key=lambda n: n["uid"]),
            "edges": sorted(edges, key=lambda e: (e["src"], e["type"], e["dst"], e["quote"] or "")),
        }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest ghostbrain/api/tests/test_ontology_graph.py -q`
Expected: PASS (8 tests). JVM startup adds a few seconds to the first test.

If `labels(n)` or `type(e) IN $types` behave differently in this ArcadeDB version, adjust only the query text and keep the method contracts. The spike verified `type(e)`, `labels(n)`, `count()`, `MERGE`, `DETACH DELETE` and dict params.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/ontology/graph.py ghostbrain/api/tests/test_ontology_graph.py
git commit -m "feat(ontology): GoldGraph adapter over embedded ArcadeDB"
```

---

### Task 5: Projector — log → graph, catch-up and rebuild

**Files:**
- Create: `ghostbrain/ontology/projector.py`
- Test: `ghostbrain/api/tests/test_ontology_projector.py`

**Interfaces:**
- Consumes: `Store.events/append_event`, `Event`, `GoldGraph.*`.
- Produces:
  - `projector.apply(graph: GoldGraph, event: Event) -> None`. Runs inside its own transaction and sets meta to `event.seq`.
  - `projector.catch_up(store: Store, graph: GoldGraph) -> int` (number of events applied)
  - `projector.rebuild(store: Store, graph: GoldGraph) -> int`

**Event payloads**, which are the contract every later task writes:

| Event | Payload |
|---|---|
| `seed` | `{"nodes":[{"uid","kind","props"}], "edges":[{"type","src","dst","props"}]}` |
| `bind` | `{"project": uuid, "artefacts":[{"aid","path","title"}]}` |
| `ratify` | `{"candidate_id": int, "project": uuid, "node": {"uid","kind","name","statement","value"}, "relations":[{"type","target_uid"}], "evidence":[{"aid","quote","locator"}], "provenance": str, "extractor_version": str}` |
| `revert` | `{"uid": str}` |
| `relabel` | `{"uid": str, "name": str}` |
| `reject`, `investigate`, `by_design` | no graph effect in M1 |

- [ ] **Step 1: Write the failing tests**

`ghostbrain/api/tests/test_ontology_projector.py`:
```python
import random

import pytest

pytest.importorskip("arcadedb_embedded")

from ghostbrain.ontology import projector  # noqa: E402
from ghostbrain.ontology.graph import GoldGraph  # noqa: E402
from ghostbrain.ontology.store import Store  # noqa: E402

SEED = {"nodes": [{"uid": "self", "kind": "Self", "props": {"name": "me"}},
                  {"uid": "c1", "kind": "Context", "props": {"name": "work"}},
                  {"uid": "p1", "kind": "Project", "props": {"name": "Orbit"}}],
        "edges": [{"type": "WORKS_IN", "src": "self", "dst": "c1", "props": {}},
                  {"type": "IN", "src": "p1", "dst": "c1", "props": {}}]}


def _ratify(i, uid, kind="Rule", value="31", aid="a1", rel=None):
    return {"candidate_id": i, "project": "p1",
            "node": {"uid": uid, "kind": kind, "name": f"n{i}", "statement": f"s{i}", "value": value},
            "relations": rel or [], "evidence": [{"aid": aid, "quote": f"q{i}", "locator": ""}],
            "provenance": "extracted", "extractor_version": "v1"}


@pytest.fixture
def env(tmp_path):
    store = Store(tmp_path / "o.db")
    g = GoldGraph(tmp_path / "gold").open()
    yield store, g, tmp_path
    g.close()
    store.close()


def test_ratify_projects_node_part_of_and_evidence(env):
    store, g, _ = env
    store.append_event("seed", SEED)
    store.append_event("bind", {"project": "p1", "artefacts": [{"aid": "a1", "path": "x.md", "title": "X"}]})
    seq = store.append_event("ratify", _ratify(1, "r1"))
    assert projector.catch_up(store, g) == 3
    n = g.node("r1")
    assert n["kind"] == "Rule" and n["ratification_id"] == seq and n["provenance"] == "extracted"
    edges = g.snapshot()["edges"]
    assert {"src": "r1", "type": "PART_OF", "dst": "p1", "quote": None, "locator": None} in edges
    assert any(e["type"] == "EVIDENCED_BY" and e["dst"] == "a1" and e["quote"] == "q1" for e in edges)
    assert g.get_meta() == seq
    assert projector.catch_up(store, g) == 0


def test_revert_and_relabel(env):
    store, g, _ = env
    store.append_event("seed", SEED)
    store.append_event("ratify", _ratify(1, "r1"))
    store.append_event("relabel", {"uid": "p1", "name": "Orbit Programme"})
    store.append_event("revert", {"uid": "r1"})
    projector.catch_up(store, g)
    assert g.node("r1") is None
    assert g.node("p1")["name"] == "Orbit Programme"


def _random_log(store, rng):
    store.append_event("seed", SEED)
    uids: list[str] = []
    for i in range(1, 40):
        roll = rng.random()
        if roll < 0.15:
            store.append_event("bind", {"project": "p1", "artefacts": [
                {"aid": f"a{rng.randint(1, 5)}", "path": f"n{i}.md", "title": f"T{i}"}]})
        elif roll < 0.65 or not uids:
            uid = f"u{rng.randint(1, 12)}"
            rel = [{"type": "DEPENDS_ON", "target_uid": rng.choice(uids)}] if uids and rng.random() < 0.4 else []
            store.append_event("ratify", _ratify(i, uid, kind=rng.choice(["Rule", "Concept", "Decision"]),
                                                 value=str(rng.randint(1, 60)), aid=f"a{rng.randint(1, 5)}", rel=rel))
            uids.append(uid)
        elif roll < 0.8:
            store.append_event("revert", {"uid": rng.choice(uids)})
        elif roll < 0.9:
            store.append_event("relabel", {"uid": rng.choice(uids + ["p1"]), "name": f"L{i}"})
        else:
            store.append_event("reject", {"candidate_id": i})


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_rebuild_equals_incremental(tmp_path, seed):
    """The key invariant: replaying the log from scratch equals applying it event by event."""
    store = Store(tmp_path / "o.db")
    _random_log(store, random.Random(seed))
    inc = GoldGraph(tmp_path / "inc").open()
    for ev in store.events():          # one event at a time, reopening midway
        projector.apply(inc, ev)
        if ev.seq == 20:
            inc.close()
            inc = GoldGraph(tmp_path / "inc").open()
    full = GoldGraph(tmp_path / "full").open()
    projector.rebuild(store, full)
    assert inc.snapshot() == full.snapshot()
    assert projector.rebuild(store, full) == store.head()   # rebuild is repeatable
    assert inc.snapshot() == full.snapshot()
    inc.close()
    full.close()
    store.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest ghostbrain/api/tests/test_ontology_projector.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.ontology.projector'`.

- [ ] **Step 3: Implement**

`ghostbrain/ontology/projector.py`:
```python
"""Projects the append-only log onto the gold graph.

Every handler is deterministic in (graph state, event), so `rebuild()` (clear and
replay) always equals incremental `apply()`; test_ontology_projector pins this.
"""
from __future__ import annotations

from ghostbrain.ontology.graph import GoldGraph
from ghostbrain.ontology.store import Event, Store


def _seed(g: GoldGraph, ev: Event) -> None:
    for n in ev.payload["nodes"]:
        g.upsert_node(n["uid"], n["kind"], {**n.get("props", {}), "provenance": "seeded"})
    for e in ev.payload["edges"]:
        g.upsert_edge(e["type"], e["src"], e["dst"], e.get("props", {}))


def _bind(g: GoldGraph, ev: Event) -> None:
    project = ev.payload["project"]
    for a in ev.payload["artefacts"]:
        g.upsert_node(a["aid"], "Artefact", {"name": a["title"], "note_path": a["path"]})
        g.upsert_edge("ABOUT", a["aid"], project, {"ratification_id": ev.seq})


def _ratify(g: GoldGraph, ev: Event) -> None:
    p = ev.payload
    node = p["node"]
    g.upsert_node(node["uid"], node["kind"], {
        "name": node["name"], "statement": node["statement"], "value": node.get("value"),
        "ratification_id": ev.seq, "valid_from": ev.ts, "provenance": p["provenance"],
        "extractor_version": p["extractor_version"],
    })
    g.upsert_edge("PART_OF", node["uid"], p["project"], {"ratification_id": ev.seq})
    for rel in p.get("relations", []):
        g.upsert_edge(rel["type"], node["uid"], rel["target_uid"], {"ratification_id": ev.seq})
    for e in p.get("evidence", []):
        g.upsert_node(e["aid"], "Artefact", {})
        g.upsert_edge("EVIDENCED_BY", node["uid"], e["aid"],
                      {"quote": e["quote"], "locator": e.get("locator", ""), "ratification_id": ev.seq})


def _revert(g: GoldGraph, ev: Event) -> None:
    g.delete_node(ev.payload["uid"])


def _relabel(g: GoldGraph, ev: Event) -> None:
    g.set_props(ev.payload["uid"], {"name": ev.payload["name"]})


_HANDLERS = {"seed": _seed, "bind": _bind, "ratify": _ratify, "revert": _revert, "relabel": _relabel}


def apply(graph: GoldGraph, event: Event) -> None:
    with graph.transaction():
        handler = _HANDLERS.get(event.type)
        if handler is not None:
            handler(graph, event)
        graph.set_meta(event.seq)


def catch_up(store: Store, graph: GoldGraph) -> int:
    applied = 0
    for ev in store.events(after=graph.get_meta()):
        apply(graph, ev)
        applied += 1
    return applied


def rebuild(store: Store, graph: GoldGraph) -> int:
    with graph.transaction():
        graph.clear()
        graph.set_meta(0)
    return catch_up(store, graph)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest ghostbrain/api/tests/test_ontology_projector.py -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/ontology/projector.py ghostbrain/api/tests/test_ontology_projector.py
git commit -m "feat(ontology): projector with deterministic rebuild from the log"
```

---

### Task 6: OntologyService — the sidecar-owned singleton

**Files:**
- Create: `ghostbrain/ontology/service.py`
- Modify: `ghostbrain/api/tests/conftest.py` (append the `ontology_root` fixture)
- Test: `ghostbrain/api/tests/test_ontology_service.py`

**Interfaces:**
- Consumes: `paths.ontology_dir`, `Store`, `GoldGraph`, `GraphUnavailable`, `projector`, `identity.seed_payload`.
- Produces:
  - **Singleton:** `get_service() -> OntologyService` and `reset_service() -> None` (closes and drops it; tests and atexit).
  - **`OntologyService(root: Path)`:**
    - `.store: Store`
    - `.status() -> dict`: `{"available": bool, "reason": str | None}`. Opening the graph is attempted here.
    - `.graph_session()`: a context manager yielding an opened `GoldGraph` under a lock. It raises `GraphUnavailable`.
    - `.commit(type: str, payload: dict, actor: str = "user") -> int`. Appends to the log, then *tries* to catch up the graph and run the projection hook. Graph errors are logged, never raised: the log is truth.
    - `.rebuild() -> int`
    - `.seed() -> int`: commits a `seed` event from `identity.seed_payload`.
    - `.on_applied: list[Callable[[OntologyService, list[str]], None]]`: hooks called after a successful catch-up, with the affected project uuids. Task 12 registers the markdown projection here.
- **Test fixture** `ontology_root` (in conftest): sets `GHOSTBRAIN_ONTOLOGY_DIR` to `tmp_path / "ontology"`, yields the path, and calls `reset_service()` on teardown.

- [ ] **Step 1: Add the fixture and write the failing tests**

Append to `ghostbrain/api/tests/conftest.py`:
```python
@pytest.fixture
def ontology_root(tmp_path, monkeypatch):
    from ghostbrain.ontology import service  # noqa: PLC0415

    root = tmp_path / "ontology"
    monkeypatch.setenv("GHOSTBRAIN_ONTOLOGY_DIR", str(root))
    service.reset_service()
    yield root
    service.reset_service()
```

`ghostbrain/api/tests/test_ontology_service.py`:
```python
import pytest

from ghostbrain.ontology import service as service_mod
from ghostbrain.ontology.graph import GoldGraph, GraphLocked


def test_status_reports_lock_without_raising(ontology_root, monkeypatch):
    def locked(self):
        raise GraphLocked("the gold graph is locked by another process (x)")
    monkeypatch.setattr(GoldGraph, "open", locked)
    svc = service_mod.get_service()
    st = svc.status()
    assert st == {"available": False, "reason": "the gold graph is locked by another process (x)"}


def test_commit_appends_even_when_graph_unavailable(ontology_root, monkeypatch):
    monkeypatch.setattr(GoldGraph, "open", lambda self: (_ for _ in ()).throw(GraphLocked("locked")))
    svc = service_mod.get_service()
    seq = svc.commit("relabel", {"uid": "x", "name": "y"})
    assert svc.store.head() == seq


def test_non_ontology_routes_unaffected_by_locked_graph(ontology_root, monkeypatch, client, auth_headers):
    monkeypatch.setattr(GoldGraph, "open", lambda self: (_ for _ in ()).throw(GraphLocked("locked")))
    service_mod.get_service().status()
    assert client.get("/v1/projects", headers=auth_headers).status_code == 200


def test_seed_then_graph_has_core_layer(ontology_root, tmp_vault):
    pytest.importorskip("arcadedb_embedded")
    from ghostbrain.api.repo import projects  # noqa: PLC0415
    p = projects.create_project("work", "Orbit")
    svc = service_mod.get_service()
    svc.seed()
    with svc.graph_session() as g:
        assert g.node(p["uuid"])["kind"] == "Project"
        assert g.node("self")["kind"] == "Self"


def test_catch_up_after_reopen(ontology_root, tmp_vault):
    pytest.importorskip("arcadedb_embedded")
    svc = service_mod.get_service()
    svc.seed()
    service_mod.reset_service()          # graph closed; log keeps going
    svc2 = service_mod.get_service()
    svc2.store.append_event("relabel", {"uid": "self", "name": "me-renamed"})
    with svc2.graph_session() as g:      # opening catches up
        assert g.node("self")["name"] == "me-renamed"


def test_on_applied_hook_receives_projects(ontology_root, tmp_vault):
    pytest.importorskip("arcadedb_embedded")
    svc = service_mod.get_service()
    seen: list[list[str]] = []
    svc.on_applied.append(lambda s, projects: seen.append(projects))
    svc.commit("bind", {"project": "p9", "artefacts": []})
    assert seen and "p9" in seen[-1]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest ghostbrain/api/tests/test_ontology_service.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.ontology.service'`.

- [ ] **Step 3: Implement**

`ghostbrain/ontology/service.py`:
```python
"""Process-wide ontology service owned by the sidecar.

The log (SQLite) is truth. The gold graph is opened lazily, on first use, which
also starts the JVM, and is caught up from the log whenever it is opened or
after each commit.
"""
from __future__ import annotations

import atexit
import logging
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

from ghostbrain import paths
from ghostbrain.ontology import identity, projector
from ghostbrain.ontology.graph import GoldGraph, GraphUnavailable
from ghostbrain.ontology.store import Store

log = logging.getLogger(__name__)

_PROJECT_KEYS = ("project",)


class OntologyService:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.store = Store(root / "ontology.db")
        self._graph: GoldGraph | None = None
        self._graph_error: str | None = None
        self._lock = threading.RLock()
        self.on_applied: list[Callable[["OntologyService", list[str]], None]] = []
        self.extraction = None  # set by pipeline.ExtractionRunner (Task 10)

    # -- graph ---------------------------------------------------------------
    def _open_graph(self) -> GoldGraph:
        if self._graph is None:
            g = GoldGraph(self.root / "gold")
            try:
                g.open()
            except GraphUnavailable as e:
                self._graph_error = str(e)
                raise
            self._graph = g
            self._graph_error = None
            projector.catch_up(self.store, g)
        return self._graph

    @contextmanager
    def graph_session(self) -> Iterator[GoldGraph]:
        with self._lock:
            yield self._open_graph()

    def status(self) -> dict:
        try:
            with self.graph_session():
                pass
            return {"available": True, "reason": None}
        except GraphUnavailable as e:
            return {"available": False, "reason": str(e)}

    # -- writes --------------------------------------------------------------
    def commit(self, type: str, payload: dict, actor: str = "user") -> int:
        with self._lock:
            before = self._graph.get_meta() if self._graph is not None else None
            seq = self.store.append_event(type, payload, actor)
            try:
                g = self._open_graph()
                start = before if before is not None else 0
                events = self.store.events(after=start)
                projector.catch_up(self.store, g)
                self._notify(sorted({e.payload[k] for e in events for k in _PROJECT_KEYS if k in e.payload}))
            except GraphUnavailable as e:
                log.warning("ontology: committed seq %s but the graph is unavailable: %s", seq, e)
            return seq

    def _notify(self, project_uuids: list[str]) -> None:
        for hook in list(self.on_applied):
            try:
                hook(self, project_uuids)
            except Exception:  # noqa: BLE001 - a projection failure must not undo a commit
                log.exception("ontology: on_applied hook failed")

    def rebuild(self) -> int:
        with self._lock:
            g = self._open_graph()
            n = projector.rebuild(self.store, g)
            self._notify([p["project_uuid"] for p in self.store.enabled_projects()])
            return n

    def seed(self) -> int:
        return self.commit("seed", identity.seed_payload(self.store), actor="system")

    def close(self) -> None:
        with self._lock:
            if self._graph is not None:
                self._graph.close()
                self._graph = None
            self.store.close()


_service: OntologyService | None = None
_service_lock = threading.Lock()


def get_service() -> OntologyService:
    global _service
    with _service_lock:
        if _service is None:
            _service = OntologyService(paths.ontology_dir())
            from ghostbrain.ontology import projection_md  # noqa: PLC0415  (Task 12)
            _service.on_applied.append(projection_md.on_applied)
        return _service


def reset_service() -> None:
    global _service
    with _service_lock:
        if _service is not None:
            _service.close()
            _service = None


atexit.register(reset_service)
```

Until Task 12 lands, create a stub `ghostbrain/ontology/projection_md.py` so the import resolves. Task 12 replaces it:
```python
"""Gold → vault markdown projection (implemented in Task 12)."""


def on_applied(service, project_uuids):  # noqa: ARG001
    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest ghostbrain/api/tests/test_ontology_service.py -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/ontology/service.py ghostbrain/ontology/projection_md.py ghostbrain/api/tests/conftest.py ghostbrain/api/tests/test_ontology_service.py
git commit -m "feat(ontology): sidecar-owned service with lazy graph and commit-then-project"
```

---

### Task 7: Scoping — discover project artefacts and a bulk binding item

**Files:**
- Create: `ghostbrain/ontology/scope.py`
- Test: `ghostbrain/api/tests/test_ontology_scope.py`

**Interfaces:**
- Consumes: `paths.vault_path`, `ghostbrain.api.repo.search.search(q, limit, days) -> {"items":[{"path",...}]}`, `Store.bindings/upsert_binding/add_item`.
- Produces:
  - `ArtefactRef` (dataclass: `aid: str, path: str, title: str`)
  - `artefact_key(path: str, meta: dict) -> str`
  - `is_generated(path: str, meta: dict) -> bool`
  - `read_artefact(rel_path: str) -> tuple[dict, str] | None` (frontmatter dict and body; None if missing)
  - `find_artefacts(seeds: list[str], *, limit: int = 500, search_fn=None) -> list[ArtefactRef]`
  - `propose_binding(store, project_uuid: str, refs: list[ArtefactRef]) -> int | None`. Returns the item id, or None if nothing new. It writes `proposed` bindings and one `binding` item with payload `{"artefacts":[{"aid","path","title"}]}`.

- [ ] **Step 1: Write the failing tests**

`ghostbrain/api/tests/test_ontology_scope.py`:
```python
from ghostbrain.ontology import scope
from ghostbrain.ontology.store import Store


def _note(vault, rel, fm: str, body: str):
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\n{fm}\n---\n{body}\n", encoding="utf-8")


def test_artefact_key_prefers_id_then_doc_id_then_stem():
    assert scope.artefact_key("a/b/x.md", {"id": "evt-1", "doc_id": "d"}) == "evt-1"
    assert scope.artefact_key("a/b/x.md", {"doc_id": "abc123"}) == "abc123"
    assert scope.artefact_key("a/b/x.md", {}) == "x"


def test_find_artefacts_keyword_match_dedupes_raw_and_context_copies(tmp_vault):
    _note(tmp_vault, "20-contexts/work/jira/t1.md", "id: t1\ntitle: Orbit lapse rules", "Lapse is day 31.")
    _note(tmp_vault, "00-inbox/raw/jira/t1.md", "id: t1\ntitle: Orbit lapse rules", "Lapse is day 31.")
    _note(tmp_vault, "20-contexts/work/jira/t2.md", "id: t2\ntitle: Other", "nothing to see")
    _note(tmp_vault, "20-contexts/work/slack/s1.md", "id: s1\ntitle: chat", "the orbit go-live moved")
    refs = scope.find_artefacts(["Orbit"], search_fn=lambda q, limit: [])
    assert sorted(r.aid for r in refs) == ["s1", "t1"]
    assert next(r for r in refs if r.aid == "t1").path == "20-contexts/work/jira/t1.md"


def test_generated_ontology_notes_are_never_artefacts(tmp_vault):
    _note(tmp_vault, "20-contexts/work/projects/orbit/ontology/rule/abcd1234-lapse.md",
          "type: ontology\nuuid: abcd\ngenerated: true", "Orbit lapse rule")
    _note(tmp_vault, "20-contexts/work/x.md", "id: x1\ntype: ontology", "Orbit")
    assert scope.find_artefacts(["Orbit"], search_fn=lambda q, limit: []) == []


def test_semantic_hits_are_included_and_failures_ignored(tmp_vault):
    _note(tmp_vault, "20-contexts/work/m/meet.md", "id: m1\ntitle: Planning", "unit-linked policy design")
    refs = scope.find_artefacts(["Orbit"], search_fn=lambda q, limit: ["20-contexts/work/m/meet.md"])
    assert [r.aid for r in refs] == ["m1"]

    def boom(q, limit):
        raise RuntimeError("index not built")
    assert scope.find_artefacts(["Orbit"], search_fn=boom) == []


def test_propose_binding_skips_known_artefacts(tmp_path):
    store = Store(tmp_path / "o.db")
    refs = [scope.ArtefactRef("a1", "x.md", "X"), scope.ArtefactRef("a2", "y.md", "Y")]
    item = scope.propose_binding(store, "p1", refs)
    assert store.item(item)["payload"]["artefacts"][0]["aid"] == "a1"
    store.upsert_binding("p1", "a1", "x.md", "X", "bound")
    store.upsert_binding("p1", "a2", "y.md", "Y", "excluded")
    assert scope.propose_binding(store, "p1", refs) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest ghostbrain/api/tests/test_ontology_scope.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.ontology.scope'`.

- [ ] **Step 3: Implement**

`ghostbrain/ontology/scope.py`:
```python
"""Which vault notes belong to a project: keyword and semantic discovery, then
one bulk `binding` backlog item. Bindings are human-ratified, never inferred."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import frontmatter

from ghostbrain.paths import vault_path

SCAN_ROOTS = ("20-contexts", "00-inbox/raw")   # context copies first: they win the dedupe
BODY_SCAN_CHARS = 50_000
SEMANTIC_LIMIT = 50


@dataclass(frozen=True)
class ArtefactRef:
    aid: str
    path: str
    title: str


def artefact_key(path: str, meta: dict) -> str:
    for field in ("id", "doc_id"):
        value = meta.get(field)
        if value:
            return str(value)
    return Path(path).stem


def is_generated(path: str, meta: dict) -> bool:
    return meta.get("type") == "ontology" or "/ontology/" in path


def read_artefact(rel_path: str) -> tuple[dict, str] | None:
    p = vault_path() / rel_path
    if not p.is_file():
        return None
    try:
        post = frontmatter.load(p)
    except Exception:  # noqa: BLE001 - malformed frontmatter: treat body as text
        return {}, p.read_text(encoding="utf-8", errors="replace")
    return dict(post.metadata), post.content


def _title(meta: dict, body: str, path: str) -> str:
    if meta.get("title"):
        return str(meta["title"])
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return Path(path).stem


def _default_search(q: str, limit: int) -> list[str]:
    from ghostbrain.api.repo import search  # noqa: PLC0415
    return [hit["path"] for hit in search.search(q, limit=limit)["items"]]


def find_artefacts(seeds: list[str], *, limit: int = 500,
                   search_fn: Callable[[str, int], list[str]] | None = None) -> list[ArtefactRef]:
    seeds = [s.strip() for s in seeds if s.strip()]
    if not seeds:
        return []
    pattern = re.compile(r"\b(" + "|".join(re.escape(s) for s in seeds) + r")\b", re.IGNORECASE)
    search_fn = search_fn or _default_search
    root = vault_path()
    found: dict[str, ArtefactRef] = {}

    def consider(rel: str, require_match: bool) -> None:
        if len(found) >= limit:
            return
        loaded = read_artefact(rel)
        if loaded is None:
            return
        meta, body = loaded
        if is_generated(rel, meta):
            return
        title = _title(meta, body, rel)
        if require_match and not pattern.search(title + "\n" + body[:BODY_SCAN_CHARS]):
            return
        aid = artefact_key(rel, meta)
        if aid not in found:
            found[aid] = ArtefactRef(aid, rel, title)

    for base in SCAN_ROOTS:
        for p in sorted((root / base).rglob("*.md")):
            consider(p.relative_to(root).as_posix(), require_match=True)
    for seed in seeds:
        try:
            hits = search_fn(seed, SEMANTIC_LIMIT)
        except Exception:  # noqa: BLE001 - semantic index missing/cold: keywords still work
            hits = []
        for rel in hits:
            consider(rel, require_match=False)
    return list(found.values())


def propose_binding(store, project_uuid: str, refs: list[ArtefactRef]) -> int | None:
    known = {b["aid"] for b in store.bindings(project_uuid)}
    fresh = [r for r in refs if r.aid not in known]
    if not fresh:
        return None
    for r in fresh:
        store.upsert_binding(project_uuid, r.aid, r.path, r.title, "proposed")
    return store.add_item(project_uuid, "binding", payload={
        "artefacts": [{"aid": r.aid, "path": r.path, "title": r.title} for r in fresh]})
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest ghostbrain/api/tests/test_ontology_scope.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/ontology/scope.py ghostbrain/api/tests/test_ontology_scope.py
git commit -m "feat(ontology): artefact scoping and bulk binding proposals"
```

---

### Task 8: Extraction — prompt, chunking, LLM call, quote validation

**Files:**
- Create: `ghostbrain/ontology/prompts.py`, `ghostbrain/ontology/extract.py`
- Test: `ghostbrain/api/tests/test_ontology_extract.py`

**Interfaces:**
- Consumes: `ghostbrain.llm.client.run(prompt, *, model, json_schema, budget_usd, timeout_s) -> LLMResult` (`.as_json()`), `llm.LLMError`, `schema.DOMAIN_KINDS/RELATION_TYPES`.
- Produces:
  - **Constants:** `EXTRACTOR_VERSION = "m1-2026-10-10"`, `CANDIDATE_JSON_SCHEMA: dict`.
  - **Candidate type:** `CandidateIn` (dataclass: `kind, name, statement, value: str | None, existing_uid: str | None, relations: list[dict], quote, locator, confidence: float`).
  - **Exception:** `ExtractionFailed(RuntimeError)`.
  - **Functions:**
    - `normalise(text: str) -> str`
    - `chunk_text(text: str, max_chars: int = 24_000) -> list[str]`
    - `build_prompt(title: str, text: str, digest: list[dict]) -> str`
    - `validate(raw_items: list[dict], source_text: str, digest_uids: set[str]) -> tuple[list[CandidateIn], int]` (valid candidates, discarded count)
    - `extract_chunk(title: str, text: str, digest: list[dict], *, run=None) -> tuple[list[CandidateIn], int]`. One retry with a repair suffix, then `ExtractionFailed`.

- [ ] **Step 1: Write the failing tests**

`ghostbrain/api/tests/test_ontology_extract.py`:
```python
import pytest

from ghostbrain.llm import client as llm
from ghostbrain.ontology import extract

SOURCE = "## Lapse\nThe team agreed: a policy “lapses on day 31” after a missed premium.\n"


def _item(**kw):
    base = {"kind": "Rule", "name": "lapse day", "statement": "Today policies lapse on day 31.",
            "value": "31", "existing_uid": None, "relations": [], "quote": "lapses on day 31",
            "locator": "## Lapse", "confidence": 0.8}
    base.update(kw)
    return base


def test_quote_match_tolerates_whitespace_case_and_curly_quotes():
    items = [_item(quote='A  policy "LAPSES ON\nday 31"')]
    valid, discarded = extract.validate(items, SOURCE, set())
    assert len(valid) == 1 and discarded == 0


def test_paraphrased_quote_is_discarded():
    valid, discarded = extract.validate([_item(quote="policies expire after thirty-one days")], SOURCE, set())
    assert valid == [] and discarded == 1


def test_schema_violations_discarded_and_unknown_uids_cleared():
    items = [
        _item(kind="Person"),
        _item(name="   "),
        _item(existing_uid="ghost", relations=[{"type": "DEPENDS_ON", "target_uid": "ghost"},
                                                {"type": "DEPENDS_ON", "target_uid": "known"}]),
        _item(confidence=7),
    ]
    valid, discarded = extract.validate(items, SOURCE, {"known"})
    assert discarded == 2
    assert valid[0].existing_uid is None
    assert valid[0].relations == [{"type": "DEPENDS_ON", "target_uid": "known"}]
    assert valid[1].confidence == 1.0


def test_chunk_text_splits_on_headings_and_hard_limit():
    text = "# A\n" + "x" * 30 + "\n# B\n" + "y" * 30
    assert extract.chunk_text(text, max_chars=40) == ["# A\n" + "x" * 30 + "\n", "# B\n" + "y" * 30]
    assert all(len(c) <= 10 for c in extract.chunk_text("z" * 25, max_chars=10))


def test_build_prompt_contains_digest_and_text():
    p = extract.build_prompt("Spec", SOURCE, [{"uid": "u1", "kind": "Rule", "name": "lapse day", "value": "31"}])
    assert "[u1] Rule: lapse day = 31" in p and "lapses on day 31" in p and "Spec" in p


class _Res:
    def __init__(self, data):
        self._data = data

    def as_json(self):
        return self._data


def test_extract_chunk_retries_once_then_fails():
    calls = []

    def flaky(prompt, **kw):
        calls.append(kw)
        if len(calls) == 1:
            raise llm.LLMError("boom")
        return _Res({"items": [_item()]})
    valid, _ = extract.extract_chunk("Spec", SOURCE, [], run=flaky)
    assert len(valid) == 1 and len(calls) == 2
    assert calls[0]["budget_usd"] >= 1.0 and calls[0]["json_schema"] == extract.CANDIDATE_JSON_SCHEMA

    with pytest.raises(extract.ExtractionFailed):
        extract.extract_chunk("Spec", SOURCE, [], run=lambda p, **kw: _Res({"nope": 1}))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest ghostbrain/api/tests/test_ontology_extract.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.ontology.extract'`.

- [ ] **Step 3: Implement**

`ghostbrain/ontology/prompts.py`:
```python
"""Extraction prompt. A vault copy at 90-meta/prompts/ontology-extract.md overrides it."""

EXTRACT_PROMPT = """You extract durable project knowledge from one note for a project ontology.

Return candidate facts of these kinds only: {{KINDS}}.
- Concept: what a term means in this project.
- Rule: a business or technical rule; put its concrete value in `value` (e.g. "31").
- Decision: what was chosen, including rejected options and the reason, in `statement`.
- Requirement, System (a service/component/system of record), Role (a job role — NEVER a person's name),
  OpenQuestion (something explicitly unresolved).

Rules:
1. Only facts the note actually states. `quote` must be copied verbatim from the note (max 300 chars).
2. Phrase `statement` as the de facto current state: "Today X, because Y".
3. If a fact is about something already in the known ontology below, set `existing_uid` to its id.
4. `relations` may only point at ids from the known ontology.
5. Never name individual people; use roles.
6. At most 15 items. Return {"items": []} when nothing durable is stated.
7. `confidence` is 0..1: how clearly the note states this as settled.

Known ontology for this project (id, kind, name = value):
{{DIGEST}}

Note title: {{TITLE}}
Note text:
<<<
{{TEXT}}
>>>
"""
```

`ghostbrain/ontology/extract.py`:
```python
"""One note chunk → validated observed candidates. A candidate whose quote is
not actually in the note is discarded (the main hallucination guard)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ghostbrain.llm import client as llm
from ghostbrain.ontology.prompts import EXTRACT_PROMPT
from ghostbrain.ontology.schema import DOMAIN_KINDS, RELATION_TYPES
from ghostbrain.paths import vault_path

EXTRACTOR_VERSION = "m1-2026-10-10"
EXTRACT_MODEL = "sonnet"
EXTRACT_BUDGET_USD = 2.0
EXTRACT_TIMEOUT_S = 300
MAX_QUOTE = 300
REPAIR_SUFFIX = "\n\nYour previous answer was invalid. Return ONLY JSON matching the schema."

CANDIDATE_JSON_SCHEMA: dict = {
    "type": "object", "additionalProperties": False, "required": ["items"],
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["kind", "name", "statement", "value", "existing_uid", "relations",
                     "quote", "locator", "confidence"],
        "properties": {
            "kind": {"type": "string", "enum": list(DOMAIN_KINDS)},
            "name": {"type": "string"},
            "statement": {"type": "string"},
            "value": {"type": ["string", "null"]},
            "existing_uid": {"type": ["string", "null"]},
            "relations": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["type", "target_uid"],
                "properties": {"type": {"type": "string", "enum": list(RELATION_TYPES)},
                               "target_uid": {"type": "string"}}}},
            "quote": {"type": "string"},
            "locator": {"type": "string"},
            "confidence": {"type": "number"},
        }}}},
}

_QUOTES = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"})
_WS = re.compile(r"\s+")


class ExtractionFailed(RuntimeError):
    pass


@dataclass
class CandidateIn:
    kind: str
    name: str
    statement: str
    value: str | None
    existing_uid: str | None
    relations: list[dict] = field(default_factory=list)
    quote: str = ""
    locator: str = ""
    confidence: float = 0.5


def normalise(text: str) -> str:
    return _WS.sub(" ", text.translate(_QUOTES)).strip().casefold()


def chunk_text(text: str, max_chars: int = 24_000) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    sections = re.split(r"(?m)^(?=#{1,3} )", text)
    chunks: list[str] = []
    current = ""
    for sec in sections:
        if len(current) + len(sec) <= max_chars:
            current += sec
            continue
        if current:
            chunks.append(current)
        while len(sec) > max_chars:
            chunks.append(sec[:max_chars])
            sec = sec[max_chars:]
        current = sec
    if current:
        chunks.append(current)
    return chunks


def _template() -> str:
    override = vault_path() / "90-meta" / "prompts" / "ontology-extract.md"
    if override.is_file():
        return override.read_text(encoding="utf-8")
    return EXTRACT_PROMPT


def build_prompt(title: str, text: str, digest: list[dict]) -> str:
    lines = [
        f"[{d['uid']}] {d['kind']}: {d['name']}" + (f" = {d['value']}" if d.get("value") else "")
        for d in digest
    ] or ["(empty — nothing ratified yet)"]
    return (_template()
            .replace("{{KINDS}}", ", ".join(DOMAIN_KINDS))
            .replace("{{DIGEST}}", "\n".join(lines))
            .replace("{{TITLE}}", title)
            .replace("{{TEXT}}", text))


def validate(raw_items: list[dict], source_text: str, digest_uids: set[str]) -> tuple[list[CandidateIn], int]:
    source = normalise(source_text)
    valid: list[CandidateIn] = []
    discarded = 0
    for it in raw_items:
        try:
            kind = it["kind"]
            name = str(it["name"]).strip()
            statement = str(it["statement"]).strip()
            quote = str(it["quote"]).strip()[:MAX_QUOTE]
        except (KeyError, TypeError):
            discarded += 1
            continue
        if kind not in DOMAIN_KINDS or not name or not statement or not quote or normalise(quote) not in source:
            discarded += 1
            continue
        existing = it.get("existing_uid")
        relations = [
            {"type": r["type"], "target_uid": r["target_uid"]}
            for r in it.get("relations") or []
            if isinstance(r, dict) and r.get("type") in RELATION_TYPES and r.get("target_uid") in digest_uids
        ]
        try:
            confidence = min(1.0, max(0.0, float(it.get("confidence", 0.5))))
        except (TypeError, ValueError):
            confidence = 0.5
        value = it.get("value")
        valid.append(CandidateIn(
            kind=kind, name=name, statement=statement,
            value=str(value).strip() if value not in (None, "") else None,
            existing_uid=existing if existing in digest_uids else None,
            relations=relations, quote=quote, locator=str(it.get("locator") or "")[:200],
            confidence=confidence,
        ))
    return valid, discarded


def extract_chunk(title: str, text: str, digest: list[dict], *, run=None) -> tuple[list[CandidateIn], int]:
    run = run or llm.run
    prompt = build_prompt(title, text, digest)
    uids = {d["uid"] for d in digest}
    last_error = "unknown"
    for attempt in range(2):
        try:
            result = run(prompt + (REPAIR_SUFFIX if attempt else ""), model=EXTRACT_MODEL,
                         json_schema=CANDIDATE_JSON_SCHEMA, budget_usd=EXTRACT_BUDGET_USD,
                         timeout_s=EXTRACT_TIMEOUT_S)
            data = result.as_json()
            if not isinstance(data, dict) or not isinstance(data.get("items"), list):
                raise ValueError("response has no items list")
            return validate(data["items"], text, uids)
        except (llm.LLMError, ValueError, TypeError) as e:
            last_error = str(e)
    raise ExtractionFailed(last_error)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest ghostbrain/api/tests/test_ontology_extract.py -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/ontology/prompts.py ghostbrain/ontology/extract.py ghostbrain/api/tests/test_ontology_extract.py
git commit -m "feat(ontology): LLM extraction with verbatim-quote validation"
```

---

### Task 9: Triage — merge duplicates, drop near-rejected

**Files:**
- Create: `ghostbrain/ontology/triage.py`
- Test: `ghostbrain/api/tests/test_ontology_triage.py`

**Interfaces:**
- Consumes: `Store.candidates/add_candidate/add_evidence/evidence/set_candidate_confidence/add_item`, `CandidateIn`, `EXTRACTOR_VERSION`.
- Produces:
  - **Embedder:** `Embedder` (Protocol: `encode(texts: list[str]) -> Sequence[Sequence[float]]`); `default_embedder() -> Embedder` (raises `TriageUnavailable`).
  - **Constants:** `TAU_DUP = 0.92`, `TAU_REJ = 0.90`.
  - **Helpers:** `canonical(c) -> str`, `pack(vec) -> bytes`, `unpack(b) -> list[float]`, `cosine(a, b) -> float`.
  - **`triage(store, project_uuid: str, aid: str, c: CandidateIn, embedder) -> tuple[str, int | None]`:**
    - `("merged", cid)`: the candidate joins an existing one; evidence is added and confidence raised by independent corroboration.
    - `("dropped", None)`: it is near a rejected candidate.
    - `("new", cid)`: a new candidate plus a `candidate` item.

- [ ] **Step 1: Write the failing tests**

`ghostbrain/api/tests/test_ontology_triage.py`:
```python
import pytest

from ghostbrain.ontology import triage
from ghostbrain.ontology.extract import CandidateIn
from ghostbrain.ontology.store import Store


class FakeEmbedder:
    """Bag-of-words vectors: identical statements → cosine 1, unrelated → ~0."""
    def encode(self, texts):
        out = []
        for t in texts:
            v = [0.0] * 64
            for w in t.lower().split():
                v[hash(w) % 64] += 1.0
            out.append(v)
        return out


def _c(statement="Today policies lapse on day 31.", value="31", conf=0.6):
    return CandidateIn(kind="Rule", name="lapse day", statement=statement, value=value,
                       existing_uid=None, quote="day 31", locator="", confidence=conf)


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "o.db")
    yield s
    s.close()


def test_new_then_duplicate_from_other_artefact_merges(store):
    e = FakeEmbedder()
    kind, cid = triage.triage(store, "p1", "a1", _c(), e)
    assert kind == "new" and store.open_items("p1")[0]["candidate_id"] == cid
    kind2, cid2 = triage.triage(store, "p1", "a2", _c(conf=0.5), e)
    assert (kind2, cid2) == ("merged", cid)
    assert [ev["aid"] for ev in store.evidence(cid)] == ["a1", "a2"]
    assert store.candidate(cid)["confidence"] == pytest.approx(1 - 0.4 * 0.5)
    assert len(store.open_items("p1")) == 1


def test_duplicate_from_same_artefact_does_not_inflate_confidence(store):
    e = FakeEmbedder()
    _, cid = triage.triage(store, "p1", "a1", _c(conf=0.6), e)
    triage.triage(store, "p1", "a1", _c(conf=0.7), e)
    assert store.candidate(cid)["confidence"] == pytest.approx(0.7)


def test_near_rejected_is_dropped(store):
    e = FakeEmbedder()
    _, cid = triage.triage(store, "p1", "a1", _c(), e)
    store.set_candidate_status(cid, "rejected")
    assert triage.triage(store, "p1", "a9", _c(), e) == ("dropped", None)


def test_unrelated_is_new(store):
    e = FakeEmbedder()
    triage.triage(store, "p1", "a1", _c(), e)
    kind, _ = triage.triage(store, "p1", "a1", _c(statement="Reinstatement allowed for 45 days", value="45"), e)
    assert kind == "new"


def test_pack_roundtrip_and_cosine():
    v = [1.0, 0.0, 2.5]
    assert triage.unpack(triage.pack(v)) == pytest.approx(v)
    assert triage.cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert triage.cosine([1, 0], [0, 0]) == 0.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest ghostbrain/api/tests/test_ontology_triage.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.ontology.triage'`.

- [ ] **Step 3: Implement**

`ghostbrain/ontology/triage.py`:
```python
"""Triage of validated candidates (M1: duplicates and rejection memory).
Contradiction, equivalence and re-opened items arrive in milestone 2."""
from __future__ import annotations

import math
from array import array
from typing import Protocol, Sequence

from ghostbrain.ontology.extract import EXTRACTOR_VERSION, CandidateIn

TAU_DUP = 0.92
TAU_REJ = 0.90


class TriageUnavailable(RuntimeError):
    pass


class Embedder(Protocol):
    def encode(self, texts: list[str]) -> Sequence[Sequence[float]]: ...


def default_embedder() -> Embedder:
    """The same MiniLM model the semantic index uses (packaged sidecar ships it)."""
    try:
        from ghostbrain.api.repo.search import _get_embedder  # noqa: PLC0415
        from ghostbrain.semantic.index import DEFAULT_MODEL_NAME  # noqa: PLC0415
        return _get_embedder(DEFAULT_MODEL_NAME)
    except Exception as e:  # noqa: BLE001 - sentence-transformers missing in some installs
        raise TriageUnavailable(f"embedding model unavailable: {e}") from e


def canonical(c: CandidateIn) -> str:
    return f"{c.kind} {c.name}: {c.statement} {c.value or ''}".strip()


def pack(vec: Sequence[float]) -> bytes:
    return array("f", [float(x) for x in vec]).tobytes()


def unpack(blob: bytes) -> list[float]:
    a = array("f")
    a.frombytes(blob)
    return list(a)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def _best(store, project_uuid: str, status: str, kind: str, vec: list[float]) -> tuple[float, dict | None]:
    best, best_row = 0.0, None
    for row in store.candidates(project_uuid, status):
        if row["kind"] != kind or row["embedding"] is None:
            continue
        score = cosine(vec, unpack(row["embedding"]))
        if score > best:
            best, best_row = score, row
    return best, best_row


def triage(store, project_uuid: str, aid: str, c: CandidateIn, embedder: Embedder) -> tuple[str, int | None]:
    vec = [float(x) for x in embedder.encode([canonical(c)])[0]]
    rej_score, _ = _best(store, project_uuid, "rejected", c.kind, vec)
    if rej_score >= TAU_REJ:
        return "dropped", None
    dup_score, dup = _best(store, project_uuid, "pending", c.kind, vec)
    if dup is not None and dup_score >= TAU_DUP and (dup["value"] or None) == (c.value or None):
        seen = {e["aid"] for e in store.evidence(dup["id"])}
        if aid in seen:
            confidence = max(dup["confidence"], c.confidence)
        else:
            confidence = 1 - (1 - dup["confidence"]) * (1 - c.confidence)
        store.add_evidence(dup["id"], aid, c.quote, c.locator)
        store.set_candidate_confidence(dup["id"], confidence)
        return "merged", dup["id"]
    cid = store.add_candidate(
        project_uuid, kind=c.kind, name=c.name, statement=c.statement, value=c.value,
        existing_uid=c.existing_uid, relations=c.relations, confidence=c.confidence,
        extractor_version=EXTRACTOR_VERSION, embedding=pack(vec),
    )
    store.add_evidence(cid, aid, c.quote, c.locator)
    store.add_item(project_uuid, "candidate", candidate_id=cid)
    return "new", cid
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest ghostbrain/api/tests/test_ontology_triage.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/ontology/triage.py ghostbrain/api/tests/test_ontology_triage.py
git commit -m "feat(ontology): triage merges duplicates and honours rejections"
```

---

### Task 10: Extraction pipeline and background runner

**Files:**
- Create: `ghostbrain/ontology/pipeline.py`
- Test: `ghostbrain/api/tests/test_ontology_pipeline.py`

**Interfaces:**
- Consumes: `OntologyService` (`.store`, `.graph_session()`), `scope.read_artefact`, `extract.chunk_text/extract_chunk/EXTRACTOR_VERSION/ExtractionFailed`, `triage.triage/default_embedder`, `GraphUnavailable`.
- Produces:
  - `MAX_CONSECUTIVE_FAILURES = 5`
  - `run_extraction(svc, project_uuid: str, *, limit: int = 25, run=None, embedder=None) -> dict`. Returns keys `processed`, `new`, `merged`, `dropped`, `discarded`, `failed`, `skipped` (all ints), plus `stopped: str | None`.
  - **`ExtractionRunner(svc)`:**
    - `.start(project_uuid, limit) -> bool` (False if already running)
    - `.status() -> dict`: `running`, `project`, `summary`, `last_error`
    - `get_runner(svc) -> ExtractionRunner` attaches the runner to `svc.extraction` on first use.

- [ ] **Step 1: Write the failing tests**

`ghostbrain/api/tests/test_ontology_pipeline.py`:
```python
import time

from ghostbrain.ontology import pipeline, service as service_mod


class FakeEmbedder:
    def encode(self, texts):
        out = []
        for t in texts:
            v = [0.0] * 64
            for w in t.lower().split():
                v[hash(w) % 64] += 1.0
            out.append(v)
        return out


class _Res:
    def __init__(self, items):
        self._items = items

    def as_json(self):
        return {"items": self._items}


def _note(vault, rel, aid, body):
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\nid: {aid}\ntitle: {aid}\ncreated: 2026-0{aid[-1]}-01\n---\n{body}\n", encoding="utf-8")


def _llm(prompt, **kw):
    if "day 31" in prompt:
        return _Res([{"kind": "Rule", "name": "lapse day", "statement": "Today lapse is day 31.", "value": "31",
                      "existing_uid": None, "relations": [], "quote": "lapse is day 31", "locator": "",
                      "confidence": 0.7}])
    return _Res([])


def _bind(svc, project, refs):
    for aid, path in refs:
        svc.store.upsert_binding(project, aid, path, aid, "bound")


def test_run_extraction_processes_oldest_first_and_is_idempotent(ontology_root, tmp_vault):
    svc = service_mod.get_service()
    _note(tmp_vault, "20-contexts/work/a2.md", "a2", "Agreed: lapse is day 31.")
    _note(tmp_vault, "20-contexts/work/a1.md", "a1", "Kickoff notes, nothing settled.")
    _bind(svc, "p1", [("a1", "20-contexts/work/a1.md"), ("a2", "20-contexts/work/a2.md")])
    out = pipeline.run_extraction(svc, "p1", limit=1, run=_llm, embedder=FakeEmbedder())
    assert out["processed"] == 1 and out["new"] == 0          # a1 (oldest) first
    out = pipeline.run_extraction(svc, "p1", limit=25, run=_llm, embedder=FakeEmbedder())
    assert out["processed"] == 1 and out["new"] == 1 and out["skipped"] == 1
    out = pipeline.run_extraction(svc, "p1", limit=25, run=_llm, embedder=FakeEmbedder())
    assert out["processed"] == 0 and out["skipped"] == 2


def test_missing_source_is_recorded_and_run_continues(ontology_root, tmp_vault):
    svc = service_mod.get_service()
    _note(tmp_vault, "20-contexts/work/a2.md", "a2", "Agreed: lapse is day 31.")
    _bind(svc, "p1", [("a1", "20-contexts/work/gone.md"), ("a2", "20-contexts/work/a2.md")])
    out = pipeline.run_extraction(svc, "p1", run=_llm, embedder=FakeEmbedder())
    assert out["failed"] == 1 and out["new"] == 1


def test_consecutive_failures_stop_the_run(ontology_root, tmp_vault):
    svc = service_mod.get_service()
    refs = []
    for i in range(1, 8):
        _note(tmp_vault, f"20-contexts/work/n{i}.md", f"n{i}", "text")
        refs.append((f"n{i}", f"20-contexts/work/n{i}.md"))
    _bind(svc, "p1", refs)
    out = pipeline.run_extraction(svc, "p1", run=lambda p, **kw: _Res("bad"), embedder=FakeEmbedder())
    assert out["failed"] == pipeline.MAX_CONSECUTIVE_FAILURES
    assert "consecutive" in out["stopped"]


def test_runner_reports_status(ontology_root, tmp_vault, monkeypatch):
    svc = service_mod.get_service()
    monkeypatch.setattr(pipeline, "run_extraction",
                        lambda s, p, limit=25, **kw: {"processed": 0, "stopped": None})
    runner = pipeline.get_runner(svc)
    assert runner.start("p1", 5) is True
    for _ in range(50):
        if not runner.status()["running"]:
            break
        time.sleep(0.02)
    st = runner.status()
    assert st["running"] is False and st["summary"] == {"processed": 0, "stopped": None}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest ghostbrain/api/tests/test_ontology_pipeline.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.ontology.pipeline'`.

- [ ] **Step 3: Implement**

`ghostbrain/ontology/pipeline.py`:
```python
"""Run extraction over a project's bound artefacts, oldest first. Idempotent on
(content hash, extractor version). M1 runs on demand; milestone 2 schedules it."""
from __future__ import annotations

import hashlib
import logging
import threading

from ghostbrain.ontology import extract, scope, triage
from ghostbrain.ontology.graph import GraphUnavailable

log = logging.getLogger(__name__)
MAX_CONSECUTIVE_FAILURES = 5
DIGEST_LIMIT = 150


def _digest(svc, project_uuid: str) -> list[dict]:
    try:
        with svc.graph_session() as g:
            return g.domain_nodes(project_uuid, limit=DIGEST_LIMIT)
    except GraphUnavailable:
        return []


def _ordered_bound(svc, project_uuid: str) -> list[tuple[dict, tuple[dict, str] | None]]:
    rows = []
    for b in svc.store.bindings(project_uuid, "bound"):
        loaded = scope.read_artefact(b["path"])
        created = str((loaded[0] if loaded else {}).get("created") or "9999")
        rows.append((created, b, loaded))
    rows.sort(key=lambda r: (r[0], r[1]["path"]))
    return [(b, loaded) for _, b, loaded in rows]


def run_extraction(svc, project_uuid: str, *, limit: int = 25, run=None, embedder=None) -> dict:
    out = {"processed": 0, "new": 0, "merged": 0, "dropped": 0, "discarded": 0,
           "failed": 0, "skipped": 0, "stopped": None}
    embedder = embedder or triage.default_embedder()
    digest = _digest(svc, project_uuid)
    consecutive = 0
    for b, loaded in _ordered_bound(svc, project_uuid):
        if out["processed"] + out["failed"] >= limit:
            break
        if loaded is None:
            svc.store.record_extraction(project_uuid, b["aid"], "missing", extract.EXTRACTOR_VERSION,
                                        "failed", "source missing")
            out["failed"] += 1
            continue
        meta, body = loaded
        content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if svc.store.extraction_done(project_uuid, b["aid"], content_hash, extract.EXTRACTOR_VERSION):
            out["skipped"] += 1
            continue
        try:
            for chunk in extract.chunk_text(body):
                candidates, discarded = extract.extract_chunk(b["title"], chunk, digest, run=run)
                out["discarded"] += discarded
                for c in candidates:
                    kind, _ = triage.triage(svc.store, project_uuid, b["aid"], c, embedder)
                    out[kind] += 1
        except extract.ExtractionFailed as e:
            svc.store.record_extraction(project_uuid, b["aid"], content_hash, extract.EXTRACTOR_VERSION,
                                        "failed", str(e))
            out["failed"] += 1
            consecutive += 1
            if consecutive >= MAX_CONSECUTIVE_FAILURES:
                out["stopped"] = f"stopped after {consecutive} consecutive failures: {e}"
                break
            continue
        consecutive = 0
        svc.store.record_extraction(project_uuid, b["aid"], content_hash, extract.EXTRACTOR_VERSION, "ok")
        out["processed"] += 1
    return out


class ExtractionRunner:
    def __init__(self, svc) -> None:
        self._svc = svc
        self._lock = threading.Lock()
        self._state = {"running": False, "project": None, "summary": None, "last_error": None}

    def start(self, project_uuid: str, limit: int) -> bool:
        with self._lock:
            if self._state["running"]:
                return False
            self._state = {"running": True, "project": project_uuid, "summary": None, "last_error": None}
        threading.Thread(target=self._run, args=(project_uuid, limit), daemon=True,
                         name="ontology-extract").start()
        return True

    def _run(self, project_uuid: str, limit: int) -> None:
        summary, error = None, None
        try:
            summary = run_extraction(self._svc, project_uuid, limit=limit)
            error = summary.get("stopped")
        except Exception as e:  # noqa: BLE001 - surfaced through status()
            log.exception("ontology extraction failed")
            error = str(e)
        with self._lock:
            self._state = {"running": False, "project": project_uuid, "summary": summary, "last_error": error}

    def status(self) -> dict:
        with self._lock:
            return dict(self._state)


def get_runner(svc) -> ExtractionRunner:
    if svc.extraction is None:
        svc.extraction = ExtractionRunner(svc)
    return svc.extraction
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest ghostbrain/api/tests/test_ontology_pipeline.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/ontology/pipeline.py ghostbrain/api/tests/test_ontology_pipeline.py
git commit -m "feat(ontology): on-demand extraction pipeline with background runner"
```

---

### Task 11: Backlog — list items and apply actions

**Files:**
- Create: `ghostbrain/ontology/backlog.py`
- Test: `ghostbrain/api/tests/test_ontology_backlog.py`

**Interfaces:**
- Consumes: `OntologyService.commit/store`, `Store.*`, `EXTRACTOR_VERSION`.
- Produces:
  - **Exceptions:** `ItemNotFound(LookupError)`, `ItemClosed(RuntimeError)` (→ 409), `BadAction(ValueError)` (→ 422).
  - `list_items(svc, project_uuid, limit: int = 50) -> list[dict]`. Each item has `id, type, created` plus either `candidate: {id, kind, name, statement, value, confidence, evidence:[{aid, path, title, quote, locator}]}` or `artefacts: [{aid, path, title}]`. Binding items come first, then candidates by confidence, descending.
  - `act(svc, item_id: int, action: str, *, name=None, statement=None, value=None, exclude: list[str] | None = None, note: str | None = None) -> int | None`. Returns the committed log seq, or None.
    - Actions: `ratify | reject | investigate`.
    - A binding `ratify` honours `exclude`.
    - A candidate `ratify` takes an edited `name`, `statement` or `value`.

- [ ] **Step 1: Write the failing tests**

`ghostbrain/api/tests/test_ontology_backlog.py`:
```python
import pytest

from ghostbrain.ontology import backlog, service as service_mod
from ghostbrain.ontology.extract import CandidateIn
from ghostbrain.ontology import triage


class FakeEmbedder:
    def encode(self, texts):
        return [[float(len(t)), 1.0] for t in texts]


def _candidate(svc, project="p1"):
    c = CandidateIn(kind="Rule", name="lapse day", statement="Today lapse is day 31.", value="31",
                    existing_uid=None, quote="day 31", locator="", confidence=0.7)
    svc.store.upsert_binding(project, "a1", "20-contexts/work/a1.md", "A1", "bound")
    _, cid = triage.triage(svc.store, project, "a1", c, FakeEmbedder())
    return cid, svc.store.open_items(project)[-1]["id"]


def test_ratify_candidate_with_edit_commits_full_payload(ontology_root, tmp_vault):
    svc = service_mod.get_service()
    cid, item = _candidate(svc)
    seq = backlog.act(svc, item, "ratify", value="30")
    ev = svc.store.events()[-1]
    assert ev.seq == seq and ev.type == "ratify"
    assert ev.payload["node"]["value"] == "30" and ev.payload["candidate_id"] == cid
    assert ev.payload["evidence"][0]["aid"] == "a1" and ev.payload["provenance"] == "extracted"
    assert len(ev.payload["node"]["uid"]) == 32
    assert svc.store.candidate(cid)["status"] == "ratified"


def test_double_ratify_conflicts_and_logs_once(ontology_root, tmp_vault):
    svc = service_mod.get_service()
    _, item = _candidate(svc)
    backlog.act(svc, item, "ratify")
    with pytest.raises(backlog.ItemClosed):
        backlog.act(svc, item, "ratify")
    assert [e.type for e in svc.store.events()].count("ratify") == 1


def test_reject_and_investigate(ontology_root, tmp_vault):
    svc = service_mod.get_service()
    cid, item = _candidate(svc)
    backlog.act(svc, item, "reject")
    assert svc.store.candidate(cid)["status"] == "rejected"
    assert svc.store.events()[-1].type == "reject"
    cid2, item2 = _candidate(svc, project="p2")
    backlog.act(svc, item2, "investigate", note="check with PO")
    assert svc.store.item(item2)["status"] == "parked"
    assert svc.store.candidate(cid2)["status"] == "investigating"


def test_binding_ratify_with_exclusions(ontology_root, tmp_vault):
    svc = service_mod.get_service()
    item = svc.store.add_item("p1", "binding", payload={"artefacts": [
        {"aid": "a1", "path": "x.md", "title": "X"}, {"aid": "a2", "path": "y.md", "title": "Y"}]})
    backlog.act(svc, item, "ratify", exclude=["a2"])
    ev = svc.store.events()[-1]
    assert ev.type == "bind" and [a["aid"] for a in ev.payload["artefacts"]] == ["a1"]
    assert {b["aid"]: b["status"] for b in svc.store.bindings("p1")} == {"a1": "bound", "a2": "excluded"}


def test_list_items_shapes(ontology_root, tmp_vault):
    svc = service_mod.get_service()
    _candidate(svc)
    svc.store.add_item("p1", "binding", payload={"artefacts": [{"aid": "a9", "path": "z.md", "title": "Z"}]})
    items = backlog.list_items(svc, "p1")
    assert items[0]["type"] == "binding" and items[0]["artefacts"][0]["aid"] == "a9"
    cand = items[1]["candidate"]
    assert cand["evidence"][0] == {"aid": "a1", "path": "20-contexts/work/a1.md", "title": "A1",
                                   "quote": "day 31", "locator": ""}


def test_unknown_action_and_missing_item(ontology_root, tmp_vault):
    svc = service_mod.get_service()
    _, item = _candidate(svc)
    with pytest.raises(backlog.BadAction):
        backlog.act(svc, item, "pick_a")
    with pytest.raises(backlog.ItemNotFound):
        backlog.act(svc, 9999, "ratify")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest ghostbrain/api/tests/test_ontology_backlog.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.ontology.backlog'`.

- [ ] **Step 3: Implement**

`ghostbrain/ontology/backlog.py`:
```python
"""The ratification backlog (M1: a plain list; ranking/cap/bundles in milestone 2)."""
from __future__ import annotations

import uuid as uuidlib

from ghostbrain.ontology.extract import EXTRACTOR_VERSION

ACTIONS = ("ratify", "reject", "investigate")


class ItemNotFound(LookupError):
    pass


class ItemClosed(RuntimeError):
    pass


class BadAction(ValueError):
    pass


def _artefact_info(svc, project_uuid: str) -> dict[str, dict]:
    return {b["aid"]: b for b in svc.store.bindings(project_uuid)}


def list_items(svc, project_uuid: str, limit: int = 50) -> list[dict]:
    info = _artefact_info(svc, project_uuid)
    out: list[dict] = []
    for it in svc.store.open_items(project_uuid):
        base = {"id": it["id"], "type": it["type"], "created": it["created"]}
        if it["type"] == "binding":
            out.append({**base, "candidate": None, "artefacts": it["payload"].get("artefacts", [])})
            continue
        c = svc.store.candidate(it["candidate_id"])
        if c is None:
            continue
        evidence = [
            {"aid": e["aid"], "path": info.get(e["aid"], {}).get("path", ""),
             "title": info.get(e["aid"], {}).get("title", e["aid"]),
             "quote": e["quote"], "locator": e["locator"]}
            for e in svc.store.evidence(c["id"])
        ]
        out.append({**base, "artefacts": [], "candidate": {
            "id": c["id"], "kind": c["kind"], "name": c["name"], "statement": c["statement"],
            "value": c["value"], "confidence": c["confidence"], "evidence": evidence}})
    bindings = [i for i in out if i["type"] == "binding"]
    cands = sorted((i for i in out if i["type"] == "candidate"),
                   key=lambda i: (-i["candidate"]["confidence"], i["id"]))
    return (bindings + cands)[:limit]


def act(svc, item_id: int, action: str, *, name: str | None = None, statement: str | None = None,
        value: str | None = None, exclude: list[str] | None = None, note: str | None = None) -> int | None:
    if action not in ACTIONS:
        raise BadAction(f"unknown action: {action!r}")
    it = svc.store.item(item_id)
    if it is None:
        raise ItemNotFound(item_id)
    if it["status"] != "open":
        raise ItemClosed(f"item {item_id} is already {it['status']}")
    project = it["project_uuid"]
    if it["type"] == "binding":
        return _act_binding(svc, it, project, action, exclude or [])
    return _act_candidate(svc, it, project, action, name, statement, value, note)


def _act_binding(svc, it: dict, project: str, action: str, exclude: list[str]) -> int | None:
    artefacts = it["payload"].get("artefacts", [])
    keep = [a for a in artefacts if action == "ratify" and a["aid"] not in set(exclude)]
    if not svc.store.resolve_item(it["id"], "ratified" if action == "ratify" else action,
                                  status="parked" if action == "investigate" else "resolved"):
        raise ItemClosed(f"item {it['id']} was closed concurrently")
    for a in artefacts:
        status = "bound" if a in keep else ("proposed" if action == "investigate" else "excluded")
        svc.store.upsert_binding(project, a["aid"], a["path"], a["title"], status)
    if keep:
        return svc.commit("bind", {"project": project, "artefacts": keep})
    return None


def _act_candidate(svc, it: dict, project: str, action: str, name, statement, value, note) -> int | None:
    c = svc.store.candidate(it["candidate_id"])
    status = {"ratify": "resolved", "reject": "resolved", "investigate": "parked"}[action]
    if not svc.store.resolve_item(it["id"], note or action, status=status):
        raise ItemClosed(f"item {it['id']} was closed concurrently")
    if action == "reject":
        svc.store.set_candidate_status(c["id"], "rejected")
        return svc.commit("reject", {"candidate_id": c["id"], "kind": c["kind"], "name": c["name"]})
    if action == "investigate":
        svc.store.set_candidate_status(c["id"], "investigating")
        return svc.commit("investigate", {"candidate_id": c["id"], "note": note or ""})
    svc.store.set_candidate_status(c["id"], "ratified")
    node = {
        "uid": c["existing_uid"] or uuidlib.uuid4().hex,
        "kind": c["kind"],
        "name": (name or c["name"]).strip(),
        "statement": (statement or c["statement"]).strip(),
        "value": value if value is not None else c["value"],
    }
    return svc.commit("ratify", {
        "candidate_id": c["id"], "project": project, "node": node,
        "relations": c["relations"],
        "evidence": [{"aid": e["aid"], "quote": e["quote"], "locator": e["locator"]}
                     for e in svc.store.evidence(c["id"])],
        "provenance": "extracted", "extractor_version": c["extractor_version"] or EXTRACTOR_VERSION,
    })
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest ghostbrain/api/tests/test_ontology_backlog.py -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/ontology/backlog.py ghostbrain/api/tests/test_ontology_backlog.py
git commit -m "feat(ontology): backlog listing and ratify/reject/investigate actions"
```

---

### Task 12: Markdown projection of gold

**Files:**
- Modify: `ghostbrain/ontology/projection_md.py` (replaces the Task 6 stub)
- Test: `ghostbrain/api/tests/test_ontology_projection.py`

**Interfaces:**
- Consumes: `GoldGraph.project_export`, `projects.get_project_by_uuid`, `notes_manual.make_slug`, `paths.vault_path`, `OntologyService.graph_session/store`.
- Produces:
  - `ontology_dir_for(project: dict) -> Path`, which returns `vault/20-contexts/<ctx>/projects/<slug>/ontology`
  - `write_project(graph, project_uuid: str) -> int` (number of files written; stale generated files are removed)
  - `on_applied(svc, project_uuids: list[str]) -> None`

- [ ] **Step 1: Write the failing tests**

`ghostbrain/api/tests/test_ontology_projection.py`:
```python
import pytest

pytest.importorskip("arcadedb_embedded")

import frontmatter  # noqa: E402

from ghostbrain.api.repo import projects  # noqa: E402
from ghostbrain.ontology import backlog, projection_md, service as service_mod, triage  # noqa: E402
from ghostbrain.ontology.extract import CandidateIn  # noqa: E402


class FakeEmbedder:
    def encode(self, texts):
        return [[float(len(t)), 1.0] for t in texts]


def _ratified(svc, p, statement="Today lapse is day 31."):
    svc.store.upsert_binding(p["uuid"], "a1", "20-contexts/work/a1.md", "A1", "bound")
    c = CandidateIn(kind="Rule", name="lapse day", statement=statement, value="31",
                    existing_uid=None, quote="day 31", locator="", confidence=0.7)
    triage.triage(svc.store, p["uuid"], "a1", c, FakeEmbedder())
    item = svc.store.open_items(p["uuid"])[-1]["id"]
    backlog.act(svc, item, "ratify")
    return svc.store.events()[-1].payload["node"]["uid"]


def test_ratify_writes_generated_note_with_evidence(ontology_root, tmp_vault):
    p = projects.create_project("work", "Orbit")
    svc = service_mod.get_service()
    svc.seed()
    uid = _ratified(svc, p)
    files = list((tmp_vault / "20-contexts/work/projects/orbit/ontology/rule").glob("*.md"))
    assert len(files) == 1 and files[0].name.startswith(uid[:8])
    post = frontmatter.load(files[0])
    assert post["type"] == "ontology" and post["uuid"] == uid and post["generated"] is True
    assert "[[20-contexts/work/a1]]" in post.content and "day 31" in post.content


def test_revert_removes_generated_note(ontology_root, tmp_vault):
    p = projects.create_project("work", "Orbit")
    svc = service_mod.get_service()
    svc.seed()
    uid = _ratified(svc, p)
    svc.commit("revert", {"uid": uid, "project": p["uuid"]})
    assert list((tmp_vault / "20-contexts/work/projects/orbit/ontology").rglob("*.md")) == []


def test_project_rename_moves_projection(ontology_root, tmp_vault):
    p = projects.create_project("work", "Orbit")
    svc = service_mod.get_service()
    svc.seed()
    _ratified(svc, p)
    projects.rename_project("work", p["slug"], name="Orbit Programme")
    renamed = projects.get_project_by_uuid(p["uuid"])
    with svc.graph_session() as g:
        projection_md.write_project(g, p["uuid"])
    assert list((tmp_vault / f"20-contexts/work/projects/{renamed['slug']}/ontology").rglob("*.md"))
```

Note: the `revert` payload above carries `project` so `on_applied` knows which project to regenerate. Add the optional `project` key to the Task 5 revert payload contract. The projector ignores it.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest ghostbrain/api/tests/test_ontology_projection.py -q`
Expected: FAIL. No files are written, because the stub does nothing.

- [ ] **Step 3: Implement**

Replace `ghostbrain/ontology/projection_md.py`:
```python
"""Write gold out as vault markdown so the ontology stays readable outside the app.

Files are generated: hand edits are overwritten, and scoping never treats them
as artefacts (`type: ontology`)."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import frontmatter

from ghostbrain.api.repo import projects as projects_repo
from ghostbrain.ontology.graph import GraphUnavailable
from ghostbrain.ontology.schema import ui_kind
from ghostbrain.paths import vault_path

HEADER = "<!-- Generated by Poltergeist from the ratified ontology. Edits are overwritten. -->"


def ontology_dir_for(project: dict) -> Path:
    return vault_path() / projects_repo.PROJECT_DIR_TEMPLATE.format(
        context=project["context"], slug=project["slug"]) / "ontology"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def _wikilink(rel_path: str | None, fallback: str) -> str:
    if not rel_path:
        return fallback
    return f"[[{rel_path[:-3] if rel_path.endswith('.md') else rel_path}]]"


def write_project(graph, project_uuid: str) -> int:
    from ghostbrain.api.repo.notes_manual import make_slug  # noqa: PLC0415 (import cycle)

    project = projects_repo.get_project_by_uuid(project_uuid)
    if project is None:
        return 0
    root = ontology_dir_for(project)
    nodes = graph.project_export(project_uuid)
    rel_of = {
        n["uid"]: f"{ui_kind(n['kind'])}/{n['uid'][:8]}-{make_slug(n['name']) or 'node'}.md"
        for n in nodes
    }
    vault = vault_path()
    keep: set[Path] = set()
    for n in nodes:
        path = root / rel_of[n["uid"]]
        keep.add(path)
        lines = [HEADER, f"# {n['name']}", "", n.get("statement") or ""]
        if n.get("value"):
            lines += ["", f"**Value:** {n['value']}"]
        if n["evidence"]:
            lines += ["", "## Evidence"]
            lines += [f"- {_wikilink(e['note_path'], e['title'] or '?')} — \"{e['quote']}\"" for e in n["evidence"]]
        if n["relations"]:
            lines += ["", "## Related"]
            for r in n["relations"]:
                target = rel_of.get(r["target_uid"])
                link = _wikilink((root / target).relative_to(vault).as_posix(), r["target_name"] or "?") \
                    if target else (r["target_name"] or r["target_uid"])
                lines.append(f"- {r['type']} → {link}")
        post = frontmatter.Post("\n".join(lines) + "\n", type="ontology", ontologyKind=ui_kind(n["kind"]),
                                uuid=n["uid"], project=project_uuid, ratifiedAt=n.get("valid_from"),
                                provenance=n.get("provenance"), generated=True)
        _atomic_write(path, frontmatter.dumps(post) + "\n")
    if root.exists():
        for old in root.rglob("*.md"):
            if old in keep:
                continue
            try:
                if frontmatter.load(old).get("generated") is True:
                    old.unlink()
            except Exception:  # noqa: BLE001 - never delete what we cannot identify as ours
                continue
    return len(nodes)


def on_applied(svc, project_uuids: list[str]) -> None:
    enabled = {p["project_uuid"] for p in svc.store.enabled_projects()}
    targets = [p for p in project_uuids if p in enabled or projects_repo.get_project_by_uuid(p)]
    if not targets:
        return
    try:
        with svc.graph_session() as g:
            for p in targets:
                write_project(g, p)
    except GraphUnavailable:
        return
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest ghostbrain/api/tests/test_ontology_projection.py ghostbrain/api/tests/test_ontology_service.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/ontology/projection_md.py ghostbrain/api/tests/test_ontology_projection.py
git commit -m "feat(ontology): project gold into generated vault notes"
```

---

### Task 13: API — `/v1/ontology` router

**Files:**
- Create: `ghostbrain/api/models/ontology.py`, `ghostbrain/api/routes/ontology.py`
- Modify: `ghostbrain/api/main.py` (import as `from ghostbrain.api.routes import ontology as ontology_routes`, then `app.include_router(ontology_routes.router)` after `library_routes` at line 117)
- Test: `ghostbrain/api/tests/test_ontology_routes.py`

**Interfaces:**
- Consumes: everything above.
- Produces these endpoints (all under the bearer-auth middleware):

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/v1/ontology/status` | — | `OntologyStatus {available, reason}` |
| GET | `/v1/ontology/projects` | — | `list[OntologyProject {uuid, id, name, context, seeds, bound, pending_items}]` |
| POST | `/v1/ontology/projects/enable` | `{project_id, seeds: list[str] (min 1)}` | `OntologyProject` (422 unknown project) |
| POST | `/v1/ontology/projects/{uuid}/scope` | — | `{item_id: int\|null, found: int}` (404 not enabled) |
| POST | `/v1/ontology/projects/{uuid}/extract` | `{limit: int = 25 (1..200)}` | `ExtractStatus` (409 if running) |
| GET | `/v1/ontology/projects/{uuid}/extract` | — | `ExtractStatus {running, project, summary, last_error}` |
| GET | `/v1/ontology/backlog?project=` | — | `list[OntologyItem]` |
| POST | `/v1/ontology/backlog/{item_id}/action` | `OntologyActionRequest {action, name?, statement?, value?, exclude?, note?}` | `{ok: true, seq: int\|null}` (404/409/422) |
| GET | `/v1/ontology/graph?project=&focus=&depth=` | — | `OntologyGraph {focus, depth, nodes:[{path, title, context, kind, degree, ghost, hop, note_path}], edges:[{source, target, weight, kind}], truncated}` (503 unavailable) |
| POST | `/v1/ontology/nodes/{uid}/revert` | `{project}` | `{ok, seq}` (503) |
| POST | `/v1/ontology/rebuild` | — | `{applied: int}` (503) |

In the graph response, `path` is the node uid. That lets the A6 renderer key nodes as it does notes. Artefact nodes carry `note_path`.

- [ ] **Step 1: Write the failing tests**

`ghostbrain/api/tests/test_ontology_routes.py`:
```python
import pytest

from ghostbrain.api.repo import projects
from ghostbrain.ontology import pipeline, service as service_mod
from ghostbrain.ontology.graph import GoldGraph, GraphLocked


def _note(vault, rel, aid, body):
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\nid: {aid}\ntitle: {aid}\n---\n{body}\n", encoding="utf-8")


def test_status_and_graph_503_when_locked(ontology_root, client, auth_headers, monkeypatch):
    monkeypatch.setattr(GoldGraph, "open", lambda self: (_ for _ in ()).throw(GraphLocked("locked by another process")))
    r = client.get("/v1/ontology/status", headers=auth_headers)
    assert r.json() == {"available": False, "reason": "locked by another process"}
    r = client.get("/v1/ontology/graph", params={"project": "x"}, headers=auth_headers)
    assert r.status_code == 503 and "locked" in r.json()["detail"]


def test_enable_scope_ratify_binding_and_graph(ontology_root, tmp_vault, client, auth_headers):
    pytest.importorskip("arcadedb_embedded")
    p = projects.create_project("work", "Orbit")
    _note(tmp_vault, "20-contexts/work/jira/t1.md", "t1", "Orbit lapse is day 31.")
    r = client.post("/v1/ontology/projects/enable", json={"project_id": p["id"], "seeds": ["Orbit"]},
                    headers=auth_headers)
    assert r.status_code == 200 and r.json()["uuid"] == p["uuid"]
    items = client.get("/v1/ontology/backlog", params={"project": p["uuid"]}, headers=auth_headers).json()
    assert items[0]["type"] == "binding" and items[0]["artefacts"][0]["aid"] == "t1"
    r = client.post(f"/v1/ontology/backlog/{items[0]['id']}/action", json={"action": "ratify"}, headers=auth_headers)
    assert r.status_code == 200 and r.json()["ok"] is True
    r = client.post(f"/v1/ontology/backlog/{items[0]['id']}/action", json={"action": "ratify"}, headers=auth_headers)
    assert r.status_code == 409
    g = client.get("/v1/ontology/graph", params={"project": p["uuid"], "depth": 2}, headers=auth_headers).json()
    kinds = {n["path"]: n["kind"] for n in g["nodes"]}
    assert g["focus"] == p["uuid"] and kinds[p["uuid"]] == "project" and kinds["t1"] == "artefact"
    art = next(n for n in g["nodes"] if n["path"] == "t1")
    assert art["note_path"] == "20-contexts/work/jira/t1.md"
    assert {"source": "t1", "target": p["uuid"], "weight": 1.0, "kind": "about"} in g["edges"]
    listed = client.get("/v1/ontology/projects", headers=auth_headers).json()
    assert listed[0]["bound"] == 1 and listed[0]["seeds"] == ["Orbit"]


def test_enable_unknown_project_422_and_empty_seeds_422(ontology_root, tmp_vault, client, auth_headers):
    r = client.post("/v1/ontology/projects/enable", json={"project_id": "work/nope", "seeds": ["x"]}, headers=auth_headers)
    assert r.status_code == 422
    p = projects.create_project("work", "Orbit")
    r = client.post("/v1/ontology/projects/enable", json={"project_id": p["id"], "seeds": []}, headers=auth_headers)
    assert r.status_code == 422


def test_extract_start_conflict(ontology_root, tmp_vault, client, auth_headers, monkeypatch):
    svc = service_mod.get_service()
    svc.store.enable_project("p1", ["x"])
    runner = pipeline.get_runner(svc)
    monkeypatch.setattr(runner, "start", lambda project, limit: False)
    r = client.post("/v1/ontology/projects/p1/extract", json={"limit": 5}, headers=auth_headers)
    assert r.status_code == 409


def test_bad_action_422_and_missing_item_404(ontology_root, tmp_vault, client, auth_headers):
    r = client.post("/v1/ontology/backlog/999/action", json={"action": "ratify"}, headers=auth_headers)
    assert r.status_code == 404
    r = client.post("/v1/ontology/backlog/999/action", json={"action": "explode"}, headers=auth_headers)
    assert r.status_code == 422
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest ghostbrain/api/tests/test_ontology_routes.py -q`
Expected: FAIL with 404s, because the router is not registered.

- [ ] **Step 3: Implement**

`ghostbrain/api/models/ontology.py`:
```python
"""Ontology API schemas."""
from typing import Literal

from pydantic import BaseModel, Field


class OntologyStatus(BaseModel):
    available: bool
    reason: str | None = None


class OntologyProject(BaseModel):
    uuid: str
    id: str
    name: str
    context: str
    seeds: list[str]
    bound: int
    pending_items: int


class EnableRequest(BaseModel):
    project_id: str
    seeds: list[str] = Field(..., min_length=1)


class ScopeResult(BaseModel):
    item_id: int | None
    found: int


class ExtractRequest(BaseModel):
    limit: int = Field(25, ge=1, le=200)


class ExtractStatus(BaseModel):
    running: bool
    project: str | None = None
    summary: dict | None = None
    last_error: str | None = None


class Evidence(BaseModel):
    aid: str
    path: str
    title: str
    quote: str
    locator: str


class Candidate(BaseModel):
    id: int
    kind: str
    name: str
    statement: str
    value: str | None
    confidence: float
    evidence: list[Evidence]


class BindingArtefact(BaseModel):
    aid: str
    path: str
    title: str


class OntologyItem(BaseModel):
    id: int
    type: Literal["binding", "candidate"]
    created: str
    candidate: Candidate | None
    artefacts: list[BindingArtefact]


class OntologyActionRequest(BaseModel):
    action: Literal["ratify", "reject", "investigate"]
    name: str | None = None
    statement: str | None = None
    value: str | None = None
    exclude: list[str] | None = None
    note: str | None = None


class ActionResult(BaseModel):
    ok: bool
    seq: int | None


class GraphNode(BaseModel):
    path: str
    title: str
    context: str
    kind: str
    degree: int
    ghost: bool
    hop: int
    note_path: str | None


class GraphEdge(BaseModel):
    source: str
    target: str
    weight: float
    kind: str


class OntologyGraph(BaseModel):
    focus: str
    depth: int
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool


class RevertRequest(BaseModel):
    project: str


class RebuildResult(BaseModel):
    applied: int
```

`ghostbrain/api/routes/ontology.py`:
```python
"""/v1/ontology — project ontologies, the ratification backlog and the gold graph."""
from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, HTTPException, Query

from ghostbrain.api.models.ontology import (
    ActionResult, EnableRequest, ExtractRequest, ExtractStatus, OntologyActionRequest, OntologyGraph,
    OntologyItem, OntologyProject, OntologyStatus, RebuildResult, RevertRequest, ScopeResult,
)
from ghostbrain.api.repo import projects as projects_repo
from ghostbrain.ontology import backlog, pipeline, scope
from ghostbrain.ontology.graph import GraphUnavailable
from ghostbrain.ontology.schema import ui_kind
from ghostbrain.ontology.service import get_service

router = APIRouter(prefix="/v1/ontology", tags=["ontology"])


def _unavailable(e: GraphUnavailable) -> HTTPException:
    return HTTPException(status_code=503, detail=str(e))


def _project_view(svc, project_uuid: str, seeds: list[str]) -> dict:
    p = projects_repo.get_project_by_uuid(project_uuid) or {}
    return {
        "uuid": project_uuid, "id": p.get("id", ""), "name": p.get("name", "(missing project)"),
        "context": p.get("context", ""), "seeds": seeds,
        "bound": len(svc.store.bindings(project_uuid, "bound")),
        "pending_items": len(svc.store.open_items(project_uuid)),
    }


def _require_enabled(svc, project_uuid: str) -> list[str]:
    seeds = svc.store.project_seeds(project_uuid)
    if seeds is None:
        raise HTTPException(status_code=404, detail=f"ontology not enabled for project {project_uuid}")
    return seeds


@router.get("/status", response_model=OntologyStatus)
def status() -> dict:
    return get_service().status()


@router.get("/projects", response_model=list[OntologyProject])
def list_enabled() -> list[dict]:
    svc = get_service()
    return [_project_view(svc, p["project_uuid"], p["seeds"]) for p in svc.store.enabled_projects()]


@router.post("/projects/enable", response_model=OntologyProject)
def enable(payload: EnableRequest) -> dict:
    seeds = [s.strip() for s in payload.seeds if s.strip()]
    if not seeds:
        raise HTTPException(status_code=422, detail="at least one non-empty seed term is required")
    projects_repo.ensure_project_uuids()
    match = next((p for p in projects_repo.list_projects() if p["id"] == payload.project_id), None)
    if match is None:
        raise HTTPException(status_code=422, detail=f"unknown project: {payload.project_id}")
    svc = get_service()
    svc.store.enable_project(match["uuid"], seeds)
    svc.seed()
    scope.propose_binding(svc.store, match["uuid"], scope.find_artefacts(seeds))
    return _project_view(svc, match["uuid"], seeds)


@router.post("/projects/{project_uuid}/scope", response_model=ScopeResult)
def rescope(project_uuid: str) -> dict:
    svc = get_service()
    seeds = _require_enabled(svc, project_uuid)
    refs = scope.find_artefacts(seeds)
    return {"item_id": scope.propose_binding(svc.store, project_uuid, refs), "found": len(refs)}


@router.post("/projects/{project_uuid}/extract", response_model=ExtractStatus)
def start_extract(project_uuid: str, payload: ExtractRequest) -> dict:
    svc = get_service()
    _require_enabled(svc, project_uuid)
    runner = pipeline.get_runner(svc)
    if not runner.start(project_uuid, payload.limit):
        raise HTTPException(status_code=409, detail="an extraction run is already in progress")
    return runner.status()


@router.get("/projects/{project_uuid}/extract", response_model=ExtractStatus)
def extract_status(project_uuid: str) -> dict:  # noqa: ARG001 - one runner per sidecar
    return pipeline.get_runner(get_service()).status()


@router.get("/backlog", response_model=list[OntologyItem])
def list_backlog(project: str = Query(...)) -> list[dict]:
    return backlog.list_items(get_service(), project)


@router.post("/backlog/{item_id}/action", response_model=ActionResult)
def act(item_id: int, payload: OntologyActionRequest) -> dict:
    try:
        seq = backlog.act(get_service(), item_id, payload.action, name=payload.name,
                          statement=payload.statement, value=payload.value,
                          exclude=payload.exclude, note=payload.note)
    except backlog.ItemNotFound:
        raise HTTPException(status_code=404, detail=f"no backlog item {item_id}") from None
    except backlog.ItemClosed as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    except backlog.BadAction as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    return {"ok": True, "seq": seq}


@router.get("/graph", response_model=OntologyGraph)
def graph(project: str = Query(...), focus: str | None = None, depth: int = Query(2, ge=1, le=3)) -> dict:
    svc = get_service()
    p = projects_repo.get_project_by_uuid(project) or {}
    try:
        with svc.graph_session() as g:
            nodes, edges, truncated = g.neighbourhood(focus or project, depth)
    except GraphUnavailable as e:
        raise _unavailable(e) from None
    degree = Counter([e["src"] for e in edges] + [e["dst"] for e in edges])
    return {
        "focus": focus or project, "depth": depth, "truncated": truncated,
        "nodes": [{"path": n["uid"], "title": n["name"], "context": p.get("name", ""),
                   "kind": ui_kind(n["kind"]), "degree": degree[n["uid"]], "ghost": False,
                   "hop": n["hop"], "note_path": n["note_path"]} for n in nodes],
        "edges": [{"source": e["src"], "target": e["dst"], "weight": 1.0, "kind": e["type"].lower()}
                  for e in edges],
    }


@router.post("/nodes/{uid}/revert", response_model=ActionResult)
def revert(uid: str, payload: RevertRequest) -> dict:
    svc = get_service()
    try:
        with svc.graph_session() as g:
            if g.node(uid) is None:
                raise HTTPException(status_code=404, detail=f"no gold node {uid}")
    except GraphUnavailable as e:
        raise _unavailable(e) from None
    return {"ok": True, "seq": svc.commit("revert", {"uid": uid, "project": payload.project})}


@router.post("/rebuild", response_model=RebuildResult)
def rebuild() -> dict:
    try:
        return {"applied": get_service().rebuild()}
    except GraphUnavailable as e:
        raise _unavailable(e) from None
```

In `ghostbrain/api/main.py`:
- add `from ghostbrain.api.routes import ontology as ontology_routes` to the route imports, in alphabetical position;
- add `app.include_router(ontology_routes.router)` after `app.include_router(library_routes.router)`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest ghostbrain/api/tests/test_ontology_routes.py -q && .venv/bin/python -m pytest ghostbrain/api/tests -q -x`
Expected: PASS. The whole API suite stays green.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/models/ontology.py ghostbrain/api/routes/ontology.py ghostbrain/api/main.py ghostbrain/api/tests/test_ontology_routes.py
git commit -m "feat(ontology): /v1/ontology API for projects, backlog and gold graph"
```

---

### Task 14: Packaging — frozen sidecar, prune and strip, self-check, smoke

**Files:**
- Create: `ghostbrain/ontology/selfcheck.py`, `scripts/prune-arcadedb.py`
- Modify: `ghostbrain/api/__main__.py` (`SUBCOMMANDS` at line 154), `pyproject.toml` (`[project.scripts]`), `packaging/sidecar.spec`, `scripts/smoke-sidecar.py`, `.github/workflows/release.yml`
- Test: `ghostbrain/api/tests/test_ontology_packaging.py`

**Interfaces:**
- Produces:
  - `selfcheck.main() -> int` (prints `ontology selfcheck: OK` and returns 0, or prints the error and returns 1)
  - **CLI:** `ghostbrain-api ontology-selfcheck`
  - `scripts/prune-arcadedb.py <bundle_dir>`. Exits 0 on success, and 2 if no `arcadedb_embedded/jars` is found.

- [ ] **Step 1: Write the failing tests**

`ghostbrain/api/tests/test_ontology_packaging.py`:
```python
import importlib.util
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _load_prune():
    spec = importlib.util.spec_from_file_location("prune_arcadedb", ROOT / "scripts" / "prune-arcadedb.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_prune_removes_unused_jars_and_strips_lz4_natives(tmp_path):
    jars = tmp_path / "_internal" / "arcadedb_embedded" / "jars"
    jars.mkdir(parents=True)
    for name in ("arcadedb-engine-26.10.1.jar", "arcadedb-studio-26.10.1.jar", "undertow-core-2.4.3.Final.jar"):
        with zipfile.ZipFile(jars / name, "w") as z:
            z.writestr("x.class", b"0")
    with zipfile.ZipFile(jars / "lz4-java-1.12.0.jar", "w") as z:
        z.writestr("net/jpountz/util/darwin/aarch64/liblz4-java.dylib", b"mach-o")
        z.writestr("net/jpountz/util/windows/amd64/liblz4-java.dll", b"pe")
        z.writestr("net/jpountz/util/linux/amd64/liblz4-java.so", b"elf")
        z.writestr("net/jpountz/lz4/LZ4Factory.class", b"0")
    assert _load_prune().main([str(tmp_path)]) == 0
    assert sorted(p.name for p in jars.iterdir()) == ["arcadedb-engine-26.10.1.jar", "lz4-java-1.12.0.jar"]
    names = zipfile.ZipFile(jars / "lz4-java-1.12.0.jar").namelist()
    assert "net/jpountz/lz4/LZ4Factory.class" in names
    assert not [n for n in names if n.endswith((".dylib", ".dll"))]


def test_prune_fails_when_no_jars(tmp_path):
    assert _load_prune().main([str(tmp_path)]) == 2


def test_selfcheck_passes(tmp_path, monkeypatch):
    pytest.importorskip("arcadedb_embedded")
    from ghostbrain.ontology import selfcheck  # noqa: PLC0415
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    assert selfcheck.main() == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest ghostbrain/api/tests/test_ontology_packaging.py -q`
Expected: FAIL, because the script and module do not exist.

- [ ] **Step 3: Implement**

`ghostbrain/ontology/selfcheck.py`:
```python
"""`ghostbrain-api ontology-selfcheck`: proves the bundled JRE, Cypher and the
vector index work inside a frozen build (run by scripts/smoke-sidecar.py)."""
from __future__ import annotations

import random
import sys
import tempfile
from pathlib import Path


def main() -> int:
    try:
        import arcadedb_embedded as arc  # noqa: PLC0415

        from ghostbrain.ontology.graph import GoldGraph  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            g = GoldGraph(Path(tmp) / "gold").open()
            with g.transaction():
                g.upsert_node("p", "Project", {"name": "selfcheck"})
                g.upsert_node("r", "Rule", {"name": "r", "value": "1"})
                assert g.upsert_edge("PART_OF", "r", "p", {})
            nodes, _, _ = g.neighbourhood("p", 1)
            assert {n["uid"] for n in nodes} == {"p", "r"}
            db = g._db
            db.schema.get_or_create_vertex_type("Probe")
            rng = random.Random(7)
            vecs = [[rng.random() for _ in range(8)] for _ in range(32)]
            with db.transaction():
                for i, v in enumerate(vecs):
                    vx = db.new_vertex("Probe")
                    vx.set("uid", f"v{i}")
                    vx.set("embedding", arc.to_java_float_array(v))
                    vx.save()
            idx = db.create_vector_index("Probe", "embedding", dimensions=8, id_property="uid")
            hits = idx.find_nearest(vecs[3], k=1)
            assert str(hits[0][0].get("uid")) == "v3"
            g.close()
    except Exception as e:  # noqa: BLE001
        print(f"ontology selfcheck: FAIL: {e}", file=sys.stderr)
        return 1
    print("ontology selfcheck: OK")
    return 0
```

`scripts/prune-arcadedb.py`:
```python
#!/usr/bin/env python3
"""Post-PyInstaller trim of the bundled ArcadeDB runtime.

1. Deletes server-only jars the embedded engine never loads (verified in the
   2026-10-10 spike: a frozen build still passes Cypher + vector checks).
2. Strips the macOS/Windows native libs out of lz4-java: Apple notarization
   rejects unsigned Mach-O files inside archives; lz4-java falls back to its
   pure-Java codec.

Usage: prune-arcadedb.py <sidecar bundle dir>
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

UNUSED_PREFIXES = (
    "arcadedb-studio-", "arcadedb-console-", "arcadedb-graphql-", "arcadedb-postgresw-",
    "arcadedb-redisw-", "arcadedb-mcp-", "arcadedb-bolt-", "arcadedb-server-",
    "undertow-core-", "swagger-core-", "swagger-models-", "swagger-annotations-",
)
STRIP_PREFIXES = ("net/jpountz/util/darwin/", "net/jpountz/util/windows/")


def _strip_jar(jar: Path) -> int:
    tmp = jar.with_suffix(".jar.tmp")
    removed = 0
    with zipfile.ZipFile(jar) as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            if info.filename.startswith(STRIP_PREFIXES):
                removed += 1
                continue
            dst.writestr(info, src.read(info.filename))
    tmp.replace(jar)
    return removed


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    dirs = [p for p in Path(argv[0]).rglob("jars") if p.parent.name == "arcadedb_embedded"]
    if not dirs:
        print(f"prune-arcadedb: no arcadedb_embedded/jars under {argv[0]}", file=sys.stderr)
        return 2
    for jars in dirs:
        for jar in sorted(jars.glob("*.jar")):
            if jar.name.startswith(UNUSED_PREFIXES):
                jar.unlink()
                print(f"pruned {jar.name}")
            elif jar.name.startswith("lz4-java-"):
                print(f"stripped {_strip_jar(jar)} native libs from {jar.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

`ghostbrain/api/__main__.py`: add to `SUBCOMMANDS`:
```python
    "ontology-selfcheck": "ghostbrain.ontology.selfcheck:main",
```
`pyproject.toml` `[project.scripts]`: add
```toml
ghostbrain-ontology-selfcheck = "ghostbrain.ontology.selfcheck:main"
```

`packaging/sidecar.spec`:
- add `import os` next to `import sys` at the top;
- immediately before `a = Analysis(`, add:
```python
# Ontology gold graph (arcadedb-embedded). The bundled JRE and jars are copied
# verbatim as data so PyInstaller never relocates the JRE's dylibs; validated
# frozen on macOS arm64 and Windows in the 2026-10-10 spike. Guarded so builds
# without the `ontology` extra still work.
try:
    import arcadedb_embedded as _adb

    _adb_dir = os.path.dirname(_adb.__file__)
    datas += [
        (os.path.join(_adb_dir, 'jre'), 'arcadedb_embedded/jre'),
        (os.path.join(_adb_dir, 'jars'), 'arcadedb_embedded/jars'),
    ]
    datas += copy_metadata('arcadedb_embedded') + copy_metadata('jpype1')
    hiddenimports += collect_submodules('arcadedb_embedded') + collect_submodules('jpype') + ['_jpype']
except ImportError:
    pass
```

`scripts/smoke-sidecar.py`: add this function and call it from `main()` inside its own `tempfile.TemporaryDirectory()`, after the MCP handshake check, following the existing pattern:
```python
def check_ontology_selfcheck(binary: str, tmp: str) -> None:
    proc = subprocess.run([binary, "ontology-selfcheck"], env=_env(tmp), capture_output=True,
                          text=True, timeout=240)
    if proc.returncode != 0 or "ontology selfcheck: OK" not in proc.stdout:
        raise SystemExit(f"ontology selfcheck failed (rc={proc.returncode}):\n{proc.stdout}\n{proc.stderr}")
    print("ontology selfcheck: OK")
```
Confirm `subprocess` is already imported at the top of `smoke-sidecar.py`; add it if not.

`.github/workflows/release.yml`:
- add `ontology` to the three extras installs: line 142 `".[api,semantic,ontology]"`, line 270 `".[api,semantic,ontology]"`, line 352 `".[api,semantic,recorder-win,ontology]"`;
- in each of the three jobs, immediately after its `Build Python sidecar` step and before the smoke step, insert:
```yaml
      - name: Prune ArcadeDB runtime (unused jars, unsigned lz4 natives)
        run: python scripts/prune-arcadedb.py desktop/resources/sidecar/ghostbrain-api
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest ghostbrain/api/tests/test_ontology_packaging.py tests/test_api_main_dispatch.py -q`
Expected: PASS. The dispatch test confirms `SUBCOMMANDS` matches `[project.scripts]`.

- [ ] **Step 5: Verify the frozen build locally (macOS)**

```bash
uv pip install -q -p .venv/bin/python pyinstaller==6.11.1 "setuptools<82" -e ".[api,semantic,ontology]"
.venv/bin/pyinstaller packaging/sidecar.spec --distpath /tmp/pg-sidecar-dist --workpath /tmp/pg-sidecar-build --noconfirm
.venv/bin/python scripts/prune-arcadedb.py /tmp/pg-sidecar-dist/ghostbrain-api
.venv/bin/python scripts/smoke-sidecar.py /tmp/pg-sidecar-dist/ghostbrain-api/ghostbrain-api
```
Expected: `ontology selfcheck: OK` and `sidecar smoke test: PASS`. Notarization itself is verified in the next release build; record that in the PR description.

- [ ] **Step 6: Commit**

```bash
git add ghostbrain/ontology/selfcheck.py scripts/prune-arcadedb.py ghostbrain/api/__main__.py pyproject.toml packaging/sidecar.spec scripts/smoke-sidecar.py .github/workflows/release.yml ghostbrain/api/tests/test_ontology_packaging.py
git commit -m "build(ontology): bundle ArcadeDB in the sidecar, prune jars, smoke self-check"
```

---

### Task 15: Desktop — widen the graph kinds

**Files:**
- Modify:
  - `desktop/src/shared/api-types.ts` (after `NoteKind` at line 638)
  - `desktop/src/renderer/lib/graph/kinds.ts`, `lib/graph/layout.ts`, `lib/graph/draw.ts`
  - `desktop/src/renderer/components/GraphCanvas.tsx`
  - `desktop/colors_and_type.css` (after line 66)
  - `desktop/src/renderer/__tests__/graph-kinds.test.ts`
- Test: `desktop/src/renderer/__tests__/ontology-graph-layout.test.ts`

**Interfaces:**
- Produces:
  - **Types:** `OntologyKind` and `GraphKind` (in api-types).
  - **Kinds:** `ONTOLOGY_KINDS: readonly OntologyKind[]`; `KIND_COLORS` and `KIND_LABELS` become `Record<GraphKind, string>`.
  - **Layout:** `EgoLike` (structural input type of `layoutEgo`); `SceneNode.kind: GraphKind`.
  - **Canvas:** the `GraphCanvas` prop `hiddenKinds: ReadonlySet<GraphKind>`.

- [ ] **Step 1: Write the failing tests**

`desktop/src/renderer/__tests__/ontology-graph-layout.test.ts`:
```ts
import { describe, expect, it } from 'vitest';
import { layoutEgo } from '../lib/graph/layout';
import type { OntologyGraph } from '../../shared/api-types';

describe('layoutEgo with an ontology graph', () => {
  it('lays out ontology kinds with the focus at the origin', () => {
    const graph: OntologyGraph = {
      focus: 'p1', depth: 2, truncated: false,
      nodes: [
        { path: 'p1', title: 'Orbit', context: 'Orbit', kind: 'project', degree: 2, ghost: false, hop: 0, note_path: null },
        { path: 'r1', title: 'lapse day', context: 'Orbit', kind: 'rule', degree: 2, ghost: false, hop: 1, note_path: null },
        { path: 'a1', title: 'Spec', context: 'Orbit', kind: 'artefact', degree: 1, ghost: false, hop: 2, note_path: '20-contexts/work/spec.md' },
      ],
      edges: [
        { source: 'r1', target: 'p1', weight: 1, kind: 'part_of' },
        { source: 'r1', target: 'a1', weight: 1, kind: 'evidenced_by' },
      ],
    };
    const scene = layoutEgo(graph);
    expect(scene.nodes.map((n) => n.kind)).toEqual(['project', 'rule', 'artefact']);
    expect(scene.focus).toBe(0);
    expect(scene.nodes[0]!.x).toBe(0);
    expect(scene.edges).toHaveLength(2);
  });
});
```

Extend `desktop/src/renderer/__tests__/graph-kinds.test.ts`:
- change the import to include `ONTOLOGY_KINDS`;
- add:
```ts
  it('mirrors the ontology --kind-* tokens and labels every kind', () => {
    const css = readFileSync('colors_and_type.css', 'utf8');
    for (const kind of ONTOLOGY_KINDS) {
      const m = css.match(new RegExp(`--kind-${kind}:\\s*(#[0-9A-Fa-f]{6})`));
      expect(m?.[1]?.toUpperCase(), kind).toBe(KIND_COLORS[kind].toUpperCase());
      expect(KIND_LABELS[kind]).toBeTruthy();
    }
  });
```
- change the first test's label assertion to `expect(Object.keys(KIND_LABELS).sort()).toEqual([...new Set([...NOTE_KINDS, ...ONTOLOGY_KINDS])].sort());`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd desktop && npx vitest run src/renderer/__tests__/ontology-graph-layout.test.ts src/renderer/__tests__/graph-kinds.test.ts`
Expected: FAIL. The `OntologyGraph` type and `ONTOLOGY_KINDS` are missing.

- [ ] **Step 3: Implement**

`desktop/src/shared/api-types.ts`, after `NoteKind`:
```ts
/** Kinds of nodes in a project ontology graph ('decision' is shared with NoteKind). */
export type OntologyKind =
  | 'self' | 'context' | 'project' | 'artefact' | 'concept' | 'rule'
  | 'decision' | 'requirement' | 'system' | 'role' | 'question';

/** Anything the graph canvas can colour. */
export type GraphKind = NoteKind | OntologyKind;

export interface OntologyGraphNode {
  path: string; // node uid
  title: string;
  context: string;
  kind: OntologyKind;
  degree: number;
  ghost: boolean;
  hop: number;
  note_path: string | null;
}

export interface OntologyGraphEdge {
  source: string;
  target: string;
  weight: number;
  kind: string;
}

export interface OntologyGraph {
  focus: string;
  depth: number;
  nodes: OntologyGraphNode[];
  edges: OntologyGraphEdge[];
  truncated: boolean;
}
```

`desktop/colors_and_type.css`, after `--kind-note` (line 66):
```css
  --kind-self:        #F2F3F5;
  --kind-context:     #8C93A8;
  --kind-project:     #4FD1FF;
  --kind-artefact:    #6E7381;
  --kind-concept:     #9AD1FF;
  --kind-rule:        #FFB86B;
  --kind-requirement: #F5E663;
  --kind-system:      #62D69B;
  --kind-role:        #D9A6FF;
  --kind-question:    #FF8FA3;
```

`desktop/src/renderer/lib/graph/kinds.ts`:
- change the import to `import type { GraphKind, NoteKind, OntologyKind } from '../../../shared/api-types';`;
- add after `NOTE_KINDS`:
```ts
export const ONTOLOGY_KINDS: readonly OntologyKind[] = [
  'self', 'context', 'project', 'artefact', 'concept', 'rule',
  'decision', 'requirement', 'system', 'role', 'question',
];
```
- change `KIND_COLORS: Record<NoteKind, string>` to `Record<GraphKind, string>` and add the entries `self: '#F2F3F5', context: '#8C93A8', project: '#4FD1FF', artefact: '#6E7381', concept: '#9AD1FF', rule: '#FFB86B', requirement: '#F5E663', system: '#62D69B', role: '#D9A6FF', question: '#FF8FA3',`;
- change `KIND_LABELS: Record<NoteKind, string>` to `Record<GraphKind, string>` and add `self: 'me', context: 'contexts', project: 'projects', artefact: 'sources', concept: 'concepts', rule: 'rules', requirement: 'requirements', system: 'systems', role: 'roles', question: 'open questions',`.

`desktop/src/renderer/lib/graph/layout.ts`:
- change the import to `import type { GraphKind, VaultGraph } from '../../../shared/api-types';`, dropping `EgoGraph` and `NoteKind` if they're otherwise unused;
- change `kind: NoteKind;` in `SceneNode` to `kind: GraphKind;`;
- add before `layoutEgo`:
```ts
/** Structural input for the ego layout: the A6 ego graph and the ontology graph both fit. */
export interface EgoLike {
  focus: string;
  nodes: ReadonlyArray<{ path: string; title: string; kind: GraphKind; degree: number; ghost: boolean; hop: number }>;
  edges: ReadonlyArray<{ source: string; target: string; weight: number }>;
}
```
- change the signature to `export function layoutEgo(graph: EgoLike, ticks: number = EGO_TICKS): Scene {`.

`desktop/src/renderer/lib/graph/draw.ts`:
- replace `NoteKind` with `GraphKind` in the import and in `hidden: ReadonlySet<...>` (line 27), `isHidden(..., hidden: ReadonlySet<...>)` (line 51), `new Map<..., number[]>()` (line 154) and the parameter at line 231.

`desktop/src/renderer/components/GraphCanvas.tsx`:
- replace `NoteKind` with `GraphKind` in the import and in `hiddenKinds: ReadonlySet<GraphKind>;`;
- add an optional prop `ariaLabel?: string` (default `'link graph'`) and use it in place of the hard-coded canvas `aria-label`.

- [ ] **Step 4: Run the tests, typecheck and lint**

```bash
cd desktop && npx vitest run src/renderer/__tests__/ontology-graph-layout.test.ts src/renderer/__tests__/graph-kinds.test.ts src/renderer/__tests__/graph-layout.test.ts src/renderer/__tests__/graph-draw.test.ts src/renderer/__tests__/GraphCanvas.test.tsx src/renderer/__tests__/LinkGraph.test.tsx
npm run typecheck && npm run lint
```
Expected: all PASS, and typecheck/lint exit 0. `LinkGraph`'s `Set<NoteKind>` still satisfies `ReadonlySet<GraphKind>`.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/shared/api-types.ts desktop/src/renderer/lib/graph desktop/src/renderer/components/GraphCanvas.tsx desktop/colors_and_type.css desktop/src/renderer/__tests__/graph-kinds.test.ts desktop/src/renderer/__tests__/ontology-graph-layout.test.ts
git commit -m "feat(desktop): graph canvas understands ontology node kinds"
```

---

### Task 16: Desktop — Ontology screen (status, enable, backlog, graph)

**Files:**
- Modify:
  - `desktop/src/shared/api-types.ts` (remaining ontology types)
  - `desktop/src/renderer/stores/navigation.ts` (add `'ontology'` to `ScreenId`)
  - `desktop/src/renderer/components/Sidebar.tsx` (add to `NAV_ITEMS`)
  - `desktop/src/renderer/App.tsx` (mount the screen)
- Create:
  - `desktop/src/renderer/lib/api/ontology-hooks.ts`
  - `desktop/src/renderer/stores/ontology-view.ts`
  - `desktop/src/renderer/components/OntologyBacklog.tsx`
  - `desktop/src/renderer/components/OntologyGraph.tsx`
  - `desktop/src/renderer/screens/ontology.tsx`
- Test: `desktop/src/renderer/__tests__/OntologyScreen.test.tsx`

**Interfaces:**
- Consumes: `get`/`post` from `lib/api/client`; `GraphCanvas`, `layoutEgo`; `useNoteView((s) => s.open)`; `TopBar`, `Btn`, `Pill`, `Lucide`, `PanelError`, `PanelEmpty`, `SkeletonRows`, `toast`.
- Produces these hooks, from `ontology-hooks.ts`:
  - **Queries:** `useOntologyStatus()`, `useOntologyProjects()`, `useRegistryProjects()`, `useOntologyBacklog(project)`, `useOntologyExtractStatus(project)`, `useOntologyGraph(project, focus, depth)`.
  - **Mutations:** `useEnableOntologyProject()`, `useOntologyAction(project)`, `useStartOntologyExtract(project)`.
- Also produces the Zustand store `useOntologyView` with state `{ project, tab, focus, depth }` and actions `setProject`, `setTab`, `setFocus`, `setDepth` and `reset`.

- [ ] **Step 1: Write the failing test**

`desktop/src/renderer/__tests__/OntologyScreen.test.tsx`:
```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { OntologyScreen } from '../screens/ontology';
import { useOntologyView } from '../stores/ontology-view';

const request = vi.fn();

const PROJECT = { uuid: 'p1', id: 'work/orbit', name: 'Orbit', context: 'work', seeds: ['Orbit'], bound: 1, pending_items: 2 };
const ITEMS = [
  { id: 1, type: 'binding', created: '2026-10-10', candidate: null,
    artefacts: [{ aid: 'a1', path: '20-contexts/work/a1.md', title: 'Kickoff' }] },
  { id: 2, type: 'candidate', created: '2026-10-10', artefacts: [],
    candidate: { id: 7, kind: 'Rule', name: 'lapse day', statement: 'Today lapse is day 31.', value: '31',
      confidence: 0.8, evidence: [{ aid: 'a1', path: '20-contexts/work/a1.md', title: 'Kickoff', quote: 'day 31', locator: '' }] } },
];

function route(method: string, path: string) {
  if (path === '/v1/ontology/status') return { available: true, reason: null };
  if (path === '/v1/ontology/projects') return [PROJECT];
  if (path === '/v1/projects') return [];
  if (path.startsWith('/v1/ontology/backlog?')) return ITEMS;
  if (path.startsWith('/v1/ontology/projects/p1/extract')) return { running: false, project: null, summary: null, last_error: null };
  if (method === 'POST' && path.startsWith('/v1/ontology/backlog/')) return { ok: true, seq: 5 };
  return null;
}

beforeEach(() => {
  request.mockReset();
  request.mockImplementation(async (method: string, path: string) => ({ ok: true, data: route(method, path) }));
  useOntologyView.getState().reset();
  window.gb = { ...window.gb, api: { request } } as typeof window.gb;
});

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><OntologyScreen /></QueryClientProvider>);
}

describe('OntologyScreen', () => {
  it('lists binding and candidate items for the selected project', async () => {
    renderScreen();
    expect(await screen.findByText('lapse day')).toBeInTheDocument();
    expect(screen.getByText(/1 notes look like Orbit/i)).toBeInTheDocument();
    expect(screen.getByText(/day 31/)).toBeInTheDocument();
  });

  it('ratifies a candidate with an edited value', async () => {
    renderScreen();
    const input = await screen.findByLabelText('value for lapse day');
    fireEvent.change(input, { target: { value: '30' } });
    fireEvent.click(screen.getByRole('button', { name: 'ratify lapse day' }));
    await waitFor(() =>
      expect(request).toHaveBeenCalledWith('POST', '/v1/ontology/backlog/2/action', { action: 'ratify', value: '30' }),
    );
  });

  it('shows the unavailable reason', async () => {
    request.mockImplementation(async (_m: string, path: string) => ({
      ok: true, data: path === '/v1/ontology/status' ? { available: false, reason: 'locked by another process' } : [],
    }));
    renderScreen();
    expect(await screen.findByText(/locked by another process/)).toBeInTheDocument();
  });
});
```

Before writing the screen, check the exact `window.gb.api.request` resolved shape (`{ok, data}` vs throwing) in `desktop/src/renderer/lib/api/client.ts` and match the mock to it. `VaultScreen.test.tsx` uses `{ ok: true, data }`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd desktop && npx vitest run src/renderer/__tests__/OntologyScreen.test.tsx`
Expected: FAIL. `Cannot find module '../screens/ontology'`.

- [ ] **Step 3: Implement**

Append to `desktop/src/shared/api-types.ts`:
```ts
export interface OntologyStatus { available: boolean; reason: string | null }
export interface OntologyProject {
  uuid: string; id: string; name: string; context: string; seeds: string[]; bound: number; pending_items: number;
}
export interface OntologyEvidence { aid: string; path: string; title: string; quote: string; locator: string }
export interface OntologyCandidate {
  id: number; kind: string; name: string; statement: string; value: string | null; confidence: number;
  evidence: OntologyEvidence[];
}
export interface OntologyBindingArtefact { aid: string; path: string; title: string }
export interface OntologyItem {
  id: number; type: 'binding' | 'candidate'; created: string;
  candidate: OntologyCandidate | null; artefacts: OntologyBindingArtefact[];
}
export interface OntologyExtractStatus {
  running: boolean; project: string | null; summary: Record<string, number | string | null> | null; last_error: string | null;
}
export type OntologyActionBody =
  | { action: 'ratify'; name?: string; statement?: string; value?: string | null; exclude?: string[] }
  | { action: 'reject' }
  | { action: 'investigate'; note?: string };
export interface RegistryProject { id: string; context: string; name: string; archived: boolean }
```

`desktop/src/renderer/lib/api/ontology-hooks.ts`:
```ts
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { get, post } from './client';
import type {
  OntologyActionBody, OntologyExtractStatus, OntologyGraph, OntologyItem, OntologyProject,
  OntologyStatus, RegistryProject,
} from '../../../shared/api-types';

const KEY = ['ontology'] as const;

export function useOntologyStatus() {
  return useQuery({ queryKey: [...KEY, 'status'], queryFn: () => get<OntologyStatus>('/v1/ontology/status'), staleTime: 15_000 });
}

export function useOntologyProjects() {
  return useQuery({ queryKey: [...KEY, 'projects'], queryFn: () => get<OntologyProject[]>('/v1/ontology/projects') });
}

export function useRegistryProjects() {
  return useQuery({ queryKey: [...KEY, 'registry'], queryFn: () => get<RegistryProject[]>('/v1/projects') });
}

export function useEnableOntologyProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { project_id: string; seeds: string[] }) => post<OntologyProject>('/v1/ontology/projects/enable', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useOntologyBacklog(project: string | null) {
  return useQuery({
    queryKey: [...KEY, 'backlog', project],
    queryFn: () => get<OntologyItem[]>(`/v1/ontology/backlog?project=${encodeURIComponent(project!)}`),
    enabled: project !== null,
  });
}

export function useOntologyAction(project: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ itemId, body }: { itemId: number; body: OntologyActionBody }) =>
      post<{ ok: boolean; seq: number | null }>(`/v1/ontology/backlog/${itemId}/action`, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: [...KEY, 'backlog', project] });
      void qc.invalidateQueries({ queryKey: [...KEY, 'graph', project] });
      void qc.invalidateQueries({ queryKey: [...KEY, 'projects'] });
    },
  });
}

export function useOntologyExtractStatus(project: string | null) {
  return useQuery({
    queryKey: [...KEY, 'extract', project],
    queryFn: () => get<OntologyExtractStatus>(`/v1/ontology/projects/${project!}/extract`),
    enabled: project !== null,
    refetchInterval: (q) => (q.state.data?.running ? 2_000 : false),
  });
}

export function useStartOntologyExtract(project: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (limit: number) => post<OntologyExtractStatus>(`/v1/ontology/projects/${project!}/extract`, { limit }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: [...KEY, 'extract', project] });
      void qc.invalidateQueries({ queryKey: [...KEY, 'backlog', project] });
    },
  });
}

export function useOntologyGraph(project: string | null, focus: string | null, depth: number) {
  const q = focus ? `&focus=${encodeURIComponent(focus)}` : '';
  return useQuery({
    queryKey: [...KEY, 'graph', project, focus, depth],
    queryFn: () => get<OntologyGraph>(`/v1/ontology/graph?project=${encodeURIComponent(project!)}&depth=${depth}${q}`),
    enabled: project !== null,
    placeholderData: keepPreviousData,
  });
}
```

`desktop/src/renderer/stores/ontology-view.ts`:
```ts
import { create } from 'zustand';

type Tab = 'backlog' | 'graph';

interface OntologyViewState {
  project: string | null;
  tab: Tab;
  focus: string | null;
  depth: 1 | 2 | 3;
  setProject: (project: string | null) => void;
  setTab: (tab: Tab) => void;
  setFocus: (focus: string | null) => void;
  setDepth: (depth: 1 | 2 | 3) => void;
  reset: () => void;
}

const initial = { project: null, tab: 'backlog' as Tab, focus: null, depth: 2 as const };

export const useOntologyView = create<OntologyViewState>((set) => ({
  ...initial,
  setProject: (project) => set({ project, focus: null }),
  setTab: (tab) => set({ tab }),
  setFocus: (focus) => set({ focus }),
  setDepth: (depth) => set({ depth }),
  reset: () => set(initial),
}));
```

`desktop/src/renderer/components/OntologyBacklog.tsx`:
```tsx
import { useState } from 'react';
import { Btn } from './Btn';
import { Lucide } from './Lucide';
import { PanelEmpty, PanelError, SkeletonRows } from './Panel';
import { Pill } from './Pill';
import { toast } from '../stores/toast';
import { useNoteView } from '../stores/note-view';
import {
  useOntologyAction, useOntologyBacklog, useOntologyExtractStatus, useStartOntologyExtract,
} from '../lib/api/ontology-hooks';
import type { OntologyItem } from '../../shared/api-types';

export function OntologyBacklog({ project, projectName }: { project: string; projectName: string }) {
  const backlog = useOntologyBacklog(project);
  const extract = useOntologyExtractStatus(project);
  const start = useStartOntologyExtract(project);
  const running = extract.data?.running ?? false;

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex flex-shrink-0 items-center gap-3 border-b border-hairline px-6 py-3">
        <Btn variant="secondary" size="sm" disabled={running || start.isPending}
             icon={<Lucide name="sparkles" size={13} />}
             onClick={() => start.mutate(25, { onError: (e) => toast.error(String(e)) })}>
          {running ? 'extracting…' : 'extract next 25'}
        </Btn>
        {extract.data?.last_error && <span className="font-mono text-11 text-oxblood">{extract.data.last_error}</span>}
        {extract.data?.summary && !running && (
          <span className="font-mono text-11 text-ink-3">
            last run: {String(extract.data.summary.processed ?? 0)} notes · {String(extract.data.summary.new ?? 0)} new
          </span>
        )}
      </div>
      <div className="flex-1 overflow-y-auto px-2 py-3">
        {backlog.isLoading && <SkeletonRows count={4} height={72} />}
        {backlog.isError && <PanelError message={String(backlog.error)} onRetry={() => void backlog.refetch()} />}
        {backlog.data && backlog.data.length === 0 && (
          <PanelEmpty icon="check-circle" message="nothing waiting for ratification" />
        )}
        {backlog.data?.map((item) =>
          item.type === 'binding'
            ? <BindingRow key={item.id} project={project} projectName={projectName} item={item} />
            : <CandidateRow key={item.id} project={project} item={item} />,
        )}
      </div>
    </div>
  );
}

function BindingRow({ project, projectName, item }: { project: string; projectName: string; item: OntologyItem }) {
  const action = useOntologyAction(project);
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const toggle = (aid: string) =>
    setExcluded((s) => { const n = new Set(s); if (n.has(aid)) n.delete(aid); else n.add(aid); return n; });
  return (
    <div className="mb-2 rounded-r6 border border-hairline px-[14px] py-[10px]">
      <div className="mb-2 flex items-center gap-2">
        <Pill tone="neon">binding</Pill>
        <span className="text-13 text-ink-0">{item.artefacts.length} notes look like {projectName}</span>
      </div>
      <ul className="mb-2 max-h-48 overflow-y-auto">
        {item.artefacts.map((a) => (
          <li key={a.aid} className="flex items-center gap-2 py-[2px] font-mono text-11 text-ink-1">
            <input type="checkbox" aria-label={`include ${a.title}`} checked={!excluded.has(a.aid)} onChange={() => toggle(a.aid)} />
            <span className="truncate">{a.title}</span>
            <span className="truncate text-ink-3">{a.path}</span>
          </li>
        ))}
      </ul>
      <div className="flex gap-2">
        <Btn variant="primary" size="sm" ariaLabel={`ratify binding ${item.id}`}
             onClick={() => action.mutate({ itemId: item.id, body: { action: 'ratify', exclude: [...excluded] } })}>
          ratify {item.artefacts.length - excluded.size}
        </Btn>
        <Btn variant="ghost" size="sm" onClick={() => action.mutate({ itemId: item.id, body: { action: 'reject' } })}>
          reject all
        </Btn>
      </div>
    </div>
  );
}

function CandidateRow({ project, item }: { project: string; item: OntologyItem }) {
  const c = item.candidate!;
  const action = useOntologyAction(project);
  const openNote = useNoteView((s) => s.open);
  const [value, setValue] = useState(c.value ?? '');
  const edited = c.value !== null && value !== c.value;
  const ratify = () =>
    action.mutate(
      { itemId: item.id, body: edited ? { action: 'ratify', value } : { action: 'ratify' } },
      { onError: (e) => toast.error(String(e)) },
    );
  return (
    <div className="mb-2 rounded-r6 border border-hairline px-[14px] py-[10px]">
      <div className="mb-1 flex items-center gap-2">
        <Pill tone="outline">{c.kind}</Pill>
        <span className="text-13 text-ink-0">{c.name}</span>
        <span className="ml-auto font-mono text-9 text-ink-3">{Math.round(c.confidence * 100)}%</span>
      </div>
      <p className="mb-2 text-13 text-ink-1">{c.statement}</p>
      {c.value !== null && (
        <label className="mb-2 flex items-center gap-2 font-mono text-11 text-ink-2">
          value
          <input aria-label={`value for ${c.name}`} value={value} onChange={(e) => setValue(e.target.value)}
                 className="rounded-sm border border-hairline-2 bg-paper px-2 py-[2px] text-ink-0" />
        </label>
      )}
      <ul className="mb-2">
        {c.evidence.map((e, i) => (
          <li key={`${e.aid}-${i}`} className="font-mono text-11 text-ink-2">
            “{e.quote}” —{' '}
            <button type="button" className="text-neon-ink underline" onClick={() => e.path && openNote(e.path)}>
              {e.title}
            </button>
          </li>
        ))}
      </ul>
      <div className="flex gap-2">
        <Btn variant="primary" size="sm" ariaLabel={`ratify ${c.name}`} onClick={ratify}>ratify</Btn>
        <Btn variant="ghost" size="sm" ariaLabel={`reject ${c.name}`}
             onClick={() => action.mutate({ itemId: item.id, body: { action: 'reject' } })}>reject</Btn>
        <Btn variant="ghost" size="sm" ariaLabel={`investigate ${c.name}`}
             onClick={() => action.mutate({ itemId: item.id, body: { action: 'investigate' } })}>investigate</Btn>
      </div>
    </div>
  );
}
```

`desktop/src/renderer/components/OntologyGraph.tsx`:
```tsx
import { useMemo } from 'react';
import { GraphCanvas } from './GraphCanvas';
import { PanelEmpty, PanelError, SkeletonRows } from './Panel';
import { layoutEgo } from '../lib/graph/layout';
import { useOntologyGraph } from '../lib/api/ontology-hooks';
import { useNoteView } from '../stores/note-view';
import { useOntologyView } from '../stores/ontology-view';
import type { GraphKind } from '../../shared/api-types';

const NONE: ReadonlySet<GraphKind> = new Set();

export function OntologyGraph({ project }: { project: string }) {
  const { focus, depth, setFocus, setDepth } = useOntologyView();
  const graph = useOntologyGraph(project, focus, depth);
  const openNote = useNoteView((s) => s.open);
  const scene = useMemo(() => (graph.data ? layoutEgo(graph.data) : null), [graph.data]);
  const notePaths = useMemo(
    () => new Map((graph.data?.nodes ?? []).map((n) => [n.path, n.note_path])),
    [graph.data],
  );

  if (graph.isError) return <PanelError message={String(graph.error)} onRetry={() => void graph.refetch()} />;
  if (!scene) return <SkeletonRows count={3} height={48} />;
  if (scene.nodes.length <= 1) return <PanelEmpty icon="network" message="nothing ratified yet — ratify a binding to start" />;

  return (
    <div className="relative flex flex-1 flex-col overflow-hidden">
      <div className="absolute right-4 top-3 z-10 flex gap-1">
        {([1, 2, 3] as const).map((d) => (
          <button key={d} type="button" onClick={() => setDepth(d)}
                  className={`rounded-sm border px-2 py-[2px] font-mono text-11 ${d === depth ? 'border-neon/30 bg-neon/15 text-neon-ink' : 'border-hairline-2 text-ink-1'}`}>
            depth {d}
          </button>
        ))}
        {focus && (
          <button type="button" onClick={() => setFocus(null)} className="rounded-sm border border-hairline-2 px-2 py-[2px] font-mono text-11 text-ink-1">
            project
          </button>
        )}
      </div>
      <GraphCanvas
        scene={scene}
        hiddenKinds={NONE}
        ariaLabel="ontology graph"
        onRecenter={(node) => setFocus(node.path)}
        onOpen={(node) => {
          const notePath = notePaths.get(node.path);
          if (notePath) openNote(notePath);
        }}
      />
    </div>
  );
}
```

`desktop/src/renderer/screens/ontology.tsx`:
```tsx
import { useEffect, useState } from 'react';
import { Btn } from '../components/Btn';
import { OntologyBacklog } from '../components/OntologyBacklog';
import { OntologyGraph } from '../components/OntologyGraph';
import { PanelEmpty, PanelError, SkeletonRows } from '../components/Panel';
import { TopBar } from '../components/TopBar';
import { toast } from '../stores/toast';
import { useOntologyView } from '../stores/ontology-view';
import {
  useEnableOntologyProject, useOntologyProjects, useOntologyStatus, useRegistryProjects,
} from '../lib/api/ontology-hooks';

export function OntologyScreen() {
  const status = useOntologyStatus();
  const projects = useOntologyProjects();
  const { project, tab, setProject, setTab } = useOntologyView();
  const [enabling, setEnabling] = useState(false);

  useEffect(() => {
    if (project === null && projects.data && projects.data.length > 0) setProject(projects.data[0]!.uuid);
  }, [project, projects.data, setProject]);

  const current = projects.data?.find((p) => p.uuid === project) ?? null;

  return (
    <div className="flex flex-1 flex-col overflow-hidden bg-paper">
      <TopBar
        title="ontology"
        subtitle={current ? `${current.name} · ${current.bound} sources · ${current.pending_items} waiting` : 'ratified project knowledge'}
        right={
          <div className="flex items-center gap-2">
            {projects.data && projects.data.length > 0 && (
              <select aria-label="ontology project" value={project ?? ''} onChange={(e) => setProject(e.target.value)}
                      className="rounded-sm border border-hairline-2 bg-paper px-2 py-1 font-mono text-11 text-ink-0">
                {projects.data.map((p) => <option key={p.uuid} value={p.uuid}>{p.name}</option>)}
              </select>
            )}
            <Btn variant="secondary" size="sm" onClick={() => setEnabling((v) => !v)}>enable project</Btn>
          </div>
        }
      />
      {status.data && !status.data.available && (
        <PanelError message={`ontology unavailable: ${status.data.reason ?? 'unknown reason'}`} onRetry={() => void status.refetch()} />
      )}
      {enabling && <EnableForm onDone={() => setEnabling(false)} />}
      {projects.isLoading && <SkeletonRows count={3} height={48} />}
      {projects.data && projects.data.length === 0 && !enabling && (
        <PanelEmpty icon="network" message="no project has an ontology yet" />
      )}
      {current && (
        <>
          <div className="flex flex-shrink-0 items-center gap-[6px] border-b border-hairline px-6 py-3" role="tablist">
            {(['backlog', 'graph'] as const).map((t) => (
              <button key={t} role="tab" aria-selected={tab === t} type="button" onClick={() => setTab(t)}
                      className={`rounded-sm border px-[10px] py-1 font-mono text-11 ${tab === t ? 'border-neon/30 bg-neon/15 text-neon-ink' : 'border-hairline-2 text-ink-1'}`}>
                {t}
              </button>
            ))}
          </div>
          {tab === 'backlog'
            ? <OntologyBacklog project={current.uuid} projectName={current.name} />
            : <OntologyGraph project={current.uuid} />}
        </>
      )}
    </div>
  );
}

function EnableForm({ onDone }: { onDone: () => void }) {
  const registry = useRegistryProjects();
  const enable = useEnableOntologyProject();
  const setProject = useOntologyView((s) => s.setProject);
  const [projectId, setProjectId] = useState('');
  const [seeds, setSeeds] = useState('');
  const submit = () =>
    enable.mutate(
      { project_id: projectId, seeds: seeds.split(',').map((s) => s.trim()).filter(Boolean) },
      {
        onSuccess: (p) => { setProject(p.uuid); onDone(); },
        onError: (e) => toast.error(String(e)),
      },
    );
  return (
    <div className="flex flex-shrink-0 items-end gap-3 border-b border-hairline bg-vellum px-6 py-3">
      <label className="flex flex-col font-mono text-11 text-ink-2">
        project
        <select aria-label="project to enable" value={projectId} onChange={(e) => setProjectId(e.target.value)}
                className="rounded-sm border border-hairline-2 bg-paper px-2 py-1 text-ink-0">
          <option value="">choose…</option>
          {(registry.data ?? []).filter((p) => !p.archived).map((p) => <option key={p.id} value={p.id}>{p.name} ({p.context})</option>)}
        </select>
      </label>
      <label className="flex flex-1 flex-col font-mono text-11 text-ink-2">
        seed terms (comma-separated)
        <input aria-label="seed terms" value={seeds} onChange={(e) => setSeeds(e.target.value)} placeholder="Orbit, unit-linked"
               className="rounded-sm border border-hairline-2 bg-paper px-2 py-1 text-ink-0" />
      </label>
      <Btn variant="primary" size="sm" disabled={!projectId || !seeds.trim() || enable.isPending} onClick={submit}>
        {enable.isPending ? 'scanning…' : 'enable'}
      </Btn>
    </div>
  );
}
```

Navigation:
- `stores/navigation.ts`: add `| 'ontology'` to `ScreenId`.
- `components/Sidebar.tsx`: add `{ id: 'ontology', icon: 'network', label: 'ontology' }` to `NAV_ITEMS`, after the `vault` entry.
- `App.tsx`: add `import { OntologyScreen } from './screens/ontology';` and `{active === 'ontology' && <OntologyScreen />}` next to the vault screen.

Component import paths: before running, confirm the export locations of `Btn`, `Pill`, `PanelError`, `PanelEmpty`, `SkeletonRows`, `TopBar`, `Lucide` and `toast` with `grep -rn "export function Btn\|export function PanelError\|export function SkeletonRows\|export function Pill\|export const toast" desktop/src/renderer`. Fix the import lines to match, keeping the components themselves unchanged.

- [ ] **Step 4: Run the tests, typecheck and lint**

```bash
cd desktop && npx vitest run src/renderer/__tests__/OntologyScreen.test.tsx && npm test && npm run typecheck && npm run lint
```
Expected: all PASS. The full vitest suite stays green, and typecheck/lint exit 0.

- [ ] **Step 5: Commit**

```bash
git add desktop/src
git commit -m "feat(desktop): Ontology screen with backlog and gold graph"
```

---

### Task 17: Dev-build verification against a Orbit sandbox (manual, required)

**Files:** none committed. Everything lives in a scratch dir.

This proves the milestone's done-when: *ratified Orbit facts appear in Poltergeist's graph view in a dev build, linked to their artefacts*.

- [ ] **Step 1: Build a Orbit-only sandbox vault.** The real vault is 4.8 GB and the dev build must not write into it.

```bash
SB=/tmp/pg-ontology-sandbox && rm -rf "${SB:?}" && mkdir -p "$SB/vault/90-meta" "$SB/userdata" "$SB/state" "$SB/chats" "$SB/ontology"
REAL=~/ghostbrain/vault
cp "$REAL/90-meta/routing.yaml" "$REAL/90-meta/projects.json" "$SB/vault/90-meta/"
grep -rli -E "\bOrbit\b" "$REAL/20-contexts" --include='*.md' | head -40 | while read -r f; do
  rel="${f#$REAL/}"; mkdir -p "$SB/vault/$(dirname "$rel")"; cp "$f" "$SB/vault/$rel"; done
python3 - "$REAL/90-meta/config.yaml" "$SB/vault/90-meta/config.yaml" <<'EOF'
import sys, yaml
src = yaml.safe_load(open(sys.argv[1])) or {}
yaml.safe_dump({"llm": src.get("llm", {})}, open(sys.argv[2], "w"))
EOF
printf '{"vaultPath":"%s","schedulerEnabled":false,"onboardingComplete":true}\n' "$SB/vault" > "$SB/userdata/config.json"
find "$SB/vault" -name '*.md' | wc -l
```
Expected: about 40 notes copied. If no Orbit project exists in `projects.json`, create one from the app's project settings once it's running (context: whichever context holds the notes).

- [ ] **Step 2: Run the dev build sandboxed**

```bash
cd desktop   # from the worktree root
GHOSTBRAIN_STATE_DIR=$SB/state GHOSTBRAIN_CHATS_DIR=$SB/chats GHOSTBRAIN_ONTOLOGY_DIR=$SB/ontology VAULT_PATH=$SB/vault \
  npx electron-vite dev -- --user-data-dir=$SB/userdata
```

- [ ] **Step 3: Walk the loop and record what you see**
1. Open **ontology** in the sidebar. The status must not show "unavailable"; the first open starts the JVM (~3 s).
2. Click **enable project**, pick Orbit, and enter seeds `Orbit`. A binding item lists the Orbit notes. Untick one, then **ratify**.
3. **Graph** tab: the Orbit project node sits at the centre, linked to the bound artefact nodes. Double-clicking an artefact opens its note.
4. **Backlog** tab: click **extract next 25**. Wait for the run summary; candidate items appear with quotes. Clicking a quote's source opens the note.
5. Ratify 3–5 candidates, editing one value first. Reject one.
6. **Graph** tab: the ratified rule, decision and concept nodes appear, linked to Orbit and to their evidence artefacts.
7. Check `$SB/vault/20-contexts/<ctx>/projects/<slug>/ontology/` contains generated notes, then click **enable project** → the same project again. The new binding item must **not** list any `ontology/` notes (Review Focus 1).

- [ ] **Step 4: Prove rebuild-from-log on the real data**

```bash
curl -s -X POST -H "Authorization: Bearer $(python3 -c "import json;print(json.load(open('$SB/state/sidecar.json'))['token'])")" \
  "http://127.0.0.1:$(python3 -c "import json;print(json.load(open('$SB/state/sidecar.json'))['port'])")/v1/ontology/rebuild"
```
Expected: `{"applied": N}`, and the graph tab shows the same nodes after a refresh. If `sidecar.json` lives elsewhere, find the port and token in `$SB/state` or the dev console output.

- [ ] **Step 5: Stop the dev build and report.** Give the user screenshots of the backlog and graph tabs, the extraction summary numbers (processed / new / merged / discarded / failed), and anything that misbehaved. Do not delete `$SB` until the user has looked.

---

## Self-review notes (done while writing)

- **Spec coverage (Milestone 1):**

  | Spec item | Task |
  |---|---|
  | SQLite store and log | 2 |
  | ArcadeDB adapter, projector and rebuild | 4, 5, 6 |
  | Stable UUIDs | 3 |
  | Scoping and bulk binding | 7, 11, 13 |
  | Extraction and triage (dup/rejection), manual trigger, ~25 notes | 8, 9, 10, 13 |
  | Plain backlog list | 11, 16 |
  | Graph tab on A6 | 15, 16 |
  | Markdown projection | 12 |
  | Packaging incl. lz4 strip | 14 |
  | Done-when | 17 |

  Deliberate M1 simplification: **investigate** parks the item. The spec's linked jot/task arrives in milestone 2, alongside the other backlog upgrades.
- **Types:** the `revert` payload carries an optional `project` (used by Task 12 and Task 13; the projector ignores it). The graph API's `note_path` (snake_case) is used consistently in the Python models, TS types, hooks and components.
- **Review Focus pins:** 1 → Task 7 `test_generated_ontology_notes_are_never_artefacts` (+ Task 17 step 3.7); 2 → Task 6 `test_status_reports_lock_without_raising` and `test_non_ontology_routes_unaffected_by_locked_graph`; 3 → Task 10 `test_missing_source_is_recorded_and_run_continues`; 4 → Task 8 `test_quote_match_tolerates_whitespace_case_and_curly_quotes` and `test_paraphrased_quote_is_discarded`; 5 → Task 11 `test_double_ratify_conflicts_and_logs_once` and Task 13's 409 assertion.
