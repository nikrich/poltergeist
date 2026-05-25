# Meeting Prep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a T-15min native macOS notification before each calendar meeting and a prep panel in the Meetings tab that shows event detail, semantically-related vault items, and an LLM-generated brief.

**Architecture:** Python sidecar generates briefs (`build_prep`) and caches them on disk; a scheduler job pre-warms the next upcoming meeting; FastAPI exposes `GET /v1/meetings/prep/{event_id}` + `POST /v1/meetings/prep/{event_id}/prewarm`. The Electron main process polls `/v1/agenda` and fires the native `Notification` once per event; click handler IPC-pings the renderer to navigate to the Meetings tab and auto-expand the matching row. Renderer renders the prep panel via a new `<MeetingPrep />` component sourced through a TanStack Query hook.

**Tech Stack:** Python 3.11 + FastAPI + Pydantic for the sidecar; existing `ghostbrain.llm.client` (shells out to `claude -p`) for the LLM; existing `ghostbrain.api.repo.search` for semantic lookup; Electron + React 18 + TanStack Query + Zustand for the desktop app; vitest + React Testing Library for renderer tests; pytest for backend.

**Spec:** `docs/superpowers/specs/2026-05-25-meeting-prep-design.md`

---

## File Structure

**Backend (Python — sidecar):**
- Create: `ghostbrain/worker/meeting_prep.py` — `build_prep(event_id) -> Prep`. Pure builder: reads the calendar note, queries the semantic index for related items, calls `claude -p`.
- Create: `ghostbrain/api/repo/meeting_prep.py` — disk cache (get/set) + `prewarm` (background thread).
- Modify: `ghostbrain/api/models/meeting.py` — add `Prep`, `RelatedItem`, `EventSnapshot` Pydantic models.
- Modify: `ghostbrain/api/routes/meetings.py` — add `GET /v1/meetings/prep/{event_id}` and `POST /v1/meetings/prep/{event_id}/prewarm`.
- Modify: `ghostbrain/scheduler_jobs.py` — register a 60-second job that pre-warms the next-upcoming meeting.
- Create: `tests/test_meeting_prep.py` — unit tests for `build_prep` + cache repo.
- Create: `tests/test_route_meeting_prep.py` — integration tests for the new HTTP endpoints.
- Create: `tests/test_scheduler_meeting_prep_prewarm.py` — unit test for the "should prewarm" predicate.

**Frontend (Electron main process):**
- Create: `desktop/src/main/meeting-notifier.ts` — agenda poll loop + `shouldFireNow` pure helper + notified-set persistence + click handler.
- Modify: `desktop/src/main/index.ts` — wire up the notifier alongside the existing tray installer.
- Modify: `desktop/src/preload/index.ts` (no API surface change — the renderer just listens via the existing `gb.on(channel, listener)` bridge, which already covers the new `meetings:openPrep` channel).
- Create: `desktop/src/main/__tests__/meeting-notifier.test.ts` — unit test for `shouldFireNow`.

**Frontend (renderer):**
- Modify: `desktop/src/shared/api-types.ts` — add `Prep`, `RelatedItem`, `EventSnapshot` TypeScript types mirroring the Pydantic models.
- Modify: `desktop/src/renderer/lib/api/hooks.ts` — add `useMeetingPrep(eventId: string | null)`.
- Modify: `desktop/src/renderer/stores/meeting.ts` — add `selectedEventId` + `setSelectedEventId` (kept tiny — separate Zustand slice if it grows).
- Create: `desktop/src/renderer/components/MeetingPrep.tsx` — renders the three-section prep panel (event detail, brief, related).
- Create: `desktop/src/renderer/components/UpcomingMeetings.tsx` — today's upcoming-meeting list with inline expansion.
- Modify: `desktop/src/renderer/screens/meetings.tsx` — render `<UpcomingMeetings />` between the hero card and `MeetingHistory`.
- Modify: `desktop/src/renderer/App.tsx` — subscribe to `meetings:openPrep` IPC and route to the Meetings screen with the right `selectedEventId`.
- Create: `desktop/src/renderer/__tests__/MeetingPrep.test.tsx` — RTL tests for loading / success / brief-error / empty-related states.
- Create: `desktop/src/renderer/__tests__/UpcomingMeetings.test.tsx` — RTL tests for the list + inline expansion.

---

## Task 1: Pydantic models for the Prep response

**Files:**
- Modify: `ghostbrain/api/models/meeting.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_meeting_prep.py` (new file):

```python
"""Tests for the meeting-prep models, builder, and cache repo."""
from __future__ import annotations

from ghostbrain.api.models.meeting import EventSnapshot, Prep, RelatedItem


def test_prep_model_round_trips():
    snap = EventSnapshot(
        title="Eng standup",
        start="2026-05-25T09:00:00+02:00",
        end="2026-05-25T09:30:00+02:00",
        with_=["alice@example.com", "bob@example.com"],
        location="Zoom",
        description="weekly sync",
        hash="abc123",
    )
    rel = RelatedItem(
        path="20-contexts/sanlam/meetings/2026-05-18-eng-standup.md",
        title="Eng standup 2026-05-18",
        source="meeting",
        snippet="discussed sprint plan",
        score=0.81,
    )
    prep = Prep(
        event_id="20260525T090000-eng-standup",
        brief="Continuing last week's sprint plan thread.",
        related=[rel],
        event_snapshot=snap,
        generated_at="2026-05-25T08:55:00+02:00",
        error=None,
    )
    dumped = prep.model_dump(by_alias=True)
    assert dumped["eventId"] == "20260525T090000-eng-standup"
    assert dumped["related"][0]["path"].endswith("-eng-standup.md")
    assert dumped["eventSnapshot"]["with"] == ["alice@example.com", "bob@example.com"]
    assert dumped["generatedAt"] == "2026-05-25T08:55:00+02:00"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_meeting_prep.py::test_prep_model_round_trips -v`

Expected: FAIL with `ImportError: cannot import name 'Prep' from 'ghostbrain.api.models.meeting'`.

- [ ] **Step 3: Write the models**

Append to `ghostbrain/api/models/meeting.py`:

```python
from pydantic import Field


class EventSnapshot(BaseModel):
    """Frozen view of a calendar event used for cache invalidation."""
    model_config = ConfigDict(populate_by_name=True)

    title: str
    start: str
    end: str
    with_: list[str] = Field(default_factory=list, alias="with")
    location: str = ""
    description: str = ""
    hash: str


class RelatedItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    path: str
    title: str
    source: str
    snippet: str
    score: float


class Prep(BaseModel):
    """Prep notes for an upcoming meeting."""
    model_config = ConfigDict(populate_by_name=True)

    event_id: str = Field(alias="eventId")
    brief: str | None = None
    related: list[RelatedItem] = Field(default_factory=list)
    event_snapshot: EventSnapshot = Field(alias="eventSnapshot")
    generated_at: str = Field(alias="generatedAt")
    error: str | None = None
```

`Field`, `BaseModel`, and `ConfigDict` already import at the top of the existing file — only add `Field` to that line.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_meeting_prep.py::test_prep_model_round_trips -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_meeting_prep.py ghostbrain/api/models/meeting.py
git commit -m "feat(meeting-prep): add Prep / RelatedItem / EventSnapshot models"
```

---

## Task 2: Vault helpers — resolve event id back to its calendar note

**Files:**
- Modify: `ghostbrain/worker/meeting_prep.py` (new file)
- Modify: `tests/test_meeting_prep.py`

The agenda repo uses `path.stem` as the event id. We need the reverse lookup, plus a hash function over the cache-invalidation fields.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_meeting_prep.py`:

```python
import textwrap
from pathlib import Path

import pytest

from ghostbrain.worker import meeting_prep as mp


@pytest.fixture()
def vault(tmp_path, monkeypatch):
    """Create a fake vault with one calendar event note and one prior meeting."""
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    cal = tmp_path / "20-contexts" / "sanlam" / "calendar"
    cal.mkdir(parents=True)
    (cal / "20260525T090000-eng-standup.md").write_text(textwrap.dedent("""\
        ---
        title: Eng standup
        start: 2026-05-25T09:00:00+02:00
        end: 2026-05-25T09:30:00+02:00
        with:
          - alice@example.com
          - bob@example.com
        location: Zoom
        description: weekly sync — sprint plan
        ---
        """))
    return tmp_path


def test_resolve_event_path_finds_note(vault):
    path = mp.resolve_event_path("20260525T090000-eng-standup")
    assert path is not None
    assert path.name == "20260525T090000-eng-standup.md"


def test_resolve_event_path_missing_returns_none(vault):
    assert mp.resolve_event_path("does-not-exist") is None


def test_event_hash_changes_when_description_changes(vault):
    h1 = mp.event_hash({"start": "x", "end": "y", "description": "v1"})
    h2 = mp.event_hash({"start": "x", "end": "y", "description": "v2"})
    h3 = mp.event_hash({"start": "x", "end": "y", "description": "v1"})
    assert h1 != h2
    assert h1 == h3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_meeting_prep.py::test_resolve_event_path_finds_note -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.worker.meeting_prep'`.

- [ ] **Step 3: Implement the helpers**

Create `ghostbrain/worker/meeting_prep.py`:

```python
"""Meeting-prep builder.

Composes a prep payload for a single calendar event by reading its
calendar note, finding related items via the semantic index, and
asking ``claude -p`` for a short brief.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

from ghostbrain.paths import vault_path

log = logging.getLogger("ghostbrain.worker.meeting_prep")


def resolve_event_path(event_id: str) -> Path | None:
    """Find the calendar note that produced this event id.

    Agenda uses ``path.stem`` as the id, so we reverse-glob over all
    ``20-contexts/*/calendar/*.md`` files. Returns ``None`` if the event
    has been deleted from the vault.
    """
    vault = vault_path()
    if not vault.exists():
        return None
    target = f"{event_id}.md"
    for path in vault.glob("20-contexts/*/calendar/*.md"):
        if path.name == target:
            return path
    return None


def event_hash(fields: dict[str, Any]) -> str:
    """Stable hash over the cache-busting fields."""
    payload = "|".join(
        str(fields.get(k, "")) for k in ("start", "end", "description")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_meeting_prep.py -v -k "resolve_event_path or event_hash"`

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/worker/meeting_prep.py tests/test_meeting_prep.py
git commit -m "feat(meeting-prep): resolve event id to calendar note + hash helper"
```

---

## Task 3: `build_prep` — happy path with mocked LLM and semantic search

**Files:**
- Modify: `ghostbrain/worker/meeting_prep.py`
- Modify: `tests/test_meeting_prep.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_meeting_prep.py`:

```python
from unittest.mock import MagicMock


def test_build_prep_happy_path(vault, monkeypatch):
    """build_prep loads event, queries semantic index, calls LLM, returns Prep."""
    # Mock semantic search to return one related item.
    fake_search = MagicMock(return_value={
        "query": "Eng standup",
        "total": 1,
        "items": [{
            "path": "20-contexts/sanlam/meetings/2026-05-18-eng-standup.md",
            "title": "Eng standup 2026-05-18",
            "snippet": "agreed to spike auth",
            "score": 0.82,
        }],
    })
    monkeypatch.setattr(mp, "_semantic_search", fake_search)

    # Mock the LLM to return a fixed brief.
    fake_llm = MagicMock()
    fake_llm.return_value = MagicMock(text="Continuing the auth spike.")
    monkeypatch.setattr(mp, "_llm_run", fake_llm)

    prep = mp.build_prep("20260525T090000-eng-standup")

    assert prep.event_id == "20260525T090000-eng-standup"
    assert prep.brief == "Continuing the auth spike."
    assert prep.error is None
    assert len(prep.related) == 1
    assert prep.related[0].title == "Eng standup 2026-05-18"
    assert prep.event_snapshot.title == "Eng standup"
    assert prep.event_snapshot.with_ == ["alice@example.com", "bob@example.com"]
    # The brief was generated, so the LLM was called exactly once.
    assert fake_llm.call_count == 1
    # Two queries to the semantic index (title-based and attendee-based).
    assert fake_search.call_count >= 1


def test_build_prep_unknown_event_raises(vault, monkeypatch):
    with pytest.raises(mp.UnknownEvent):
        mp.build_prep("not-a-real-id")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_meeting_prep.py::test_build_prep_happy_path -v`

Expected: FAIL with `AttributeError: module 'ghostbrain.worker.meeting_prep' has no attribute 'build_prep'`.

- [ ] **Step 3: Implement `build_prep`**

Append to `ghostbrain/worker/meeting_prep.py`:

```python
from datetime import datetime, timezone

import frontmatter

from ghostbrain.api.models.meeting import EventSnapshot, Prep, RelatedItem
from ghostbrain.api.repo.search import search as _semantic_search
from ghostbrain.llm.client import (
    LLMError,
    LLMTimeout,
    run as _llm_run,
)

LLM_MODEL = "haiku"
LLM_TIMEOUT_S = 30
LLM_BUDGET_USD = 0.05
RELATED_LIMIT = 8


class UnknownEvent(LookupError):
    """Raised when an event id has no matching calendar note in the vault."""


def _load_event_fields(path: Path) -> dict[str, Any]:
    post = frontmatter.load(path)
    fm = post.metadata or {}
    return {
        "title": str(fm.get("title") or ""),
        "start": str(fm.get("start") or ""),
        "end": str(fm.get("end") or ""),
        "with": [str(x) for x in (fm.get("with") or [])],
        "location": str(fm.get("location") or ""),
        "description": str(fm.get("description") or ""),
    }


def _related_for(fields: dict[str, Any]) -> list[RelatedItem]:
    """Two-query strategy: title + attendees. De-dup and keep top N by score."""
    seen: dict[str, RelatedItem] = {}

    title_q = fields["title"].strip()
    if title_q:
        for hit in _semantic_search(title_q, limit=RELATED_LIMIT).get("items", []):
            key = hit["path"]
            if key not in seen:
                seen[key] = RelatedItem(
                    path=hit["path"],
                    title=hit["title"],
                    source=_source_for(hit["path"]),
                    snippet=hit["snippet"],
                    score=float(hit["score"]),
                )

    attendees = " ".join(fields.get("with") or [])
    if attendees:
        for hit in _semantic_search(attendees, limit=RELATED_LIMIT).get("items", []):
            key = hit["path"]
            if key in seen:
                continue
            seen[key] = RelatedItem(
                path=hit["path"],
                title=hit["title"],
                source=_source_for(hit["path"]),
                snippet=hit["snippet"],
                score=float(hit["score"]),
            )

    # Drop the calendar event itself from its own related list.
    title_lower = fields["title"].lower().strip()
    items = [
        ri for ri in seen.values()
        if "/calendar/" not in ri.path or ri.title.lower().strip() != title_lower
    ]
    items.sort(key=lambda r: r.score, reverse=True)
    return items[:RELATED_LIMIT]


def _source_for(rel_path: str) -> str:
    """Derive a source tag from a vault-relative path."""
    for segment in ("calendar", "meetings", "email", "gmail", "slack", "jira",
                    "confluence", "github", "joplin"):
        if f"/{segment}/" in rel_path:
            return "email" if segment == "gmail" else segment
    return "note"


PROMPT_TEMPLATE = """You are preparing a 1-paragraph brief (max 60 words) for an upcoming meeting.

Meeting:
- Title: {title}
- When: {start} -> {end}
- Attendees: {attendees}
- Location: {location}
- Invite description: {description}

Related context from the user's vault (most relevant first):
{related_block}

Write the brief in plain prose. Focus on what's likely on the table and any unresolved threads from prior context. No filler, no bullet points, no greetings. If there is no useful context, say so in one sentence.
"""


def _build_prompt(fields: dict[str, Any], related: list[RelatedItem]) -> str:
    if related:
        related_block = "\n".join(
            f"- [{r.source}] {r.title} -- {r.snippet}" for r in related
        )
    else:
        related_block = "(no related context found)"
    return PROMPT_TEMPLATE.format(
        title=fields["title"] or "(untitled)",
        start=fields["start"],
        end=fields["end"],
        attendees=", ".join(fields["with"]) or "(none on invite)",
        location=fields["location"] or "(unspecified)",
        description=fields["description"] or "(empty)",
        related_block=related_block,
    )


def build_prep(event_id: str) -> Prep:
    """Compose a Prep payload for ``event_id``.

    Raises ``UnknownEvent`` if the calendar note is gone. LLM failures
    are captured in ``Prep.error`` rather than raised — the caller still
    gets event detail and related items.
    """
    path = resolve_event_path(event_id)
    if path is None:
        raise UnknownEvent(event_id)
    fields = _load_event_fields(path)
    snapshot = EventSnapshot(
        title=fields["title"],
        start=fields["start"],
        end=fields["end"],
        with_=fields["with"],
        location=fields["location"],
        description=fields["description"],
        hash=event_hash(fields),
    )

    related = _related_for(fields)
    brief: str | None = None
    error: str | None = None
    try:
        result = _llm_run(
            _build_prompt(fields, related),
            model=LLM_MODEL,
            timeout_s=LLM_TIMEOUT_S,
            budget_usd=LLM_BUDGET_USD,
        )
        brief = (result.text or "").strip() or None
    except (LLMError, LLMTimeout) as e:
        log.warning("meeting-prep LLM failed for %s: %s", event_id, e)
        error = f"{type(e).__name__}: {e}"

    return Prep(
        event_id=event_id,
        brief=brief,
        related=related,
        event_snapshot=snapshot,
        generated_at=datetime.now(timezone.utc).isoformat(),
        error=error,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_meeting_prep.py -v`

Expected: all PASS (5 tests at this point).

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/worker/meeting_prep.py tests/test_meeting_prep.py
git commit -m "feat(meeting-prep): build_prep happy path with semantic + LLM"
```

---

## Task 4: `build_prep` — LLM error path returns Prep with `error`

**Files:**
- Modify: `tests/test_meeting_prep.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_meeting_prep.py`:

```python
from ghostbrain.llm.client import LLMTimeout


def test_build_prep_llm_timeout_returns_prep_with_error(vault, monkeypatch):
    monkeypatch.setattr(mp, "_semantic_search", MagicMock(return_value={"items": []}))
    monkeypatch.setattr(
        mp,
        "_llm_run",
        MagicMock(side_effect=LLMTimeout("claude -p timed out after 30s")),
    )

    prep = mp.build_prep("20260525T090000-eng-standup")
    assert prep.brief is None
    assert prep.error is not None
    assert "Timeout" in prep.error
    assert prep.event_snapshot.title == "Eng standup"  # snapshot still built
    assert prep.related == []
```

- [ ] **Step 2: Run test to verify it passes**

Already implemented in Task 3 — verify:

Run: `pytest tests/test_meeting_prep.py::test_build_prep_llm_timeout_returns_prep_with_error -v`

Expected: PASS. (Sanity check that Task 3's error handling really works.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_meeting_prep.py
git commit -m "test(meeting-prep): pin LLM-timeout error path"
```

---

## Task 5: Cache repo — read/write with hash-based invalidation

**Files:**
- Create: `ghostbrain/api/repo/meeting_prep.py`
- Modify: `tests/test_meeting_prep.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_meeting_prep.py`:

```python
import json

from ghostbrain.api.repo import meeting_prep as repo


def test_cache_write_then_read(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path))
    snap = EventSnapshot(
        title="t", start="s", end="e", with_=[], location="", description="", hash="h1",
    )
    p = Prep(
        event_id="evt1", brief="hi", related=[], event_snapshot=snap,
        generated_at="2026-05-25T00:00:00+00:00", error=None,
    )
    repo.set_prep(p)
    got = repo.get_prep("evt1", expected_hash="h1")
    assert got is not None
    assert got.brief == "hi"


def test_cache_returns_none_when_hash_mismatches(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path))
    snap = EventSnapshot(
        title="t", start="s", end="e", with_=[], location="", description="", hash="oldhash",
    )
    repo.set_prep(Prep(
        event_id="evt1", brief="hi", related=[], event_snapshot=snap,
        generated_at="2026-05-25T00:00:00+00:00", error=None,
    ))
    # Same event_id, but the live event's fields produce a different hash.
    assert repo.get_prep("evt1", expected_hash="newhash") is None


def test_cache_returns_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path))
    assert repo.get_prep("never-written", expected_hash="x") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_meeting_prep.py::test_cache_write_then_read -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.api.repo.meeting_prep'`.

- [ ] **Step 3: Implement the cache repo**

Create `ghostbrain/api/repo/meeting_prep.py`:

```python
"""On-disk cache for meeting-prep payloads.

Cache files live under ``state_dir() / "meeting-prep" / <event_id>.json``.
``get_prep`` accepts the *expected* event-snapshot hash so callers can
invalidate stale entries when the underlying calendar event changes.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

from ghostbrain.api.models.meeting import Prep
from ghostbrain.paths import state_dir

log = logging.getLogger("ghostbrain.api.repo.meeting_prep")

_executor_lock = threading.Lock()
_inflight: set[str] = set()


def _cache_dir() -> Path:
    d = state_dir() / "meeting-prep"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_path(event_id: str) -> Path:
    safe = event_id.replace("/", "_").replace("\\", "_")
    return _cache_dir() / f"{safe}.json"


def get_prep(event_id: str, *, expected_hash: str) -> Prep | None:
    """Return the cached Prep iff present and its snapshot hash matches."""
    path = _cache_path(event_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text("utf-8"))
        prep = Prep.model_validate(payload)
    except Exception as e:  # noqa: BLE001
        log.warning("could not parse cached prep %s: %s", path, e)
        return None
    if prep.event_snapshot.hash != expected_hash:
        return None
    return prep


def set_prep(prep: Prep) -> None:
    """Atomically write a Prep to disk."""
    path = _cache_path(prep.event_id)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(prep.model_dump(by_alias=True), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def prewarm(event_id: str, *, builder=None) -> bool:
    """Kick off ``build_prep`` in a background thread.

    Returns True if a new worker was launched, False if one is already
    running for this event id. Deliberately does not block the caller —
    the cache file lands asynchronously.
    """
    # Lazy import to break the circular dep (the builder imports models).
    if builder is None:
        from ghostbrain.worker.meeting_prep import build_prep
        builder = build_prep

    with _executor_lock:
        if event_id in _inflight:
            return False
        _inflight.add(event_id)

    def _run() -> None:
        try:
            prep = builder(event_id)
            set_prep(prep)
        except Exception:  # noqa: BLE001 — never crash the scheduler thread
            log.exception("prewarm failed for %s", event_id)
        finally:
            with _executor_lock:
                _inflight.discard(event_id)

    threading.Thread(target=_run, daemon=True, name=f"prewarm-{event_id}").start()
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_meeting_prep.py -v`

Expected: all PASS (3 cache tests + the previous ones).

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/repo/meeting_prep.py tests/test_meeting_prep.py
git commit -m "feat(meeting-prep): disk cache with hash-based invalidation"
```

---

## Task 6: HTTP route — `GET /v1/meetings/prep/{event_id}`

**Files:**
- Modify: `ghostbrain/api/routes/meetings.py`
- Create: `tests/test_route_meeting_prep.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_route_meeting_prep.py`:

```python
"""Integration tests for /v1/meetings/prep/{event_id}."""
from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from ghostbrain.api.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path / "state"))
    cal = tmp_path / "20-contexts" / "sanlam" / "calendar"
    cal.mkdir(parents=True)
    (cal / "20260525T090000-eng-standup.md").write_text(textwrap.dedent("""\
        ---
        title: Eng standup
        start: 2026-05-25T09:00:00+02:00
        end: 2026-05-25T09:30:00+02:00
        with:
          - alice@example.com
        location: Zoom
        description: sprint planning
        ---
        """))

    # Patch the expensive deps. Default: succeed.
    from ghostbrain.worker import meeting_prep as mp
    monkeypatch.setattr(mp, "_semantic_search", MagicMock(return_value={"items": []}))
    monkeypatch.setattr(mp, "_llm_run", MagicMock(return_value=MagicMock(text="brief")))

    return TestClient(app)


def test_get_prep_generates_when_missing(client):
    r = client.get("/v1/meetings/prep/20260525T090000-eng-standup")
    assert r.status_code == 200
    body = r.json()
    assert body["eventId"] == "20260525T090000-eng-standup"
    assert body["brief"] == "brief"
    assert body["eventSnapshot"]["title"] == "Eng standup"


def test_get_prep_uses_cache_on_repeat(client, monkeypatch):
    from ghostbrain.worker import meeting_prep as mp

    r1 = client.get("/v1/meetings/prep/20260525T090000-eng-standup")
    assert r1.status_code == 200
    # Swap the LLM to one that would raise if called.
    monkeypatch.setattr(mp, "_llm_run", MagicMock(side_effect=AssertionError("should not be called")))
    r2 = client.get("/v1/meetings/prep/20260525T090000-eng-standup")
    assert r2.status_code == 200
    assert r2.json()["brief"] == "brief"  # same response, no new LLM call


def test_get_prep_unknown_event_returns_404(client):
    r = client.get("/v1/meetings/prep/nope")
    assert r.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_route_meeting_prep.py -v`

Expected: FAIL with `assert response.status_code == 404` or similar (the route doesn't exist yet so FastAPI returns 404 for a different reason — confirm via the response body).

- [ ] **Step 3: Add the route**

Modify `ghostbrain/api/routes/meetings.py` to read in full:

```python
"""GET /v1/meetings + /v1/meetings/prep/{event_id}."""
from fastapi import APIRouter, HTTPException, Query

from ghostbrain.api.models.meeting import MeetingsPage, Prep
from ghostbrain.api.repo.meeting_prep import get_prep, set_prep
from ghostbrain.api.repo.meetings import list_meetings
from ghostbrain.worker.meeting_prep import (
    UnknownEvent,
    build_prep,
    event_hash,
    resolve_event_path,
)
import frontmatter

router = APIRouter(prefix="/v1/meetings", tags=["meetings"])


@router.get("", response_model=MeetingsPage)
def meetings(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    return list_meetings(limit=limit, offset=offset)


@router.get("/prep/{event_id}", response_model=Prep)
def get_meeting_prep(event_id: str) -> Prep:
    """Return cached prep (if hash matches) or generate synchronously."""
    path = resolve_event_path(event_id)
    if path is None:
        raise HTTPException(status_code=404, detail=f"unknown event: {event_id}")
    post = frontmatter.load(path)
    fm = post.metadata or {}
    expected = event_hash({
        "start": str(fm.get("start") or ""),
        "end": str(fm.get("end") or ""),
        "description": str(fm.get("description") or ""),
    })
    cached = get_prep(event_id, expected_hash=expected)
    if cached is not None:
        return cached
    try:
        prep = build_prep(event_id)
    except UnknownEvent as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    set_prep(prep)
    return prep
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_route_meeting_prep.py -v`

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/routes/meetings.py tests/test_route_meeting_prep.py
git commit -m "feat(meeting-prep): GET /v1/meetings/prep/{event_id}"
```

---

## Task 7: HTTP route — `POST /v1/meetings/prep/{event_id}/prewarm`

**Files:**
- Modify: `ghostbrain/api/routes/meetings.py`
- Modify: `tests/test_route_meeting_prep.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_route_meeting_prep.py`:

```python
def test_prewarm_returns_202(client, monkeypatch):
    """Prewarm hands off to a background thread and returns 202 immediately."""
    from ghostbrain.worker import meeting_prep as mp

    monkeypatch.setattr(mp, "_llm_run", MagicMock(return_value=MagicMock(text="warm brief")))

    r = client.post("/v1/meetings/prep/20260525T090000-eng-standup/prewarm")
    assert r.status_code == 202
    assert r.json()["status"] in {"started", "in_progress"}


def test_prewarm_404_for_unknown_event(client):
    r = client.post("/v1/meetings/prep/never-existed/prewarm")
    assert r.status_code == 404


def test_prewarm_fills_cache_eventually(client, monkeypatch, tmp_path):
    """After prewarm completes, a subsequent GET sees the cached brief."""
    import time
    from ghostbrain.worker import meeting_prep as mp

    monkeypatch.setattr(mp, "_llm_run", MagicMock(return_value=MagicMock(text="warm brief")))

    r = client.post("/v1/meetings/prep/20260525T090000-eng-standup/prewarm")
    assert r.status_code == 202

    # Wait for the background thread to write the cache. The build is fast
    # because both the LLM and semantic-search are mocked.
    deadline = time.time() + 5
    cache_file = tmp_path / "state" / "meeting-prep" / "20260525T090000-eng-standup.json"
    while time.time() < deadline and not cache_file.exists():
        time.sleep(0.05)
    assert cache_file.exists(), "prewarm did not write the cache file in time"

    # The follow-up GET reads from cache (we can't assert "no new LLM call"
    # because the mock is the same, but the cache hit is what we care about).
    r2 = client.get("/v1/meetings/prep/20260525T090000-eng-standup")
    assert r2.status_code == 200
    assert r2.json()["brief"] == "warm brief"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_route_meeting_prep.py::test_prewarm_kicks_off_background_generation -v`

Expected: FAIL with 404 / 405 (route doesn't exist).

- [ ] **Step 3: Add the route**

Append to `ghostbrain/api/routes/meetings.py` (after the `get_meeting_prep` handler):

```python
from fastapi.responses import JSONResponse

from ghostbrain.api.repo.meeting_prep import prewarm as prewarm_prep


@router.post("/prep/{event_id}/prewarm")
def prewarm_meeting_prep(event_id: str) -> JSONResponse:
    """Fire-and-forget background generation. Returns 202."""
    path = resolve_event_path(event_id)
    if path is None:
        raise HTTPException(status_code=404, detail=f"unknown event: {event_id}")
    launched = prewarm_prep(event_id)
    return JSONResponse(
        status_code=202,
        content={"status": "started" if launched else "in_progress"},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_route_meeting_prep.py -v`

Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/routes/meetings.py tests/test_route_meeting_prep.py
git commit -m "feat(meeting-prep): POST /v1/meetings/prep/{event_id}/prewarm"
```

---

## Task 8: Scheduler — pre-warm the next-upcoming meeting

**Files:**
- Modify: `ghostbrain/scheduler_jobs.py`
- Create: `tests/test_scheduler_meeting_prep_prewarm.py`

The job runs every 60s. It finds the soonest agenda item within `[now, now+20min]`, computes its event hash, and if there's no fresh cache, calls `prewarm`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_scheduler_meeting_prep_prewarm.py`:

```python
"""Unit test for the meeting-prep prewarm selection predicate."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ghostbrain.scheduler_jobs import _select_prewarm_target


def _agenda_item(start: datetime, *, status: str = "upcoming") -> dict:
    return {
        "id": "evt-" + start.strftime("%H%M"),
        "time": start.strftime("%H:%M"),
        "duration": "30m",
        "title": "test",
        "with": [],
        "status": status,
    }


def test_picks_next_event_within_twenty_minutes():
    now = datetime(2026, 5, 25, 10, 0, tzinfo=timezone.utc)
    soon = now + timedelta(minutes=15)
    later = now + timedelta(hours=2)
    agenda = [
        _agenda_item(later),
        _agenda_item(soon),
    ]
    target = _select_prewarm_target(agenda, now=now)
    assert target is not None
    assert target["time"] == soon.strftime("%H:%M")


def test_skips_past_events():
    now = datetime(2026, 5, 25, 10, 0, tzinfo=timezone.utc)
    past = now - timedelta(minutes=5)
    future = now + timedelta(hours=3)  # outside the 20-min window
    agenda = [_agenda_item(past), _agenda_item(future)]
    assert _select_prewarm_target(agenda, now=now) is None


def test_skips_recorded_events():
    now = datetime(2026, 5, 25, 10, 0, tzinfo=timezone.utc)
    soon = now + timedelta(minutes=10)
    agenda = [_agenda_item(soon, status="recorded")]
    assert _select_prewarm_target(agenda, now=now) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_scheduler_meeting_prep_prewarm.py -v`

Expected: FAIL with `ImportError: cannot import name '_select_prewarm_target'`.

- [ ] **Step 3: Add the predicate + register the job**

In `ghostbrain/scheduler_jobs.py`, add (anywhere among the helper definitions, near `_digest_job`):

```python
from datetime import datetime, timedelta, timezone


def _select_prewarm_target(agenda: list[dict], *, now: datetime) -> dict | None:
    """Return the soonest upcoming item starting in [now, now+20m], else None.

    Agenda items carry ``time`` as ``HH:MM`` in the local timezone; we
    compare on local-naive timestamps for the same day.
    """
    horizon = now + timedelta(minutes=20)
    best: tuple[datetime, dict] | None = None
    for item in agenda:
        if item.get("status") != "upcoming":
            continue
        try:
            hh, mm = item["time"].split(":")
            start = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        except (KeyError, ValueError):
            continue
        if start < now or start > horizon:
            continue
        if best is None or start < best[0]:
            best = (start, item)
    return best[1] if best else None


def _meeting_prep_prewarm_job() -> RunResult:
    def work() -> dict:
        from ghostbrain.api.repo.agenda import list_agenda
        from ghostbrain.api.repo.meeting_prep import get_prep, prewarm
        from ghostbrain.worker.meeting_prep import (
            event_hash,
            resolve_event_path,
        )
        import frontmatter

        today = datetime.now().date().isoformat()
        agenda = list_agenda(date=today)
        target = _select_prewarm_target(agenda, now=datetime.now(timezone.utc))
        if target is None:
            return {"skipped": "no-target"}
        event_id = target["id"]
        path = resolve_event_path(event_id)
        if path is None:
            return {"skipped": "no-note"}
        fm = (frontmatter.load(path).metadata or {})
        h = event_hash({
            "start": str(fm.get("start") or ""),
            "end": str(fm.get("end") or ""),
            "description": str(fm.get("description") or ""),
        })
        if get_prep(event_id, expected_hash=h) is not None:
            return {"skipped": "cached", "event_id": event_id}
        launched = prewarm(event_id)
        return {"launched": launched, "event_id": event_id}

    return _wrap_job("meeting-prep-prewarm", work)
```

Then inside `register_connectors`, add:

```python
    scheduler.add_job(
        "meeting-prep-prewarm",
        Interval(seconds=60),
        _meeting_prep_prewarm_job,
        "every 60s",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_scheduler_meeting_prep_prewarm.py -v`

Expected: 3 PASS.

Also run: `pytest tests/test_meeting_prep.py tests/test_route_meeting_prep.py -v`

Expected: all previous tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/scheduler_jobs.py tests/test_scheduler_meeting_prep_prewarm.py
git commit -m "feat(meeting-prep): scheduler pre-warms the next upcoming meeting"
```

---

## Task 9: TypeScript types for the Prep response

**Files:**
- Modify: `desktop/src/shared/api-types.ts`

- [ ] **Step 1: Add the types**

Append to `desktop/src/shared/api-types.ts` (after the `AgendaItem` block):

```ts
export interface EventSnapshot {
  title: string;
  start: string;
  end: string;
  with: string[];
  location: string;
  description: string;
  hash: string;
}

export interface RelatedItem {
  path: string;
  title: string;
  source: string;  // "calendar" | "meeting" | "email" | "slack" | "jira" | …
  snippet: string;
  score: number;
}

export interface Prep {
  eventId: string;
  brief: string | null;
  related: RelatedItem[];
  eventSnapshot: EventSnapshot;
  generatedAt: string;
  error: string | null;
}
```

- [ ] **Step 2: Type-check the desktop project**

Run: `cd desktop && npm run typecheck`

Expected: PASS (no errors — these are pure additions).

If `typecheck` isn't a defined script, run: `cd desktop && npx tsc --noEmit -p tsconfig.web.json`.

- [ ] **Step 3: Commit**

```bash
git add desktop/src/shared/api-types.ts
git commit -m "feat(desktop): Prep / RelatedItem / EventSnapshot types"
```

---

## Task 10: `useMeetingPrep` hook

**Files:**
- Modify: `desktop/src/renderer/lib/api/hooks.ts`

- [ ] **Step 1: Add the hook**

Append to `desktop/src/renderer/lib/api/hooks.ts` (at the bottom of the file):

```ts
import type { Prep } from '../../../shared/api-types';

export function useMeetingPrep(eventId: string | null) {
  return useQuery({
    queryKey: ['meeting-prep', eventId],
    queryFn: () => get<Prep>(`/v1/meetings/prep/${encodeURIComponent(eventId!)}`),
    enabled: eventId !== null,
    // The brief is cached on the sidecar side and only regenerates when the
    // underlying event changes — no benefit to refetching client-side.
    staleTime: Infinity,
    retry: false,
  });
}

export function usePrewarmMeetingPrep() {
  return useMutation({
    mutationFn: (eventId: string) =>
      post<{ status: string }>(
        `/v1/meetings/prep/${encodeURIComponent(eventId)}/prewarm`,
      ),
  });
}
```

The existing `import` line for `api-types` already brings most of these symbols — if `Prep` isn't there yet, fold it into that existing import block rather than adding a second one.

- [ ] **Step 2: Type-check**

Run: `cd desktop && npx tsc --noEmit -p tsconfig.web.json`

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add desktop/src/renderer/lib/api/hooks.ts
git commit -m "feat(desktop): useMeetingPrep + usePrewarmMeetingPrep hooks"
```

---

## Task 11: Selected-event-id store

**Files:**
- Create: `desktop/src/renderer/stores/selected-event.ts`

Keep this in its own slice so the IPC handler in `App.tsx` doesn't have to import the bigger `meeting` store.

- [ ] **Step 1: Create the store**

Create `desktop/src/renderer/stores/selected-event.ts`:

```ts
import { create } from 'zustand';

interface SelectedEventState {
  selectedEventId: string | null;
  setSelectedEventId: (id: string | null) => void;
}

export const useSelectedEvent = create<SelectedEventState>((set) => ({
  selectedEventId: null,
  setSelectedEventId: (selectedEventId) => set({ selectedEventId }),
}));
```

- [ ] **Step 2: Type-check**

Run: `cd desktop && npx tsc --noEmit -p tsconfig.web.json`

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add desktop/src/renderer/stores/selected-event.ts
git commit -m "feat(desktop): selected-event store for prep panel auto-expand"
```

---

## Task 12: `<MeetingPrep />` component with RTL tests

**Files:**
- Create: `desktop/src/renderer/components/MeetingPrep.tsx`
- Create: `desktop/src/renderer/__tests__/MeetingPrep.test.tsx`

- [ ] **Step 1: Write the failing tests**

Create `desktop/src/renderer/__tests__/MeetingPrep.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { MeetingPrep } from '../components/MeetingPrep';
import * as hooks from '../lib/api/hooks';
import type { Prep } from '../../shared/api-types';

const fullPrep: Prep = {
  eventId: 'evt-1',
  brief: 'Continuing last week\'s auth thread.',
  related: [{
    path: '20-contexts/sanlam/meetings/2026-05-18-eng-standup.md',
    title: 'Eng standup 2026-05-18',
    source: 'meeting',
    snippet: 'agreed to spike auth',
    score: 0.82,
  }],
  eventSnapshot: {
    title: 'Eng standup',
    start: '2026-05-25T09:00:00+02:00',
    end: '2026-05-25T09:30:00+02:00',
    with: ['alice@example.com'],
    location: 'Zoom',
    description: 'sprint planning',
    hash: 'h1',
  },
  generatedAt: '2026-05-25T08:55:00+02:00',
  error: null,
};

function wrap(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{node}</QueryClientProvider>;
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe('MeetingPrep', () => {
  it('renders the brief, attendees, and related items on success', () => {
    vi.spyOn(hooks, 'useMeetingPrep').mockReturnValue({
      data: fullPrep,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof hooks.useMeetingPrep>);

    render(wrap(<MeetingPrep eventId="evt-1" />));

    expect(screen.getByText('Continuing last week\'s auth thread.')).toBeInTheDocument();
    expect(screen.getByText('alice@example.com')).toBeInTheDocument();
    expect(screen.getByText('Eng standup 2026-05-18')).toBeInTheDocument();
  });

  it('shows a loading state while the query is in flight', () => {
    vi.spyOn(hooks, 'useMeetingPrep').mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof hooks.useMeetingPrep>);

    render(wrap(<MeetingPrep eventId="evt-1" />));

    expect(screen.getByRole('status', { name: /loading/i })).toBeInTheDocument();
  });

  it('renders event detail and related even when the brief errored', () => {
    const noBriefPrep: Prep = {
      ...fullPrep,
      brief: null,
      error: 'LLMTimeout: claude -p timed out after 30s',
    };
    vi.spyOn(hooks, 'useMeetingPrep').mockReturnValue({
      data: noBriefPrep,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof hooks.useMeetingPrep>);

    render(wrap(<MeetingPrep eventId="evt-1" />));

    expect(screen.getByText(/couldn't generate brief/i)).toBeInTheDocument();
    expect(screen.getByText('alice@example.com')).toBeInTheDocument();
    expect(screen.getByText('Eng standup 2026-05-18')).toBeInTheDocument();
  });

  it('hides the related section when the list is empty', () => {
    const emptyRelatedPrep: Prep = { ...fullPrep, related: [] };
    vi.spyOn(hooks, 'useMeetingPrep').mockReturnValue({
      data: emptyRelatedPrep,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof hooks.useMeetingPrep>);

    render(wrap(<MeetingPrep eventId="evt-1" />));

    expect(screen.queryByText(/related/i)).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd desktop && npx vitest run src/renderer/__tests__/MeetingPrep.test.tsx`

Expected: FAIL with `Cannot find module '../components/MeetingPrep'`.

- [ ] **Step 3: Implement the component**

Create `desktop/src/renderer/components/MeetingPrep.tsx`:

```tsx
import { Eyebrow } from './Eyebrow';
import { Lucide } from './Lucide';
import { Btn } from './Btn';
import { Pill } from './Pill';
import { useMeetingPrep, usePrewarmMeetingPrep } from '../lib/api/hooks';
import { useNoteView } from '../stores/note-view';

interface Props {
  eventId: string | null;
}

export function MeetingPrep({ eventId }: Props) {
  const query = useMeetingPrep(eventId);
  const prewarm = usePrewarmMeetingPrep();
  const openNote = useNoteView((s) => s.open);

  if (query.isLoading) {
    return (
      <div
        role="status"
        aria-label="loading prep notes"
        className="flex items-center gap-3 rounded-md border border-hairline bg-paper p-4"
      >
        <div
          className="h-3 w-3 rounded-full border-2 border-neon border-t-transparent"
          style={{ animation: 'gb-spin 0.9s linear infinite' }}
        />
        <span className="font-mono text-11 text-ink-2">generating brief…</span>
      </div>
    );
  }

  if (query.isError || !query.data) {
    return (
      <div className="rounded-md border border-oxblood/30 bg-paper p-4 text-12 text-oxblood">
        couldn't load prep notes
      </div>
    );
  }

  const prep = query.data;
  const snap = prep.eventSnapshot;

  return (
    <div className="flex flex-col gap-4 rounded-md border border-hairline bg-paper p-4">
      <section>
        <Eyebrow className="mb-2">meeting</Eyebrow>
        <div className="font-display text-16 font-semibold text-ink-0">{snap.title}</div>
        <div className="mt-1 flex flex-wrap gap-3 font-mono text-11 text-ink-2">
          <span>
            <Lucide name="clock" size={11} className="mr-1 inline-block align-[-2px]" />
            {formatRange(snap.start, snap.end)}
          </span>
          {snap.location && (
            <span>
              <Lucide name="map-pin" size={11} className="mr-1 inline-block align-[-2px]" />
              {snap.location}
            </span>
          )}
        </div>
        {snap.with.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {snap.with.map((a) => (
              <Pill key={a} tone="outline">{a}</Pill>
            ))}
          </div>
        )}
        {snap.description && (
          <p className="mt-3 whitespace-pre-wrap text-12 leading-[1.5] text-ink-1">
            {snap.description}
          </p>
        )}
      </section>

      <section>
        <div className="mb-2 flex items-center gap-2">
          <Eyebrow>brief</Eyebrow>
          <Btn
            variant="ghost"
            size="sm"
            icon={<Lucide name="refresh-cw" size={11} />}
            onClick={() => {
              if (eventId) {
                prewarm.mutate(eventId, {
                  onSuccess: () => query.refetch(),
                });
              }
            }}
            ariaLabel="regenerate brief"
          />
        </div>
        {prep.brief ? (
          <p className="text-13 leading-[1.55] text-ink-0">{prep.brief}</p>
        ) : (
          <p className="text-12 text-oxblood">
            couldn't generate brief — {prep.error ?? 'unknown error'}
          </p>
        )}
      </section>

      {prep.related.length > 0 && (
        <section>
          <Eyebrow className="mb-2">related</Eyebrow>
          <ul className="m-0 flex list-none flex-col gap-1 p-0">
            {prep.related.map((r) => (
              <li key={r.path}>
                <button
                  type="button"
                  onClick={() => openNote(r.path)}
                  className="flex w-full items-start gap-2 rounded-sm px-2 py-[6px] text-left hover:bg-vellum"
                >
                  <Pill tone="outline">{r.source}</Pill>
                  <div className="flex-1">
                    <div className="text-12 text-ink-0">{r.title}</div>
                    <div className="font-mono text-10 text-ink-2">{r.snippet}</div>
                  </div>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function formatRange(start: string, end: string): string {
  try {
    const s = new Date(start);
    const e = new Date(end);
    const sStr = s.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const eStr = e.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    return `${sStr} — ${eStr}`;
  } catch {
    return `${start} — ${end}`;
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd desktop && npx vitest run src/renderer/__tests__/MeetingPrep.test.tsx`

Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/renderer/components/MeetingPrep.tsx desktop/src/renderer/__tests__/MeetingPrep.test.tsx
git commit -m "feat(desktop): MeetingPrep component renders brief + related"
```

---

## Task 13: `<UpcomingMeetings />` list with inline expansion

**Files:**
- Create: `desktop/src/renderer/components/UpcomingMeetings.tsx`
- Create: `desktop/src/renderer/__tests__/UpcomingMeetings.test.tsx`

- [ ] **Step 1: Write the failing tests**

Create `desktop/src/renderer/__tests__/UpcomingMeetings.test.tsx`:

```tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { UpcomingMeetings } from '../components/UpcomingMeetings';
import { useSelectedEvent } from '../stores/selected-event';
import type { AgendaItem } from '../../shared/api-types';

const items: AgendaItem[] = [
  { id: 'a', time: '09:00', duration: '30m', title: 'Eng standup', with: ['alice@example.com'], status: 'upcoming' },
  { id: 'b', time: '11:00', duration: '1h', title: 'Design review', with: [], status: 'upcoming' },
  { id: 'c', time: '08:00', duration: '30m', title: 'Past meeting', with: [], status: 'recorded' },
];

function wrap(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{node}</QueryClientProvider>;
}

beforeEach(() => {
  useSelectedEvent.setState({ selectedEventId: null });
  vi.restoreAllMocks();
});

describe('UpcomingMeetings', () => {
  it('lists upcoming items and hides recorded ones', () => {
    render(wrap(<UpcomingMeetings items={items} />));
    expect(screen.getByText('Eng standup')).toBeInTheDocument();
    expect(screen.getByText('Design review')).toBeInTheDocument();
    expect(screen.queryByText('Past meeting')).not.toBeInTheDocument();
  });

  it('expands the prep panel on row click', () => {
    render(wrap(<UpcomingMeetings items={items} />));
    fireEvent.click(screen.getByText('Eng standup'));
    expect(useSelectedEvent.getState().selectedEventId).toBe('a');
  });

  it('auto-expands the row matching selectedEventId from the store', () => {
    useSelectedEvent.setState({ selectedEventId: 'b' });
    render(wrap(<UpcomingMeetings items={items} />));
    // The MeetingPrep inside the expanded row mounts and renders its loading state.
    expect(screen.getByRole('status', { name: /loading/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd desktop && npx vitest run src/renderer/__tests__/UpcomingMeetings.test.tsx`

Expected: FAIL with `Cannot find module '../components/UpcomingMeetings'`.

- [ ] **Step 3: Implement the component**

Create `desktop/src/renderer/components/UpcomingMeetings.tsx`:

```tsx
import { Eyebrow } from './Eyebrow';
import { Panel } from './Panel';
import { MeetingPrep } from './MeetingPrep';
import { useSelectedEvent } from '../stores/selected-event';
import type { AgendaItem } from '../../shared/api-types';

interface Props {
  items: AgendaItem[];
}

export function UpcomingMeetings({ items }: Props) {
  const selected = useSelectedEvent((s) => s.selectedEventId);
  const setSelected = useSelectedEvent((s) => s.setSelectedEventId);

  const upcoming = items.filter((m) => m.status === 'upcoming');
  if (upcoming.length === 0) return null;

  return (
    <div className="mx-auto max-w-[1100px] px-8 pt-2">
      <Panel title="today's agenda" subtitle={`${upcoming.length} upcoming`}>
        {upcoming.map((m) => {
          const isOpen = selected === m.id;
          return (
            <div key={m.id} className="border-b border-hairline last:border-b-0">
              <button
                type="button"
                onClick={() => setSelected(isOpen ? null : m.id)}
                aria-expanded={isOpen}
                className="grid w-full items-center gap-3 px-2 py-[10px] text-left hover:bg-paper"
                style={{ gridTemplateColumns: '80px minmax(0, 1fr) 80px' }}
              >
                <span className="font-mono text-11 text-ink-2">{m.time}</span>
                <span className="text-13 text-ink-0">{m.title}</span>
                <span className="font-mono text-11 text-ink-1">{m.duration}</span>
              </button>
              {isOpen && (
                <div className="px-2 pb-4">
                  <MeetingPrep eventId={m.id} />
                </div>
              )}
            </div>
          );
        })}
      </Panel>
    </div>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd desktop && npx vitest run src/renderer/__tests__/UpcomingMeetings.test.tsx`

Expected: 3 PASS. The auto-expand test relies on `MeetingPrep` rendering its loading state when the hook hasn't returned data — that already happens because the prep query is enabled but not yet resolved.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/renderer/components/UpcomingMeetings.tsx desktop/src/renderer/__tests__/UpcomingMeetings.test.tsx
git commit -m "feat(desktop): UpcomingMeetings list with inline prep expansion"
```

---

## Task 14: Wire `<UpcomingMeetings />` into the Meetings screen

**Files:**
- Modify: `desktop/src/renderer/screens/meetings.tsx`

- [ ] **Step 1: Add the component to the screen**

In `desktop/src/renderer/screens/meetings.tsx`, do two things:

1. Add the import near the top:

```ts
import { UpcomingMeetings } from '../components/UpcomingMeetings';
```

2. Render it between the existing phase-conditional blocks and `<MeetingHistory />`. Replace this block:

```tsx
      {phase === 'post' && (
        <PostMeeting
          title={activeTitle}
          transcriptPath={transcriptPath}
          error={activeError}
          onClose={reset}
        />
      )}

      <MeetingHistory />
```

with:

```tsx
      {phase === 'post' && (
        <PostMeeting
          title={activeTitle}
          transcriptPath={transcriptPath}
          error={activeError}
          onClose={reset}
        />
      )}

      {phase === 'pre' && agenda.data && (
        <UpcomingMeetings items={agenda.data} />
      )}

      <MeetingHistory />
```

We only show the upcoming-meetings list when no recording is in progress — during an active recording or post-meeting view the user should focus on that, not the next meeting.

- [ ] **Step 2: Smoke-check**

Run: `cd desktop && npx tsc --noEmit -p tsconfig.web.json`

Expected: no errors.

Run: `cd desktop && npx vitest run`

Expected: all tests still PASS.

- [ ] **Step 3: Commit**

```bash
git add desktop/src/renderer/screens/meetings.tsx
git commit -m "feat(desktop): render UpcomingMeetings on the meetings screen"
```

---

## Task 15: `shouldFireNow` pure helper

**Files:**
- Create: `desktop/src/main/meeting-notifier.ts`
- Create: `desktop/src/main/__tests__/meeting-notifier.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `desktop/src/main/__tests__/meeting-notifier.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { shouldFireNow } from '../meeting-notifier';
import type { AgendaItem } from '../../shared/api-types';

function makeEvent(time: string, status: AgendaItem['status'] = 'upcoming'): AgendaItem {
  return { id: `evt-${time}`, time, duration: '30m', title: 't', with: [], status };
}

describe('shouldFireNow', () => {
  const now = new Date('2026-05-25T08:46:00+02:00');

  it('fires when start is exactly 15 minutes away', () => {
    const event = makeEvent('09:01');  // 15 min from now
    expect(shouldFireNow(event, now, new Set())).toBe(true);
  });

  it('does not fire when start is more than 15 minutes away', () => {
    const event = makeEvent('09:30');
    expect(shouldFireNow(event, now, new Set())).toBe(false);
  });

  it('does not fire for events whose start has already passed', () => {
    const event = makeEvent('08:00');
    expect(shouldFireNow(event, now, new Set())).toBe(false);
  });

  it('does not fire when the event id was already notified', () => {
    const event = makeEvent('09:00');
    expect(shouldFireNow(event, now, new Set(['evt-09:00']))).toBe(false);
  });

  it('does not fire for recorded events', () => {
    const event = makeEvent('09:00', 'recorded');
    expect(shouldFireNow(event, now, new Set())).toBe(false);
  });

  it('returns false for events with malformed time', () => {
    const event = { ...makeEvent('09:00'), time: 'garbage' };
    expect(shouldFireNow(event, now, new Set())).toBe(false);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd desktop && npx vitest run src/main/__tests__/meeting-notifier.test.ts`

Expected: FAIL with `Cannot find module '../meeting-notifier'`.

- [ ] **Step 3: Implement the pure helper**

Create `desktop/src/main/meeting-notifier.ts` with just the pure piece for now:

```ts
import type { AgendaItem } from '../shared/api-types';

const LEAD_MINUTES = 15;

export function shouldFireNow(
  event: AgendaItem,
  now: Date,
  notified: ReadonlySet<string>,
): boolean {
  if (event.status !== 'upcoming') return false;
  if (notified.has(event.id)) return false;
  const match = event.time.match(/^(\d{2}):(\d{2})$/);
  if (!match) return false;
  const start = new Date(now);
  start.setHours(Number(match[1]), Number(match[2]), 0, 0);
  const fireAt = start.getTime() - LEAD_MINUTES * 60_000;
  // Window: [fireAt, start). If we missed fireAt by ≤15 min but the meeting
  // hasn't started yet, fire (covers an app that booted just before the
  // meeting starts).
  return now.getTime() >= fireAt && now.getTime() < start.getTime();
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd desktop && npx vitest run src/main/__tests__/meeting-notifier.test.ts`

Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/main/meeting-notifier.ts desktop/src/main/__tests__/meeting-notifier.test.ts
git commit -m "feat(desktop): shouldFireNow predicate for meeting notifier"
```

---

## Task 16: Notifier — agenda poll loop, notified-set persistence, click handler

**Files:**
- Modify: `desktop/src/main/meeting-notifier.ts`

- [ ] **Step 1: Add the polling + Notification firing + persistence**

Append to `desktop/src/main/meeting-notifier.ts`:

```ts
import { BrowserWindow, Notification, app } from 'electron';
import fs from 'node:fs';
import path from 'node:path';

const POLL_INTERVAL_MS = 60_000;
const NOTIFIED_PRUNE_AFTER_MS = 24 * 60 * 60 * 1000;

interface InstallOpts {
  sidecarUrl: string;  // e.g. "http://127.0.0.1:8765"
}

export interface MeetingNotifierController {
  destroy: () => void;
}

interface NotifiedRecord {
  /** event id → epoch ms when it was notified */
  [eventId: string]: number;
}

function notifiedFilePath(): string {
  return path.join(app.getPath('userData'), 'meeting-notified.json');
}

function loadNotified(): NotifiedRecord {
  try {
    const raw = fs.readFileSync(notifiedFilePath(), 'utf-8');
    const parsed = JSON.parse(raw) as NotifiedRecord;
    const now = Date.now();
    const fresh: NotifiedRecord = {};
    for (const [k, v] of Object.entries(parsed)) {
      if (typeof v === 'number' && now - v < NOTIFIED_PRUNE_AFTER_MS) {
        fresh[k] = v;
      }
    }
    return fresh;
  } catch {
    return {};
  }
}

function saveNotified(record: NotifiedRecord): void {
  try {
    fs.writeFileSync(notifiedFilePath(), JSON.stringify(record), 'utf-8');
  } catch (e) {
    console.warn('[meeting-notifier] could not save notified-set:', e);
  }
}

function fireNotification(event: AgendaItem): void {
  if (!Notification.isSupported()) return;
  const notification = new Notification({
    title: `${event.title} in 15 min`,
    body: event.with.length
      ? `with ${event.with.slice(0, 3).join(', ')}`
      : '',
    silent: false,
  });
  notification.on('click', () => {
    for (const win of BrowserWindow.getAllWindows()) {
      if (win.isMinimized()) win.restore();
      win.show();
      win.focus();
      win.webContents.send('gb:meetings:openPrep', event.id);
    }
  });
  notification.show();
}

export function installMeetingNotifier(opts: InstallOpts): MeetingNotifierController {
  let notified = loadNotified();
  let timer: NodeJS.Timeout | null = null;

  async function tick(): Promise<void> {
    try {
      const res = await fetch(`${opts.sidecarUrl}/v1/agenda`);
      if (!res.ok) return;
      const items = (await res.json()) as AgendaItem[];
      const now = new Date();
      const ids = new Set(Object.keys(notified));
      for (const event of items) {
        if (shouldFireNow(event, now, ids)) {
          fireNotification(event);
          notified[event.id] = Date.now();
          ids.add(event.id);
        }
      }
      saveNotified(notified);
    } catch (e) {
      // Sidecar may be booting or down — try again next tick.
      console.warn('[meeting-notifier] poll failed:', e);
    }
  }

  // Fire one immediately so a freshly-launched app catches an imminent meeting,
  // then schedule the recurring poll.
  void tick();
  timer = setInterval(() => void tick(), POLL_INTERVAL_MS);

  return {
    destroy() {
      if (timer !== null) clearInterval(timer);
      timer = null;
    },
  };
}
```

- [ ] **Step 2: Type-check**

Run: `cd desktop && npx tsc --noEmit -p tsconfig.node.json`

`tsconfig.node.json` covers `src/main/**/*` + `src/preload/**/*` + `src/shared/**/*` (verified by `include` block in that file).

Expected: no errors. The previous unit test still passes:

Run: `cd desktop && npx vitest run src/main/__tests__/meeting-notifier.test.ts`

Expected: 6 PASS.

- [ ] **Step 3: Commit**

```bash
git add desktop/src/main/meeting-notifier.ts
git commit -m "feat(desktop): meeting-notifier poll loop + native Notification + click handler"
```

---

## Task 17: Wire the notifier into the main process

**Files:**
- Modify: `desktop/src/main/index.ts`

- [ ] **Step 1: Install the notifier alongside the tray**

In `desktop/src/main/index.ts`:

1. Add the import near the top with the other main-process imports:

```ts
import {
  installMeetingNotifier,
  type MeetingNotifierController,
} from './meeting-notifier';
```

2. Add a module-level variable next to `trayController`:

```ts
let meetingNotifier: MeetingNotifierController | null = null;
```

3. Install it where `trayController = installTray(...)` is called. Right after that block:

```ts
  meetingNotifier = installMeetingNotifier({
    sidecarUrl: process.env.GHOSTBRAIN_SIDECAR_URL ?? 'http://127.0.0.1:8765',
  });
```

(If the sidecar URL is already wired up via a constant elsewhere — e.g. settings — use that instead of the env var fallback. Look near the `gb:api:request` handler to see what URL it uses.)

4. Destroy it on `before-quit`, mirroring the tray:

```ts
app.on('before-quit', () => {
  trayController?.destroy();
  meetingNotifier?.destroy();
});
```

(If a `before-quit` handler already exists, add the `meetingNotifier?.destroy()` line to it rather than registering a second.)

- [ ] **Step 2: Smoke-check**

Run: `cd desktop && npm run build`

Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add desktop/src/main/index.ts
git commit -m "feat(desktop): install meeting-notifier on app start"
```

---

## Task 18: Renderer IPC listener — navigate to meetings tab on notification click

**Files:**
- Modify: `desktop/src/renderer/App.tsx`

- [ ] **Step 1: Subscribe to the IPC channel**

In `desktop/src/renderer/App.tsx`, add a `useEffect` near the top of the `App` component (or wherever the existing `gb.on` listeners live — there's already at least one for `sidecar:ready` / `sidecar:failed` per the IPC grep above).

```tsx
import { useSelectedEvent } from './stores/selected-event';
import { useNavigation } from './stores/navigation';

// inside the App component body:
useEffect(() => {
  const off = window.gb.on('meetings:openPrep', (eventId: unknown) => {
    if (typeof eventId !== 'string') return;
    useNavigation.getState().setActive('meetings');
    useSelectedEvent.getState().setSelectedEventId(eventId);
  });
  return off;
}, []);
```

Use the existing `gb.on` bridge — it already prefixes the channel with `gb:`, matching `webContents.send('gb:meetings:openPrep', …)` on the main-process side.

- [ ] **Step 2: Type-check + tests**

Run: `cd desktop && npx tsc --noEmit -p tsconfig.web.json`

Expected: no errors.

Run: `cd desktop && npx vitest run`

Expected: all PASS (including the existing `App.test.tsx`).

- [ ] **Step 3: Commit**

```bash
git add desktop/src/renderer/App.tsx
git commit -m "feat(desktop): handle meetings:openPrep IPC to focus prep panel"
```

---

## Task 19: End-to-end smoke test in dev mode

This is a manual checkpoint, not a code task — but it's required before declaring done.

- [ ] **Step 1: Create a calendar event 16 minutes in the future**

In macOS Calendar (or via the macOS Calendar connector if Google Calendar is wired up), create a test event titled "Notifier smoke test" starting 16 minutes from `date`. Force a calendar connector sync so the event lands in the vault:

```bash
python -m ghostbrain.connectors.calendar --once
```

Verify the event note exists under `~/ghostbrain/vault/20-contexts/<ctx>/calendar/`.

- [ ] **Step 2: Boot the desktop app in dev mode**

```bash
cd desktop && npm run dev
```

Watch the main-process console — you should see no errors from `meeting-notifier`.

- [ ] **Step 3: Wait ~1 minute and verify the notification fires**

A native macOS notification titled "Notifier smoke test in 15 min" should appear within 60s of the T-15 mark. If notification permissions aren't granted, grant them via System Settings → Notifications → Poltergeist and rerun.

- [ ] **Step 4: Click the notification**

Expected: window comes to the foreground, navigates to the Meetings tab, the "Notifier smoke test" row in `today's agenda` is auto-expanded, and the prep panel renders (brief from `claude -p`, related items from the semantic index — for a freshly-created event with no related context, expect `(no related context found)` to surface in the brief).

- [ ] **Step 5: Manual list click**

Click another upcoming row → expand → confirm the prep panel mounts and (after a few seconds of spinner) the brief lands.

- [ ] **Step 6: Restart and verify no double-fire**

Quit the app, relaunch. The notification for the same event should NOT fire again (the notified-set is persisted at `~/Library/Application Support/Poltergeist/meeting-notified.json` — check it contains the event id).

---

## Self-review notes

Coverage check against the spec:

| Spec requirement | Task |
|---|---|
| `build_prep(event_id) -> Prep` builder | Task 3 |
| Semantic search by title + attendees, de-duped | Task 3 (`_related_for`) |
| Calls `claude -p` via `ghostbrain.llm.client.run` | Task 3 |
| `brief=None` on LLM error/timeout, error string captured | Task 3 + Task 4 |
| Disk cache at `state_dir()/meeting-prep/<event_id>.json` | Task 5 |
| Cache invalidation on `start|end|description` hash change | Task 5 |
| Atomic cache write | Task 5 |
| `prewarm` fire-and-forget thread | Task 5 |
| `GET /v1/meetings/prep/{event_id}` cache-or-generate | Task 6 |
| 404 for unknown event id | Task 6 |
| `POST /v1/meetings/prep/{event_id}/prewarm` returns 202 | Task 7 |
| Scheduler runs every 60s, picks soonest event in T+20 | Task 8 |
| Skips already-cached and non-upcoming events | Task 8 |
| TypeScript types mirroring Pydantic models | Task 9 |
| `useMeetingPrep`, `usePrewarmMeetingPrep` hooks | Task 10 |
| Selected-event store for cross-component coordination | Task 11 |
| `<MeetingPrep />` with 3 sections (detail/brief/related) | Task 12 |
| Loading / error / empty-related states | Task 12 |
| `<UpcomingMeetings />` list with inline expansion | Task 13 |
| Auto-expand from selected-event store | Task 13 |
| Notifier fires at T-15 once per event | Task 16 |
| `shouldFireNow` pure helper | Task 15 |
| Click handler focuses window + IPC to renderer | Task 16 |
| Notified-set persisted, pruned after 24h | Task 16 |
| Wired into main process startup + teardown | Task 17 |
| Renderer IPC listener navigates to Meetings + opens prep | Task 18 |
| Manual smoke test | Task 19 |

No gaps.
