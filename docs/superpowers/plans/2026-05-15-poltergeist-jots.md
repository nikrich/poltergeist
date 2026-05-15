# Poltergeist Jots Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a ⌥-J global-hotkey overlay and a tree+editor "Jot" screen so the user can persist passing thoughts into the vault and have them indexed for later "ask" recall.

**Architecture:** Hotkey overlay POSTs to a new `/v1/notes` family of endpoints in the Python sidecar. The sidecar writes the markdown file to `00-inbox/raw/manual/`, calls the existing `ghostbrain.worker.router.route_event` synchronously to classify, then moves the file under `vault/20-contexts/{context}/notes/` (or leaves it as `manual_review`). The existing 15-minute semantic refresh picks it up. The Jot screen is a CodeMirror-based editor with a left tree, scoped only to manual notes.

**Tech Stack:** Python 3.11 + FastAPI (sidecar), pytest (backend tests), Electron + React + TypeScript (desktop app), Zustand (state), React Query (data), CodeMirror 6 (editor), Vitest + React Testing Library (renderer tests).

**Spec:** `docs/superpowers/specs/2026-05-14-poltergeist-jots-design.md`

---

## Task 1: Extend Note model with manual-jot fields

**Files:**
- Modify: `ghostbrain/api/models/note.py`
- Test: `ghostbrain/api/tests/test_models_note.py` (create)

- [ ] **Step 1: Write the failing test**

Create `ghostbrain/api/tests/test_models_note.py`:

```python
"""Schema contract for the note model used by the jot endpoints."""
from ghostbrain.api.models.note import Note, NoteListItem, NotesPage


def test_note_accepts_jot_frontmatter():
    note = Note(
        path="20-contexts/sanlam/notes/manual-20260514T093015-x.md",
        title="ghostbrain idea",
        body="thoughts about the ascp wizard flow",
        frontmatter={
            "id": "manual-20260514T093015-x",
            "type": "note",
            "source": "manual",
            "context": "sanlam",
            "routingStatus": "routed",
            "routingMethod": "llm",
            "routingConfidence": 0.82,
            "tags": ["idea", "ui"],
        },
    )
    assert note.frontmatter["routingStatus"] == "routed"


def test_note_list_item_shape():
    item = NoteListItem(
        id="manual-20260514T093015-x",
        path="20-contexts/sanlam/notes/manual-20260514T093015-x.md",
        title="ghostbrain idea",
        excerpt="thoughts about the…",
        context="sanlam",
        routingStatus="routed",
        tags=["idea"],
        created="2026-05-14T09:30:15+02:00",
        updated="2026-05-14T09:30:15+02:00",
    )
    assert item.routingStatus == "routed"


def test_notes_page_shape():
    page = NotesPage(items=[], total=0)
    assert page.total == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest ghostbrain/api/tests/test_models_note.py -v`
Expected: FAIL — `NoteListItem` and `NotesPage` don't exist yet.

- [ ] **Step 3: Add the new models**

Replace `ghostbrain/api/models/note.py`:

```python
"""Note-viewer schemas + jot list/detail schemas."""
from typing import Any, Literal

from pydantic import BaseModel


class Note(BaseModel):
    path: str  # vault-relative
    title: str
    body: str
    frontmatter: dict[str, Any]


RoutingStatus = Literal["pending", "routed", "manual_review"]
RoutingMethod = Literal["llm", "user", "fallback"]


class NoteListItem(BaseModel):
    """One row in the Jot screen tree/list."""

    id: str
    path: str  # vault-relative
    title: str
    excerpt: str  # first ~120 chars of body
    context: str | None  # None while pending
    routingStatus: RoutingStatus
    tags: list[str]
    created: str  # ISO8601
    updated: str  # ISO8601


class NotesPage(BaseModel):
    items: list[NoteListItem]
    total: int


class CreateNoteRequest(BaseModel):
    body: str
    capturedAt: str | None = None  # ISO8601, defaults to now()


class UpdateNoteRequest(BaseModel):
    body: str


class RouteNoteRequest(BaseModel):
    context: str
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest ghostbrain/api/tests/test_models_note.py -v`
Expected: PASS — all 3 tests green.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/models/note.py ghostbrain/api/tests/test_models_note.py
git commit -m "feat(api): extend note model with manual-jot list/request schemas"
```

---

## Task 2: Manual jot repo — id/slug/tag helpers

**Files:**
- Create: `ghostbrain/api/repo/notes_manual.py`
- Test: `ghostbrain/api/tests/test_notes_manual_helpers.py` (create)

Pure functions only in this task. File I/O is in Task 3.

- [ ] **Step 1: Write the failing test**

Create `ghostbrain/api/tests/test_notes_manual_helpers.py`:

```python
"""Pure helpers for manual jot id, slug, and tag extraction."""
from datetime import datetime, timezone

from ghostbrain.api.repo.notes_manual import (
    extract_tags,
    make_jot_id,
    make_slug,
    title_from_body,
)


def test_make_slug_lowercases_and_collapses_non_alnum():
    assert make_slug("Ghostbrain Jot Idea!") == "ghostbrain-jot-idea"


def test_make_slug_truncates_to_32_chars():
    s = make_slug("a" * 100)
    assert len(s) == 32
    assert s == "a" * 32


def test_make_slug_strips_leading_and_trailing_dashes():
    assert make_slug("!!hello world!!") == "hello-world"


def test_make_slug_empty_falls_back_to_untitled():
    assert make_slug("") == "untitled"
    assert make_slug("###") == "untitled"


def test_make_jot_id_format():
    when = datetime(2026, 5, 14, 9, 30, 15, tzinfo=timezone.utc)
    jot_id = make_jot_id("Ghostbrain idea", when=when)
    assert jot_id == "manual-20260514T093015-ghostbrain-idea"


def test_extract_tags_finds_hashtags():
    body = "thinking about #ui and the #ascp-wizard flow #idea"
    assert extract_tags(body) == ["ui", "ascp-wizard", "idea"]


def test_extract_tags_deduplicates_and_preserves_first_order():
    body = "#a #b #a"
    assert extract_tags(body) == ["a", "b"]


def test_extract_tags_ignores_in_word_hashes():
    # `colour#fff` is not a tag — must be word-boundary-preceded.
    assert extract_tags("colour#fff is bold") == []


def test_title_from_body_uses_first_nonempty_line():
    assert title_from_body("\n\nfirst line\nsecond\n") == "first line"


def test_title_from_body_strips_markdown_headers():
    assert title_from_body("# my heading\nbody") == "my heading"


def test_title_from_body_truncates_long_titles():
    assert title_from_body("a" * 200) == "a" * 80
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest ghostbrain/api/tests/test_notes_manual_helpers.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write the helpers**

Create `ghostbrain/api/repo/notes_manual.py`:

```python
"""Helpers and file operations for manual jot notes.

Pure helpers in this module (id/slug/tag/title generation) are kept side-effect
free so they can be unit-tested without touching the filesystem. The file-I/O
helpers (write_jot, list_jots, ...) come in later tasks.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

_SLUG_MAX = 32
_TITLE_MAX = 80
_TAG_RE = re.compile(r"(?:^|\s)#([a-z0-9][a-z0-9-]*)", re.IGNORECASE)


def make_slug(text: str) -> str:
    """Lowercase, collapse non-alnum to '-', strip, truncate."""
    s = re.sub(r"[^a-z0-9]+", "-", text.lower())
    s = s.strip("-")
    if not s:
        return "untitled"
    return s[:_SLUG_MAX].rstrip("-") or "untitled"


def make_jot_id(first_line: str, *, when: datetime | None = None) -> str:
    """Produce `manual-{YYYYMMDDTHHMMSS}-{slug}`."""
    when = when or datetime.now(timezone.utc)
    ts = when.strftime("%Y%m%dT%H%M%S")
    return f"manual-{ts}-{make_slug(first_line)}"


def extract_tags(body: str) -> list[str]:
    """Find `#tag` hashtags at word boundaries; dedupe; preserve order; lowercase."""
    seen: dict[str, None] = {}
    for match in _TAG_RE.finditer(body):
        tag = match.group(1).lower()
        if tag not in seen:
            seen[tag] = None
    return list(seen.keys())


def title_from_body(body: str) -> str:
    """First non-empty line, markdown header strip, truncate to 80 chars."""
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^#{1,6}\s*", "", line)
        return line[:_TITLE_MAX]
    return "untitled"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest ghostbrain/api/tests/test_notes_manual_helpers.py -v`
Expected: PASS — 10 tests green.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/repo/notes_manual.py ghostbrain/api/tests/test_notes_manual_helpers.py
git commit -m "feat(api): add pure helpers for manual jot id, slug, tags, title"
```

---

## Task 3: Manual jot repo — file I/O (write + read + list + delete)

**Files:**
- Modify: `ghostbrain/api/repo/notes_manual.py`
- Test: `ghostbrain/api/tests/test_notes_manual_io.py` (create)

Routing wiring lives in Task 4 — this task only covers filesystem ops.

- [ ] **Step 1: Write the failing test**

Create `ghostbrain/api/tests/test_notes_manual_io.py`:

```python
"""Filesystem ops on the manual jot vault location."""
import os
from datetime import datetime, timezone
from pathlib import Path

import frontmatter
import pytest

from ghostbrain.api.repo.notes_manual import (
    JotIdConflict,
    JotNotFound,
    delete_jot,
    list_jots,
    move_jot,
    read_jot,
    update_jot_body,
    write_inbox_jot,
)


@pytest.fixture
def vault(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    (tmp_path / "00-inbox" / "raw" / "manual").mkdir(parents=True)
    (tmp_path / "20-contexts" / "sanlam" / "notes").mkdir(parents=True)
    return tmp_path


def test_write_inbox_jot_creates_file_with_frontmatter(vault):
    when = datetime(2026, 5, 14, 9, 30, 15, tzinfo=timezone.utc)
    record = write_inbox_jot("ghostbrain idea\n\nbody #ui", captured_at=when)
    assert record["id"] == "manual-20260514T093015-ghostbrain-idea"
    p = vault / record["path"]
    assert p.exists()
    fm = frontmatter.load(p)
    assert fm["source"] == "manual"
    assert fm["routingStatus"] == "pending"
    assert fm["tags"] == ["ui"]
    assert "body #ui" in fm.content


def test_write_inbox_jot_id_collision_appends_suffix(vault, monkeypatch):
    when = datetime(2026, 5, 14, 9, 30, 15, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "ghostbrain.api.repo.notes_manual._random_suffix",
        lambda: "abcd",
    )
    a = write_inbox_jot("same first line", captured_at=when)
    b = write_inbox_jot("same first line", captured_at=when)
    assert a["id"] != b["id"]
    assert b["id"].endswith("-abcd")


def test_list_jots_walks_inbox_and_routed_locations(vault):
    when = datetime(2026, 5, 14, 9, 30, 15, tzinfo=timezone.utc)
    inbox = write_inbox_jot("first jot", captured_at=when)
    later = datetime(2026, 5, 14, 10, 0, 0, tzinfo=timezone.utc)
    routed = write_inbox_jot("second jot routed", captured_at=later)
    move_jot(routed["id"], to_context="sanlam", confidence=0.82, method="llm",
             reasoning="test")
    page = list_jots()
    assert page["total"] == 2
    ids = [item["id"] for item in page["items"]]
    assert ids[0] == routed["id"]  # newer first
    assert ids[1] == inbox["id"]


def test_list_jots_respects_context_filter(vault):
    when = datetime(2026, 5, 14, 9, 30, 15, tzinfo=timezone.utc)
    a = write_inbox_jot("a", captured_at=when)
    b = write_inbox_jot("b", captured_at=when.replace(second=20))
    move_jot(b["id"], to_context="sanlam", confidence=1.0, method="user",
             reasoning="manual")
    page = list_jots(context="sanlam")
    assert [item["id"] for item in page["items"]] == [b["id"]]
    _ = a  # silence linter


def test_list_jots_substring_q_matches_title_and_body(vault):
    when = datetime(2026, 5, 14, 9, 30, 15, tzinfo=timezone.utc)
    write_inbox_jot("ghostbrain idea about ascp", captured_at=when)
    write_inbox_jot("unrelated thought", captured_at=when.replace(second=20))
    page = list_jots(q="ascp")
    assert page["total"] == 1
    assert "ascp" in page["items"][0]["title"]


def test_list_jots_tag_filter(vault):
    when = datetime(2026, 5, 14, 9, 30, 15, tzinfo=timezone.utc)
    write_inbox_jot("a #ui", captured_at=when)
    write_inbox_jot("b", captured_at=when.replace(second=20))
    page = list_jots(tag="ui")
    assert page["total"] == 1


def test_read_jot_returns_frontmatter_and_body(vault):
    when = datetime(2026, 5, 14, 9, 30, 15, tzinfo=timezone.utc)
    rec = write_inbox_jot("my jot", captured_at=when)
    note = read_jot(rec["id"])
    assert note["body"].startswith("my jot")
    assert note["frontmatter"]["id"] == rec["id"]


def test_read_jot_unknown_raises(vault):
    with pytest.raises(JotNotFound):
        read_jot("manual-20990101T000000-nope")


def test_update_jot_body_rewrites_file_and_bumps_updated(vault):
    when = datetime(2026, 5, 14, 9, 30, 15, tzinfo=timezone.utc)
    rec = write_inbox_jot("original", captured_at=when)
    original_updated = read_jot(rec["id"])["frontmatter"]["updated"]
    # ensure the timestamps differ
    os.utime(vault / rec["path"], (0, 0))
    update_jot_body(rec["id"], "rewritten body #new")
    after = read_jot(rec["id"])
    assert after["body"].strip() == "rewritten body #new"
    assert after["frontmatter"]["tags"] == ["new"]
    assert after["frontmatter"]["updated"] != original_updated


def test_move_jot_moves_file_and_updates_frontmatter(vault):
    when = datetime(2026, 5, 14, 9, 30, 15, tzinfo=timezone.utc)
    rec = write_inbox_jot("routing me", captured_at=when)
    move_jot(rec["id"], to_context="sanlam", confidence=0.7, method="llm",
             reasoning="content matches sanlam terminology")
    note = read_jot(rec["id"])
    assert note["path"].startswith("20-contexts/sanlam/notes/")
    assert note["frontmatter"]["context"] == "sanlam"
    assert note["frontmatter"]["routingStatus"] == "routed"
    assert note["frontmatter"]["routingConfidence"] == 0.7


def test_delete_jot_removes_file(vault):
    when = datetime(2026, 5, 14, 9, 30, 15, tzinfo=timezone.utc)
    rec = write_inbox_jot("ephemeral", captured_at=when)
    delete_jot(rec["id"])
    with pytest.raises(JotNotFound):
        read_jot(rec["id"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest ghostbrain/api/tests/test_notes_manual_io.py -v`
Expected: FAIL — `JotIdConflict`, `JotNotFound`, `write_inbox_jot`, etc. don't exist.

- [ ] **Step 3: Implement the file ops**

Append to `ghostbrain/api/repo/notes_manual.py` (after the existing pure helpers):

```python
import logging
import secrets
import shutil
from pathlib import Path
from typing import Any, Iterable

import frontmatter

from ghostbrain.paths import vault_path

log = logging.getLogger("ghostbrain.api.repo.notes_manual")

INBOX_REL = "00-inbox/raw/manual"
CONTEXT_NOTES_TEMPLATE = "20-contexts/{context}/notes"


class JotNotFound(Exception):
    pass


class JotIdConflict(Exception):
    pass


def _random_suffix() -> str:
    return secrets.token_hex(2)  # 4 hex chars


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _vault() -> Path:
    return vault_path().resolve()


def _inbox_dir() -> Path:
    p = _vault() / INBOX_REL
    p.mkdir(parents=True, exist_ok=True)
    return p


def _context_dir(context: str) -> Path:
    p = _vault() / CONTEXT_NOTES_TEMPLATE.format(context=context)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _find_file(jot_id: str) -> Path:
    """Locate a jot by id, regardless of where the router moved it."""
    vault = _vault()
    # Check inbox first (cheap, most common during pending state).
    candidate = _inbox_dir() / f"{jot_id}.md"
    if candidate.exists():
        return candidate
    # Walk every routed context folder.
    contexts_root = vault / "20-contexts"
    if contexts_root.exists():
        for ctx_dir in contexts_root.iterdir():
            notes_dir = ctx_dir / "notes"
            if not notes_dir.is_dir():
                continue
            candidate = notes_dir / f"{jot_id}.md"
            if candidate.exists():
                return candidate
    raise JotNotFound(jot_id)


def _vault_rel(path: Path) -> str:
    return str(path.resolve().relative_to(_vault()))


def write_inbox_jot(body: str, *, captured_at: "datetime | None" = None) -> dict:
    """Write a new jot to the inbox folder. Returns {id, path}."""
    from datetime import datetime, timezone

    captured_at = captured_at or datetime.now(timezone.utc)
    first_line = title_from_body(body)
    jot_id = make_jot_id(first_line, when=captured_at)
    target = _inbox_dir() / f"{jot_id}.md"
    if target.exists():
        jot_id = f"{jot_id}-{_random_suffix()}"
        target = _inbox_dir() / f"{jot_id}.md"
        if target.exists():
            raise JotIdConflict(jot_id)
    post = frontmatter.Post(
        body,
        id=jot_id,
        type="note",
        source="manual",
        context=None,
        created=captured_at.isoformat(),
        updated=captured_at.isoformat(),
        ingestedAt=_now_iso(),
        routingStatus="pending",
        routingConfidence=None,
        routingMethod=None,
        routingReasoning=None,
        tags=extract_tags(body),
    )
    target.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    log.info("wrote inbox jot id=%s", jot_id)
    return {"id": jot_id, "path": _vault_rel(target)}


def read_jot(jot_id: str) -> dict:
    path = _find_file(jot_id)
    post = frontmatter.load(path)
    fm = {str(k): _jsonable(v) for k, v in post.metadata.items()}
    return {
        "path": _vault_rel(path),
        "title": title_from_body(post.content or fm.get("id") or ""),
        "body": post.content or "",
        "frontmatter": fm,
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def update_jot_body(jot_id: str, new_body: str) -> dict:
    path = _find_file(jot_id)
    post = frontmatter.load(path)
    post.content = new_body
    post["updated"] = _now_iso()
    post["tags"] = extract_tags(new_body)
    path.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    return {"id": jot_id, "path": _vault_rel(path), "updated": post["updated"]}


def move_jot(
    jot_id: str,
    *,
    to_context: str,
    confidence: float,
    method: str,
    reasoning: str,
) -> dict:
    src = _find_file(jot_id)
    dst = _context_dir(to_context) / f"{jot_id}.md"
    if src.resolve() == dst.resolve():
        return {"id": jot_id, "path": _vault_rel(dst), "context": to_context}
    post = frontmatter.load(src)
    post["context"] = to_context
    post["routingStatus"] = "routed"
    post["routingConfidence"] = confidence
    post["routingMethod"] = method
    post["routingReasoning"] = reasoning
    post["updated"] = _now_iso()
    dst.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    src.unlink()
    log.info("moved jot id=%s -> %s", jot_id, to_context)
    return {"id": jot_id, "path": _vault_rel(dst), "context": to_context}


def mark_manual_review(jot_id: str, reasoning: str) -> dict:
    """Keep the file at inbox path; set routingStatus=manual_review."""
    path = _find_file(jot_id)
    post = frontmatter.load(path)
    post["routingStatus"] = "manual_review"
    post["routingReasoning"] = reasoning
    post["updated"] = _now_iso()
    path.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    return {"id": jot_id, "path": _vault_rel(path), "routingStatus": "manual_review"}


def delete_jot(jot_id: str) -> None:
    path = _find_file(jot_id)
    path.unlink()


def list_jots(
    *,
    limit: int = 100,
    offset: int = 0,
    q: str | None = None,
    context: str | None = None,
    tag: str | None = None,
) -> dict:
    """Walk inbox + every context folder, filter to source=manual."""
    items: list[dict] = []
    for path in _iter_manual_files():
        try:
            post = frontmatter.load(path)
        except Exception:
            continue
        if post.get("source") != "manual":
            continue
        body = post.content or ""
        item = {
            "id": post.get("id") or path.stem,
            "path": _vault_rel(path),
            "title": title_from_body(body),
            "excerpt": (body[:120] + "…") if len(body) > 120 else body,
            "context": post.get("context"),
            "routingStatus": post.get("routingStatus") or "pending",
            "tags": list(post.get("tags") or []),
            "created": post.get("created") or "",
            "updated": post.get("updated") or "",
        }
        if context is not None and item["context"] != context:
            continue
        if tag is not None and tag not in item["tags"]:
            continue
        if q is not None:
            needle = q.lower()
            if needle not in item["title"].lower() and needle not in body.lower():
                continue
        items.append(item)
    items.sort(key=lambda r: r["created"], reverse=True)
    total = len(items)
    return {"items": items[offset : offset + limit], "total": total}


def _iter_manual_files() -> Iterable[Path]:
    vault = _vault()
    inbox = vault / INBOX_REL
    if inbox.is_dir():
        yield from inbox.glob("manual-*.md")
    contexts_root = vault / "20-contexts"
    if contexts_root.is_dir():
        for ctx_dir in contexts_root.iterdir():
            notes_dir = ctx_dir / "notes"
            if notes_dir.is_dir():
                yield from notes_dir.glob("manual-*.md")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest ghostbrain/api/tests/test_notes_manual_io.py -v`
Expected: PASS — all 11 tests green.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/repo/notes_manual.py ghostbrain/api/tests/test_notes_manual_io.py
git commit -m "feat(api): add filesystem ops for manual jots (write/read/list/move/delete)"
```

---

## Task 4: POST /v1/notes — create + route synchronously

**Files:**
- Modify: `ghostbrain/api/routes/notes.py`
- Modify: `ghostbrain/api/repo/notes_manual.py` (add `create_and_route_jot`)
- Test: `ghostbrain/api/tests/test_routes_notes_create.py` (create)

- [ ] **Step 1: Write the failing test**

Create `ghostbrain/api/tests/test_routes_notes_create.py`:

```python
"""POST /v1/notes — create a jot and route synchronously."""
from datetime import datetime, timezone
from pathlib import Path

import frontmatter
import pytest
from fastapi.testclient import TestClient

from ghostbrain.api.main import app
from ghostbrain.worker.router import RoutingDecision


@pytest.fixture
def vault(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    (tmp_path / "00-inbox" / "raw" / "manual").mkdir(parents=True)
    (tmp_path / "20-contexts" / "sanlam" / "notes").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def client():
    return TestClient(app)


def test_post_notes_writes_routes_and_returns_routed(vault, client, monkeypatch):
    monkeypatch.setattr(
        "ghostbrain.api.repo.notes_manual.route_event",
        lambda event, **kw: RoutingDecision(
            context="sanlam", confidence=0.82, reasoning="matches sanlam",
            method="llm", secondary_contexts=[],
        ),
    )
    resp = client.post("/v1/notes", json={"body": "ascp wizard idea"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["routingStatus"] == "routed"
    assert data["path"].startswith("20-contexts/sanlam/notes/")
    fm = frontmatter.load(vault / data["path"])
    assert fm["context"] == "sanlam"
    assert fm["routingMethod"] == "llm"


def test_post_notes_low_confidence_falls_back_to_manual_review(
    vault, client, monkeypatch,
):
    monkeypatch.setattr(
        "ghostbrain.api.repo.notes_manual.route_event",
        lambda event, **kw: RoutingDecision(
            context="needs_review", confidence=0.0,
            reasoning="no classifiable content",
            method="fallback", secondary_contexts=[],
        ),
    )
    resp = client.post("/v1/notes", json={"body": "..."})
    assert resp.status_code == 200
    data = resp.json()
    assert data["routingStatus"] == "manual_review"
    assert data["path"].startswith("00-inbox/raw/manual/")


def test_post_notes_router_exception_falls_back_to_manual_review(
    vault, client, monkeypatch,
):
    def boom(event, **kw):
        raise RuntimeError("LLM timeout")
    monkeypatch.setattr("ghostbrain.api.repo.notes_manual.route_event", boom)
    resp = client.post("/v1/notes", json={"body": "anything"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["routingStatus"] == "manual_review"


def test_post_notes_empty_body_rejected(vault, client):
    resp = client.post("/v1/notes", json={"body": ""})
    assert resp.status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest ghostbrain/api/tests/test_routes_notes_create.py -v`
Expected: FAIL — `POST /v1/notes` doesn't exist; `create_and_route_jot` doesn't exist.

- [ ] **Step 3: Add `create_and_route_jot` to the repo**

Append to `ghostbrain/api/repo/notes_manual.py`:

```python
from ghostbrain.worker.audit import audit_log
from ghostbrain.worker.router import route_event


REJECT_BELOW = 0.5  # below this confidence, jot falls back to manual_review


def create_and_route_jot(body: str, *, captured_at: "datetime | None" = None) -> dict:
    """Write a jot to the inbox, classify it, and (on success) move it to a
    context folder. Returns the public response payload.

    Routing errors and low-confidence results both leave the file in the inbox
    with routingStatus="manual_review" — never raises to the caller. The hotkey
    overlay is fire-and-forget, so callers need a stable contract.
    """
    record = write_inbox_jot(body, captured_at=captured_at)
    jot_id = record["id"]

    try:
        decision = route_event({"source": "manual", "id": jot_id, "body": body})
    except Exception as exc:
        log.exception("manual jot routing failed id=%s", jot_id)
        mark_manual_review(jot_id, reasoning=f"router error: {exc}")
        audit_log("manual_jot_route_failed", event_id=jot_id, error=str(exc))
        return {"id": jot_id, "path": record["path"],
                "routingStatus": "manual_review"}

    if decision.context == "needs_review" or decision.confidence < REJECT_BELOW:
        mark_manual_review(jot_id, reasoning=decision.reasoning)
        audit_log(
            "manual_jot_routed", event_id=jot_id,
            status="manual_review", confidence=decision.confidence,
            reasoning=decision.reasoning,
        )
        return {"id": jot_id, "path": record["path"],
                "routingStatus": "manual_review"}

    moved = move_jot(
        jot_id,
        to_context=decision.context,
        confidence=decision.confidence,
        method=decision.method,
        reasoning=decision.reasoning,
    )
    audit_log(
        "manual_jot_routed", event_id=jot_id,
        status="routed", context=decision.context,
        confidence=decision.confidence, reasoning=decision.reasoning,
    )
    return {"id": jot_id, "path": moved["path"], "routingStatus": "routed"}
```

- [ ] **Step 4: Wire up the POST route**

Replace `ghostbrain/api/routes/notes.py`:

```python
"""Notes endpoints — read by path (legacy), and the manual-jot family."""
from fastapi import APIRouter, HTTPException, Query, status

from ghostbrain.api.models.note import (
    CreateNoteRequest,
    Note,
    NotesPage,
)
from ghostbrain.api.repo.note import NoteInvalidPath, NoteNotFound, get_note
from ghostbrain.api.repo.notes_manual import create_and_route_jot

router = APIRouter(prefix="/v1/notes", tags=["notes"])


@router.get("", response_model=Note)
def note(path: str = Query(..., min_length=1, max_length=500)) -> dict:
    """Read a note by vault-relative path (legacy single-file viewer)."""
    try:
        return get_note(path)
    except NoteInvalidPath as e:
        raise HTTPException(status_code=400, detail=str(e))
    except NoteNotFound:
        raise HTTPException(status_code=404, detail=f"Note not found: {path}")


@router.post("", status_code=status.HTTP_200_OK)
def create_note(req: CreateNoteRequest) -> dict:
    """Create a manual jot and route it synchronously."""
    body = req.body.strip()
    if not body:
        raise HTTPException(status_code=422, detail="body must not be empty")
    captured = None
    if req.capturedAt:
        from datetime import datetime
        try:
            captured = datetime.fromisoformat(req.capturedAt)
        except ValueError:
            raise HTTPException(status_code=422, detail="capturedAt must be ISO8601")
    return create_and_route_jot(body, captured_at=captured)
```

Note: the GET-by-path route stays — it's used by the existing markdown viewer.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest ghostbrain/api/tests/test_routes_notes_create.py -v`
Expected: PASS — all 4 tests green.

- [ ] **Step 6: Commit**

```bash
git add ghostbrain/api/routes/notes.py ghostbrain/api/repo/notes_manual.py \
        ghostbrain/api/tests/test_routes_notes_create.py
git commit -m "feat(api): POST /v1/notes — create jot and route synchronously"
```

---

## Task 5: GET /v1/notes — list manual jots with filters

**Files:**
- Modify: `ghostbrain/api/routes/notes.py`
- Test: `ghostbrain/api/tests/test_routes_notes_list.py` (create)

- [ ] **Step 1: Write the failing test**

Create `ghostbrain/api/tests/test_routes_notes_list.py`:

```python
"""GET /v1/notes?source=manual — list jots for the Jot screen."""
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ghostbrain.api.main import app
from ghostbrain.api.repo.notes_manual import write_inbox_jot, move_jot


@pytest.fixture
def vault(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    (tmp_path / "00-inbox" / "raw" / "manual").mkdir(parents=True)
    (tmp_path / "20-contexts" / "sanlam" / "notes").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def client():
    return TestClient(app)


def _seed_two(vault):
    t1 = datetime(2026, 5, 14, 9, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 5, 14, 10, 0, 0, tzinfo=timezone.utc)
    a = write_inbox_jot("first jot #ui", captured_at=t1)
    b = write_inbox_jot("second jot ascp #idea", captured_at=t2)
    move_jot(b["id"], to_context="sanlam", confidence=0.9, method="llm",
             reasoning="t")
    return a, b


def test_list_returns_both_inbox_and_routed(vault, client):
    a, b = _seed_two(vault)
    resp = client.get("/v1/notes?source=manual")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    ids = [item["id"] for item in data["items"]]
    assert ids == [b["id"], a["id"]]


def test_list_q_filter(vault, client):
    _seed_two(vault)
    resp = client.get("/v1/notes?source=manual&q=ascp")
    data = resp.json()
    assert data["total"] == 1
    assert "ascp" in data["items"][0]["title"]


def test_list_tag_filter(vault, client):
    _seed_two(vault)
    resp = client.get("/v1/notes?source=manual&tag=ui")
    data = resp.json()
    assert data["total"] == 1
    assert "ui" in data["items"][0]["tags"]


def test_list_context_filter(vault, client):
    a, b = _seed_two(vault)
    resp = client.get("/v1/notes?source=manual&context=sanlam")
    data = resp.json()
    assert [item["id"] for item in data["items"]] == [b["id"]]
    _ = a


def test_list_unsupported_source_rejected(vault, client):
    resp = client.get("/v1/notes?source=slack")
    assert resp.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest ghostbrain/api/tests/test_routes_notes_list.py -v`
Expected: FAIL — GET takes a `path` only; list semantics not implemented.

- [ ] **Step 3: Differentiate GET by query shape**

Replace the `note` route in `ghostbrain/api/routes/notes.py` with a list-or-detail dispatcher. Update `ghostbrain/api/routes/notes.py`:

```python
"""Notes endpoints — read by path (legacy), and the manual-jot family."""
from fastapi import APIRouter, HTTPException, Query, Request, status

from ghostbrain.api.models.note import (
    CreateNoteRequest,
    Note,
    NotesPage,
)
from ghostbrain.api.repo.note import NoteInvalidPath, NoteNotFound, get_note
from ghostbrain.api.repo.notes_manual import create_and_route_jot, list_jots

router = APIRouter(prefix="/v1/notes", tags=["notes"])


@router.get("")
def get_notes(
    request: Request,
    path: str | None = Query(None, min_length=1, max_length=500),
    source: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    q: str | None = Query(None),
    context: str | None = Query(None),
    tag: str | None = Query(None),
):
    """Dispatcher:
    - `?path=...`  → single-note read (legacy markdown viewer).
    - `?source=manual` → list manual jots for the Jot screen.
    """
    if path is not None:
        try:
            return get_note(path)
        except NoteInvalidPath as e:
            raise HTTPException(status_code=400, detail=str(e))
        except NoteNotFound:
            raise HTTPException(status_code=404, detail=f"Note not found: {path}")
    if source == "manual":
        return list_jots(limit=limit, offset=offset, q=q, context=context, tag=tag)
    if source is None:
        raise HTTPException(
            status_code=400, detail="provide `path` or `source=manual`",
        )
    raise HTTPException(
        status_code=400, detail=f"unsupported source filter: {source}",
    )


@router.post("", status_code=status.HTTP_200_OK)
def create_note(req: CreateNoteRequest) -> dict:
    body = req.body.strip()
    if not body:
        raise HTTPException(status_code=422, detail="body must not be empty")
    captured = None
    if req.capturedAt:
        from datetime import datetime
        try:
            captured = datetime.fromisoformat(req.capturedAt)
        except ValueError:
            raise HTTPException(status_code=422, detail="capturedAt must be ISO8601")
    return create_and_route_jot(body, captured_at=captured)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest ghostbrain/api/tests/test_routes_notes_list.py ghostbrain/api/tests/test_routes_notes_create.py -v`
Expected: PASS — list tests + earlier create tests still green.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/routes/notes.py ghostbrain/api/tests/test_routes_notes_list.py
git commit -m "feat(api): GET /v1/notes?source=manual — list jots with q/tag/context filters"
```

---

## Task 6: PATCH / POST route / DELETE on /v1/notes/{id}

**Files:**
- Modify: `ghostbrain/api/routes/notes.py`
- Test: `ghostbrain/api/tests/test_routes_notes_mutate.py` (create)

- [ ] **Step 1: Write the failing test**

Create `ghostbrain/api/tests/test_routes_notes_mutate.py`:

```python
"""PATCH/DELETE/route endpoints for individual jots."""
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ghostbrain.api.main import app
from ghostbrain.api.repo.notes_manual import write_inbox_jot


@pytest.fixture
def vault(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    (tmp_path / "00-inbox" / "raw" / "manual").mkdir(parents=True)
    (tmp_path / "20-contexts" / "sanlam" / "notes").mkdir(parents=True)
    (tmp_path / "20-contexts" / "codeship" / "notes").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def client():
    return TestClient(app)


def test_patch_updates_body(vault, client):
    when = datetime(2026, 5, 14, 9, 0, 0, tzinfo=timezone.utc)
    rec = write_inbox_jot("original", captured_at=when)
    resp = client.patch(f"/v1/notes/{rec['id']}", json={"body": "new body #x"})
    assert resp.status_code == 200
    read = client.get(f"/v1/notes?path={resp.json()['path']}").json()
    assert read["body"].strip() == "new body #x"
    assert read["frontmatter"]["tags"] == ["x"]


def test_patch_unknown_returns_404(vault, client):
    resp = client.patch("/v1/notes/manual-19000101T000000-nope", json={"body": "x"})
    assert resp.status_code == 404


def test_route_moves_to_chosen_context(vault, client):
    when = datetime(2026, 5, 14, 9, 0, 0, tzinfo=timezone.utc)
    rec = write_inbox_jot("re-route me", captured_at=when)
    resp = client.post(
        f"/v1/notes/{rec['id']}/route", json={"context": "codeship"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["context"] == "codeship"
    assert data["path"].startswith("20-contexts/codeship/notes/")


def test_route_rejects_unknown_context(vault, client):
    when = datetime(2026, 5, 14, 9, 0, 0, tzinfo=timezone.utc)
    rec = write_inbox_jot("x", captured_at=when)
    resp = client.post(
        f"/v1/notes/{rec['id']}/route", json={"context": "not-a-real-ctx"},
    )
    assert resp.status_code == 400


def test_delete_removes_file(vault, client):
    when = datetime(2026, 5, 14, 9, 0, 0, tzinfo=timezone.utc)
    rec = write_inbox_jot("ephemeral", captured_at=when)
    resp = client.delete(f"/v1/notes/{rec['id']}")
    assert resp.status_code == 204
    resp2 = client.patch(f"/v1/notes/{rec['id']}", json={"body": "x"})
    assert resp2.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest ghostbrain/api/tests/test_routes_notes_mutate.py -v`
Expected: FAIL — PATCH/route/DELETE endpoints don't exist.

- [ ] **Step 3: Implement the mutation routes**

Append to `ghostbrain/api/routes/notes.py`:

```python
from fastapi import Path as PathParam
from fastapi.responses import Response

from ghostbrain.api.models.note import RouteNoteRequest, UpdateNoteRequest
from ghostbrain.api.repo.notes_manual import (
    JotNotFound,
    delete_jot,
    move_jot,
    update_jot_body,
)


# Known contexts must match the router's enum — keep this list in sync with
# ghostbrain/worker/router.py:ROUTER_JSON_SCHEMA. If a context is added there,
# add it here too.
_KNOWN_CONTEXTS = {"sanlam", "codeship", "reducedrecipes", "personal"}


@router.patch("/{jot_id}")
def patch_note(
    req: UpdateNoteRequest,
    jot_id: str = PathParam(..., min_length=8, max_length=128),
) -> dict:
    body = req.body
    if not body.strip():
        raise HTTPException(status_code=422, detail="body must not be empty")
    try:
        return update_jot_body(jot_id, body)
    except JotNotFound:
        raise HTTPException(status_code=404, detail=f"Jot not found: {jot_id}")


@router.post("/{jot_id}/route")
def route_note(
    req: RouteNoteRequest,
    jot_id: str = PathParam(..., min_length=8, max_length=128),
) -> dict:
    if req.context not in _KNOWN_CONTEXTS:
        raise HTTPException(
            status_code=400,
            detail=f"unknown context: {req.context}",
        )
    try:
        return move_jot(
            jot_id,
            to_context=req.context,
            confidence=1.0,
            method="user",
            reasoning="manual re-route by user",
        )
    except JotNotFound:
        raise HTTPException(status_code=404, detail=f"Jot not found: {jot_id}")


@router.delete("/{jot_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(
    jot_id: str = PathParam(..., min_length=8, max_length=128),
) -> Response:
    try:
        delete_jot(jot_id)
    except JotNotFound:
        raise HTTPException(status_code=404, detail=f"Jot not found: {jot_id}")
    return Response(status_code=204)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest ghostbrain/api/tests/test_routes_notes_mutate.py -v`
Expected: PASS — all 5 tests green.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/routes/notes.py ghostbrain/api/tests/test_routes_notes_mutate.py
git commit -m "feat(api): PATCH /v1/notes/{id}, POST .../route, DELETE — jot mutations"
```

---

## Task 7: Extend api-forwarder for PATCH and DELETE

**Files:**
- Modify: `desktop/src/main/api-forwarder.ts`
- Modify: `desktop/src/preload/index.ts`
- Modify: `desktop/src/shared/types.ts`
- Test: `desktop/src/main/__tests__/api-forwarder.test.ts` (create or extend)

- [ ] **Step 1: Inspect what exists**

Run: `cat desktop/src/main/api-forwarder.ts`
Note the current method type `'GET' | 'POST'` — we need to widen it.

- [ ] **Step 2: Write the failing test**

Create or extend `desktop/src/main/__tests__/api-forwarder.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { forward } from '../api-forwarder';

const fetchMock = vi.fn();
beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
});

describe('api forwarder', () => {
  it('forwards PATCH with a JSON body', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ id: 'manual-x', path: 'p', updated: 't' }),
    });
    const result = await forward('PATCH', '/v1/notes/manual-x', { body: 'new' });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/v1/notes/manual-x'),
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({ body: 'new' }),
      }),
    );
    expect(result.ok).toBe(true);
  });

  it('forwards DELETE with no body and returns ok on 204', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 204,
      json: async () => ({}),
    });
    const result = await forward('DELETE', '/v1/notes/manual-x');
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/v1/notes/manual-x'),
      expect.objectContaining({ method: 'DELETE' }),
    );
    expect(result.ok).toBe(true);
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd desktop && npx vitest run src/main/__tests__/api-forwarder.test.ts`
Expected: FAIL — TypeScript rejects `'PATCH'`/`'DELETE'` for the method parameter, or runtime fails because the function only allows GET/POST.

- [ ] **Step 4: Widen the method type and handle 204**

Edit `desktop/src/main/api-forwarder.ts`. Change the signature to accept the wider union and pass the body conditionally:

```typescript
export type HttpMethod = 'GET' | 'POST' | 'PATCH' | 'DELETE';

export async function forward(
  method: HttpMethod,
  path: string,
  body?: unknown,
): Promise<ApiResult<unknown>> {
  const init: RequestInit = {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  };
  const url = `${baseUrl()}${path}`;
  const res = await fetch(url, init);
  if (res.status === 204) {
    return { ok: true, status: 204, data: null };
  }
  const json = await res.json().catch(() => ({}));
  if (!res.ok) {
    return {
      ok: false,
      status: res.status,
      error: (json as { detail?: string }).detail ?? `${method} ${path} failed`,
    };
  }
  return { ok: true, status: res.status, data: json };
}
```

If the existing module already defines `baseUrl()` and `ApiResult` differently, preserve those and only widen the method param. The key changes: union type, no body coercion for DELETE, 204 short-circuit.

- [ ] **Step 5: Widen the preload + shared type**

Edit `desktop/src/shared/types.ts` — find the `request` field on the `window.gb.api` type and widen its method:

```typescript
request<T = unknown>(
  method: 'GET' | 'POST' | 'PATCH' | 'DELETE',
  path: string,
  body?: unknown,
): Promise<ApiResult<T>>;
```

Edit `desktop/src/preload/index.ts` — the existing IPC bridge already forwards `(method, path, body)`; no change needed beyond the type.

- [ ] **Step 6: Widen the renderer client**

Edit `desktop/src/renderer/lib/api/client.ts`. Add helpers for PATCH and DELETE, mirroring the existing `get`/`post`:

```typescript
export async function patch<T>(path: string, body?: unknown): Promise<T> {
  const result = await window.gb.api.request<T>('PATCH', path, body);
  if (!result.ok) throw new Error(result.error);
  return result.data;
}

export async function del<T = null>(path: string): Promise<T> {
  const result = await window.gb.api.request<T>('DELETE', path);
  if (!result.ok) throw new Error(result.error);
  return result.data as T;
}
```

(`del` not `delete` — `delete` is a reserved word.)

- [ ] **Step 7: Run test to verify it passes**

Run: `cd desktop && npx vitest run src/main/__tests__/api-forwarder.test.ts`
Expected: PASS — both new tests green.

Also run: `cd desktop && npx tsc --noEmit`
Expected: no type errors.

- [ ] **Step 8: Commit**

```bash
git add desktop/src/main/api-forwarder.ts desktop/src/main/__tests__/api-forwarder.test.ts \
        desktop/src/preload/index.ts desktop/src/shared/types.ts \
        desktop/src/renderer/lib/api/client.ts
git commit -m "feat(desktop): widen api-forwarder to PATCH/DELETE for jot mutations"
```

---

## Task 8: Add the Jot global hotkey + overlay window in Electron main

**Files:**
- Create: `desktop/src/main/jot-overlay.ts`
- Modify: `desktop/src/main/index.ts`
- Modify: `desktop/src/shared/settings-schema.ts` (add hotkey setting)
- Test: `desktop/src/main/__tests__/jot-overlay.test.ts` (create)

- [ ] **Step 1: Add the hotkey setting**

Edit `desktop/src/shared/settings-schema.ts`. Add a `hotkeys` block to the schema:

```typescript
export const settingsSchema = z.object({
  // ... existing fields ...
  hotkeys: z.object({
    jotOverlay: z.string().default('Alt+J'),  // Electron accelerator format
  }).default({ jotOverlay: 'Alt+J' }),
});
```

Note: Electron uses `'Alt'` rather than `'Option'` even on macOS.

- [ ] **Step 2: Write the failing test**

Create `desktop/src/main/__tests__/jot-overlay.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';

const globalShortcutMock = {
  register: vi.fn().mockReturnValue(true),
  unregister: vi.fn(),
  unregisterAll: vi.fn(),
};
const browserWindowMock = vi.fn().mockImplementation(() => ({
  loadFile: vi.fn(),
  loadURL: vi.fn(),
  show: vi.fn(),
  hide: vi.fn(),
  isVisible: vi.fn().mockReturnValue(false),
  on: vi.fn(),
  webContents: { send: vi.fn() },
}));

vi.mock('electron', () => ({
  app: { whenReady: () => Promise.resolve() },
  BrowserWindow: browserWindowMock,
  globalShortcut: globalShortcutMock,
  ipcMain: { handle: vi.fn(), on: vi.fn() },
  screen: { getCursorScreenPoint: () => ({ x: 0, y: 0 }),
            getDisplayNearestPoint: () => ({ bounds: { x: 0, y: 0, width: 1920, height: 1080 } }) },
}));

import { installJotOverlay, openJotOverlay } from '../jot-overlay';

describe('jot overlay', () => {
  beforeEach(() => {
    globalShortcutMock.register.mockClear();
    browserWindowMock.mockClear();
  });

  it('registers the configured accelerator at install time', () => {
    installJotOverlay({ accelerator: 'Alt+J' });
    expect(globalShortcutMock.register).toHaveBeenCalledWith(
      'Alt+J',
      expect.any(Function),
    );
  });

  it('logs but does not throw when registration fails', () => {
    globalShortcutMock.register.mockReturnValueOnce(false);
    expect(() => installJotOverlay({ accelerator: 'Alt+J' })).not.toThrow();
  });

  it('creates the overlay window lazily on first open', () => {
    installJotOverlay({ accelerator: 'Alt+J' });
    expect(browserWindowMock).not.toHaveBeenCalled();
    openJotOverlay();
    expect(browserWindowMock).toHaveBeenCalledTimes(1);
    openJotOverlay();
    expect(browserWindowMock).toHaveBeenCalledTimes(1); // reused
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd desktop && npx vitest run src/main/__tests__/jot-overlay.test.ts`
Expected: FAIL — `../jot-overlay` does not exist.

- [ ] **Step 4: Implement the overlay module**

Create `desktop/src/main/jot-overlay.ts`:

```typescript
import { BrowserWindow, globalShortcut, ipcMain, screen } from 'electron';
import { join } from 'node:path';
import { forward } from './api-forwarder';

const OVERLAY_WIDTH = 480;
const OVERLAY_HEIGHT = 260;

let overlay: BrowserWindow | null = null;

export interface JotOverlayOptions {
  accelerator: string;
  rendererUrl?: string;  // dev mode
  rendererFile?: string; // prod mode (packaged path)
}

let options: JotOverlayOptions | null = null;

function buildOverlay(): BrowserWindow {
  const cursor = screen.getCursorScreenPoint();
  const display = screen.getDisplayNearestPoint(cursor);
  const x = display.bounds.x + Math.round((display.bounds.width - OVERLAY_WIDTH) / 2);
  const y = display.bounds.y + Math.round((display.bounds.height - OVERLAY_HEIGHT) / 3);

  const win = new BrowserWindow({
    width: OVERLAY_WIDTH,
    height: OVERLAY_HEIGHT,
    x,
    y,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    resizable: false,
    show: false,
    vibrancy: 'hud',
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  if (options?.rendererUrl) {
    win.loadURL(options.rendererUrl);
  } else if (options?.rendererFile) {
    win.loadFile(options.rendererFile);
  }

  win.on('blur', () => win.hide());
  return win;
}

export function openJotOverlay(): void {
  if (!overlay) {
    overlay = buildOverlay();
  }
  overlay.show();
  overlay.focus();
  overlay.webContents.send('gb:jot:focus');
}

export function closeJotOverlay(): void {
  overlay?.hide();
}

export function installJotOverlay(opts: JotOverlayOptions): void {
  options = opts;
  const registered = globalShortcut.register(opts.accelerator, () => {
    openJotOverlay();
  });
  if (!registered) {
    console.error(`[jot-overlay] failed to register accelerator: ${opts.accelerator}`);
  }

  // IPC: renderer fires save (fire-and-forget). We close the overlay
  // immediately and run the POST in the background.
  ipcMain.handle('gb:jot:save', async (_e, body: string) => {
    closeJotOverlay();
    // Don't await — surface failures via a follow-up event.
    forward('POST', '/v1/notes', { body })
      .then((res) => {
        if (!res.ok) {
          BrowserWindow.getAllWindows().forEach((w) =>
            w.webContents.send('gb:jot:save-failed', { body, error: res.error }),
          );
        }
      })
      .catch((err: unknown) => {
        BrowserWindow.getAllWindows().forEach((w) =>
          w.webContents.send('gb:jot:save-failed', {
            body, error: err instanceof Error ? err.message : String(err),
          }),
        );
      });
    return { ok: true };
  });

  ipcMain.handle('gb:jot:cancel', () => {
    closeJotOverlay();
    return { ok: true };
  });
}
```

- [ ] **Step 5: Wire it into the main process**

Edit `desktop/src/main/index.ts`. Add an import and call `installJotOverlay` after `app.whenReady()`:

```typescript
import { installJotOverlay } from './jot-overlay';

// inside the existing whenReady block (after `createWindow()`):
installJotOverlay({
  accelerator: settings.getAll().hotkeys?.jotOverlay ?? 'Alt+J',
  rendererUrl: is.dev ? `${process.env.ELECTRON_RENDERER_URL}/overlay.html` : undefined,
  rendererFile: !is.dev ? join(__dirname, '../renderer/overlay.html') : undefined,
});
```

(If `is.dev` is unavailable in this file, adapt to the existing convention used for the main window.)

Also ensure the global shortcut is unregistered on quit. Add to the existing `before-quit` handler:

```typescript
import { globalShortcut } from 'electron';
app.on('will-quit', () => globalShortcut.unregisterAll());
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd desktop && npx vitest run src/main/__tests__/jot-overlay.test.ts`
Expected: PASS — all 3 tests green.

- [ ] **Step 7: Commit**

```bash
git add desktop/src/main/jot-overlay.ts desktop/src/main/index.ts \
        desktop/src/main/__tests__/jot-overlay.test.ts \
        desktop/src/shared/settings-schema.ts
git commit -m "feat(desktop): global ⌥-J hotkey + overlay window lifecycle"
```

---

## Task 9: Overlay renderer entry point

**Files:**
- Create: `desktop/src/renderer/overlay.html`
- Create: `desktop/src/renderer/overlay/main.tsx`
- Create: `desktop/src/renderer/overlay/Overlay.tsx`
- Modify: `desktop/src/preload/index.ts` (expose `window.gb.jot`)
- Modify: `desktop/src/shared/types.ts` (declare `gb.jot`)
- Modify: `desktop/electron.vite.config.ts` (register the overlay entry)
- Test: `desktop/src/renderer/overlay/__tests__/Overlay.test.tsx` (create)

- [ ] **Step 1: Expose the IPC bridge**

Edit `desktop/src/preload/index.ts`. Add a `jot` block alongside the existing `api`:

```typescript
contextBridge.exposeInMainWorld('gb', {
  // ... existing fields ...
  jot: {
    save: (body: string) => ipcRenderer.invoke('gb:jot:save', body),
    cancel: () => ipcRenderer.invoke('gb:jot:cancel'),
    onFocus: (cb: () => void) => {
      const handler = () => cb();
      ipcRenderer.on('gb:jot:focus', handler);
      return () => ipcRenderer.removeListener('gb:jot:focus', handler);
    },
    onSaveFailed: (cb: (payload: { body: string; error: string }) => void) => {
      const handler = (_: unknown, payload: { body: string; error: string }) => cb(payload);
      ipcRenderer.on('gb:jot:save-failed', handler);
      return () => ipcRenderer.removeListener('gb:jot:save-failed', handler);
    },
  },
});
```

Edit `desktop/src/shared/types.ts` to add the matching type on `window.gb`:

```typescript
jot: {
  save(body: string): Promise<{ ok: true }>;
  cancel(): Promise<{ ok: true }>;
  onFocus(cb: () => void): () => void;
  onSaveFailed(cb: (payload: { body: string; error: string }) => void): () => void;
};
```

- [ ] **Step 2: Write the failing test**

Create `desktop/src/renderer/overlay/__tests__/Overlay.test.tsx`:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Overlay } from '../Overlay';

const save = vi.fn();
const cancel = vi.fn();
const onFocusCb: { current: (() => void) | null } = { current: null };

beforeEach(() => {
  save.mockReset();
  cancel.mockReset();
  // @ts-expect-error — window.gb is normally injected by preload
  window.gb = {
    jot: {
      save,
      cancel,
      onFocus: (cb: () => void) => { onFocusCb.current = cb; return () => {}; },
      onSaveFailed: () => () => {},
    },
  };
});

describe('Overlay', () => {
  it('autofocuses the textarea on mount', () => {
    render(<Overlay />);
    const ta = screen.getByPlaceholderText('jot a thought…') as HTMLTextAreaElement;
    expect(document.activeElement).toBe(ta);
  });

  it('saves on ⌘+Enter', () => {
    render(<Overlay />);
    const ta = screen.getByPlaceholderText('jot a thought…');
    fireEvent.change(ta, { target: { value: 'a thought' } });
    fireEvent.keyDown(ta, { key: 'Enter', metaKey: true });
    expect(save).toHaveBeenCalledWith('a thought');
  });

  it('cancels on Escape', () => {
    render(<Overlay />);
    const ta = screen.getByPlaceholderText('jot a thought…');
    fireEvent.keyDown(ta, { key: 'Escape' });
    expect(cancel).toHaveBeenCalled();
  });

  it('does not save with empty body', () => {
    render(<Overlay />);
    const ta = screen.getByPlaceholderText('jot a thought…');
    fireEvent.keyDown(ta, { key: 'Enter', metaKey: true });
    expect(save).not.toHaveBeenCalled();
  });

  it('clears the textarea when onFocus fires (overlay re-opened)', () => {
    render(<Overlay />);
    const ta = screen.getByPlaceholderText('jot a thought…') as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: 'old' } });
    expect(ta.value).toBe('old');
    onFocusCb.current?.();
    expect(ta.value).toBe('');
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd desktop && npx vitest run src/renderer/overlay/__tests__/Overlay.test.tsx`
Expected: FAIL — `../Overlay` doesn't exist.

- [ ] **Step 4: Implement the Overlay component**

Create `desktop/src/renderer/overlay/Overlay.tsx`:

```typescript
import { useEffect, useRef, useState } from 'react';

export function Overlay() {
  const ref = useRef<HTMLTextAreaElement | null>(null);
  const [body, setBody] = useState('');

  useEffect(() => {
    ref.current?.focus();
  }, []);

  useEffect(() => {
    const off = window.gb.jot.onFocus(() => {
      setBody('');
      ref.current?.focus();
    });
    return off;
  }, []);

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Escape') {
      e.preventDefault();
      window.gb.jot.cancel();
      return;
    }
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      const trimmed = body.trim();
      if (!trimmed) return;
      window.gb.jot.save(trimmed);
      setBody('');
    }
  }

  return (
    <div className="flex h-screen w-screen flex-col rounded-md border border-hairline bg-paper/95 backdrop-blur-md p-4">
      <textarea
        ref={ref}
        value={body}
        onChange={(e) => setBody(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="jot a thought…"
        className="flex-1 resize-none bg-transparent text-14 text-ink-0 outline-none"
        autoFocus
      />
      <div className="flex justify-between pt-2 font-mono text-10 text-ink-3">
        <span>⌘↵ save · esc cancel</span>
        <span>poltergeist</span>
      </div>
    </div>
  );
}
```

Create `desktop/src/renderer/overlay/main.tsx`:

```typescript
import { createRoot } from 'react-dom/client';
import '../index.css';  // share the design tokens
import { Overlay } from './Overlay';

const root = document.getElementById('root');
if (root) createRoot(root).render(<Overlay />);
```

Create `desktop/src/renderer/overlay.html`:

```html
<!DOCTYPE html>
<html>
  <head>
    <meta charset="UTF-8" />
    <title>poltergeist · jot</title>
  </head>
  <body style="margin: 0; background: transparent;">
    <div id="root"></div>
    <script type="module" src="./overlay/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 5: Register the overlay entry in the Vite config**

Edit `desktop/electron.vite.config.ts`. The renderer build section should declare multiple inputs (main app + overlay). Locate the `renderer` block; modify its `build.rollupOptions.input`:

```typescript
renderer: {
  // ... existing config (resolve.alias, etc.) ...
  build: {
    rollupOptions: {
      input: {
        index: resolve(__dirname, 'src/renderer/index.html'),
        overlay: resolve(__dirname, 'src/renderer/overlay.html'),
      },
    },
  },
},
```

(`resolve` from `'node:path'` must be imported at the top of the file if not already.)

- [ ] **Step 6: Run test to verify it passes**

Run: `cd desktop && npx vitest run src/renderer/overlay/__tests__/Overlay.test.tsx`
Expected: PASS — all 5 tests green.

Also run: `cd desktop && npx tsc --noEmit && npm run build`
Expected: build succeeds; both `index.html` and `overlay.html` produced.

- [ ] **Step 7: Manually verify**

Run the app: `cd desktop && npm run dev`. Press ⌥-J → overlay should appear; type "hello world"; ⌘-Enter → overlay closes; check `~/ghostbrain/vault/00-inbox/raw/manual/` for a new `manual-*.md` file. Within a couple seconds it should move to a context folder (or stay if confidence too low).

- [ ] **Step 8: Commit**

```bash
git add desktop/src/preload/index.ts desktop/src/shared/types.ts \
        desktop/src/renderer/overlay.html desktop/src/renderer/overlay/main.tsx \
        desktop/src/renderer/overlay/Overlay.tsx \
        desktop/src/renderer/overlay/__tests__/Overlay.test.tsx \
        desktop/electron.vite.config.ts
git commit -m "feat(desktop): jot overlay renderer + preload bridge"
```

---

## Task 10: API hooks for the Jot screen

**Files:**
- Modify: `desktop/src/renderer/lib/api/hooks.ts`
- Modify: `desktop/src/shared/api-types.ts` (add jot types)

- [ ] **Step 1: Add the shared types**

Edit `desktop/src/shared/api-types.ts`. Add these alongside the existing `Capture`/`Note` types:

```typescript
export type JotRoutingStatus = 'pending' | 'routed' | 'manual_review';

export interface JotListItem {
  id: string;
  path: string;
  title: string;
  excerpt: string;
  context: string | null;
  routingStatus: JotRoutingStatus;
  tags: string[];
  created: string;
  updated: string;
}

export interface JotsPage {
  items: JotListItem[];
  total: number;
}

export interface CreateJotRequest {
  body: string;
  capturedAt?: string;
}

export interface CreateJotResponse {
  id: string;
  path: string;
  routingStatus: JotRoutingStatus;
}
```

- [ ] **Step 2: Add the hooks**

Append to `desktop/src/renderer/lib/api/hooks.ts`:

```typescript
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { get, post, patch, del } from './client';
import type {
  CreateJotRequest, CreateJotResponse, JotsPage, JotListItem, Note,
} from '../../../shared/api-types';

const JOTS_KEY = ['jots'] as const;

export function useJots(params: { q?: string; context?: string; tag?: string } = {}) {
  return useQuery({
    queryKey: [...JOTS_KEY, params],
    queryFn: async () => {
      const search = new URLSearchParams({ source: 'manual' });
      if (params.q) search.set('q', params.q);
      if (params.context) search.set('context', params.context);
      if (params.tag) search.set('tag', params.tag);
      return get<JotsPage>(`/v1/notes?${search.toString()}`);
    },
    refetchInterval: 5000,  // pick up overlay-captured jots
  });
}

export function useJot(path: string | null) {
  return useQuery({
    queryKey: ['note-by-path', path],
    queryFn: () => get<Note>(`/v1/notes?path=${encodeURIComponent(path!)}`),
    enabled: !!path,
  });
}

export function useCreateJot() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: CreateJotRequest) =>
      post<CreateJotResponse>('/v1/notes', req),
    onSuccess: () => qc.invalidateQueries({ queryKey: JOTS_KEY }),
  });
}

export function useUpdateJot() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; body: string }) =>
      patch<{ id: string; path: string; updated: string }>(
        `/v1/notes/${encodeURIComponent(vars.id)}`,
        { body: vars.body },
      ),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: JOTS_KEY });
      qc.invalidateQueries({ queryKey: ['note-by-path'] });
    },
  });
}

export function useRouteJot() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; context: string }) =>
      post<{ id: string; path: string; context: string }>(
        `/v1/notes/${encodeURIComponent(vars.id)}/route`,
        { context: vars.context },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: JOTS_KEY }),
  });
}

export function useDeleteJot() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => del(`/v1/notes/${encodeURIComponent(id)}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: JOTS_KEY }),
  });
}
```

- [ ] **Step 3: Type-check**

Run: `cd desktop && npx tsc --noEmit`
Expected: no errors. (No unit tests for hooks themselves — they're tested via the screen component in Task 12.)

- [ ] **Step 4: Commit**

```bash
git add desktop/src/shared/api-types.ts desktop/src/renderer/lib/api/hooks.ts
git commit -m "feat(desktop): API hooks for jot list/get/create/update/route/delete"
```

---

## Task 11: JotTree component

**Files:**
- Create: `desktop/src/renderer/components/JotTree.tsx`
- Test: `desktop/src/renderer/components/__tests__/JotTree.test.tsx` (create)

- [ ] **Step 1: Write the failing test**

Create `desktop/src/renderer/components/__tests__/JotTree.test.tsx`:

```typescript
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { JotTree } from '../JotTree';
import type { JotListItem } from '../../../shared/api-types';

const items: JotListItem[] = [
  {
    id: 'manual-20260514T093015-a',
    path: '20-contexts/sanlam/notes/manual-20260514T093015-a.md',
    title: 'ascp wizard',
    excerpt: 'ascp wizard',
    context: 'sanlam',
    routingStatus: 'routed',
    tags: ['ui'],
    created: '2026-05-14T09:30:15+02:00',
    updated: '2026-05-14T09:30:15+02:00',
  },
  {
    id: 'manual-20260413T093015-b',
    path: '20-contexts/sanlam/notes/manual-20260413T093015-b.md',
    title: 'older sanlam note',
    excerpt: '',
    context: 'sanlam',
    routingStatus: 'routed',
    tags: [],
    created: '2026-04-13T09:30:15+02:00',
    updated: '2026-04-13T09:30:15+02:00',
  },
  {
    id: 'manual-20260514T100000-c',
    path: '00-inbox/raw/manual/manual-20260514T100000-c.md',
    title: 'unrouted thought',
    excerpt: '',
    context: null,
    routingStatus: 'manual_review',
    tags: [],
    created: '2026-05-14T10:00:00+02:00',
    updated: '2026-05-14T10:00:00+02:00',
  },
];

describe('JotTree', () => {
  it('groups items by context → month', () => {
    render(<JotTree items={items} selectedId={null} onSelect={() => {}} />);
    expect(screen.getByText('sanlam')).toBeInTheDocument();
    expect(screen.getByText('unrouted')).toBeInTheDocument();
    expect(screen.getByText('2026-05')).toBeInTheDocument();
    expect(screen.getByText('2026-04')).toBeInTheDocument();
  });

  it('calls onSelect with the jot id when a leaf is clicked', () => {
    const onSelect = vi.fn();
    render(<JotTree items={items} selectedId={null} onSelect={onSelect} />);
    fireEvent.click(screen.getByText('ascp wizard'));
    expect(onSelect).toHaveBeenCalledWith('manual-20260514T093015-a');
  });

  it('marks the selected leaf', () => {
    render(
      <JotTree
        items={items}
        selectedId="manual-20260514T093015-a"
        onSelect={() => {}}
      />,
    );
    const leaf = screen.getByText('ascp wizard').closest('button');
    expect(leaf?.className).toContain('bg-neon');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd desktop && npx vitest run src/renderer/components/__tests__/JotTree.test.tsx`
Expected: FAIL — `../JotTree` does not exist.

- [ ] **Step 3: Implement the component**

Create `desktop/src/renderer/components/JotTree.tsx`:

```typescript
import { useMemo, useState } from 'react';
import type { JotListItem } from '../../shared/api-types';
import { Lucide } from './Lucide';

interface Props {
  items: JotListItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

type Tree = Record<string, Record<string, JotListItem[]>>;

function groupItems(items: JotListItem[]): Tree {
  const tree: Tree = {};
  for (const item of items) {
    const ctx = item.routingStatus === 'manual_review' ? 'unrouted' :
                item.routingStatus === 'pending' ? 'inbox (pending)' :
                item.context ?? 'unrouted';
    const month = (item.created || '').slice(0, 7) || 'unknown';
    tree[ctx] ??= {};
    tree[ctx][month] ??= [];
    tree[ctx][month].push(item);
  }
  return tree;
}

export function JotTree({ items, selectedId, onSelect }: Props) {
  const tree = useMemo(() => groupItems(items), [items]);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  function toggle(key: string) {
    setCollapsed((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  return (
    <div className="flex flex-col gap-1 overflow-y-auto px-2 py-2 text-12">
      {Object.entries(tree)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([ctx, byMonth]) => {
          const ctxKey = `ctx:${ctx}`;
          const open = !collapsed[ctxKey];
          return (
            <div key={ctx}>
              <button
                type="button"
                onClick={() => toggle(ctxKey)}
                className="flex w-full items-center gap-1 px-1 py-1 text-ink-1 hover:bg-vellum"
              >
                <Lucide name={open ? 'chevron-down' : 'chevron-right'} size={12} />
                <span className="font-mono">{ctx}</span>
              </button>
              {open && Object.entries(byMonth)
                .sort(([a], [b]) => b.localeCompare(a))
                .map(([month, leaves]) => {
                  const monthKey = `m:${ctx}:${month}`;
                  const monthOpen = !collapsed[monthKey];
                  return (
                    <div key={month} className="ml-3">
                      <button
                        type="button"
                        onClick={() => toggle(monthKey)}
                        className="flex w-full items-center gap-1 px-1 py-1 text-ink-2 hover:bg-vellum"
                      >
                        <Lucide
                          name={monthOpen ? 'chevron-down' : 'chevron-right'}
                          size={11}
                        />
                        <span className="font-mono">{month}</span>
                      </button>
                      {monthOpen && (
                        <div className="ml-4 flex flex-col">
                          {leaves
                            .slice()
                            .sort((a, b) => b.created.localeCompare(a.created))
                            .map((leaf) => (
                              <button
                                key={leaf.id}
                                type="button"
                                onClick={() => onSelect(leaf.id)}
                                className={`truncate rounded-sm px-2 py-[3px] text-left ${
                                  selectedId === leaf.id
                                    ? 'bg-neon/12 text-ink-0'
                                    : 'text-ink-1 hover:bg-vellum'
                                }`}
                              >
                                {leaf.title}
                              </button>
                            ))}
                        </div>
                      )}
                    </div>
                  );
                })}
            </div>
          );
        })}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd desktop && npx vitest run src/renderer/components/__tests__/JotTree.test.tsx`
Expected: PASS — all 3 tests green.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/renderer/components/JotTree.tsx \
        desktop/src/renderer/components/__tests__/JotTree.test.tsx
git commit -m "feat(desktop): JotTree component (context → month grouping)"
```

---

## Task 12: JotEditor component (CodeMirror + autosave)

**Files:**
- Modify: `desktop/package.json` (add `@uiw/react-codemirror`, `@codemirror/lang-markdown`)
- Create: `desktop/src/renderer/components/JotEditor.tsx`
- Test: `desktop/src/renderer/components/__tests__/JotEditor.test.tsx` (create)

- [ ] **Step 1: Add the CodeMirror dependency**

Run from `desktop/`:

```bash
cd desktop && npm install @uiw/react-codemirror @codemirror/lang-markdown
```

- [ ] **Step 2: Write the failing test**

Create `desktop/src/renderer/components/__tests__/JotEditor.test.tsx`:

```typescript
import { describe, it, expect, vi } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { JotEditor } from '../JotEditor';

vi.useFakeTimers();

describe('JotEditor', () => {
  it('renders the initial body', () => {
    render(<JotEditor body="hello" onSave={() => {}} />);
    expect(screen.getByText('hello')).toBeInTheDocument();
  });

  it('debounces autosave to 1s after the last keystroke', async () => {
    const onSave = vi.fn();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<JotEditor body="initial" onSave={onSave} />);
    const editor = screen.getByRole('textbox');
    await user.type(editor, ' added');
    expect(onSave).not.toHaveBeenCalled();
    act(() => { vi.advanceTimersByTime(999); });
    expect(onSave).not.toHaveBeenCalled();
    act(() => { vi.advanceTimersByTime(2); });
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave).toHaveBeenCalledWith(expect.stringContaining('added'));
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd desktop && npx vitest run src/renderer/components/__tests__/JotEditor.test.tsx`
Expected: FAIL — `../JotEditor` doesn't exist.

- [ ] **Step 4: Implement the editor**

Create `desktop/src/renderer/components/JotEditor.tsx`:

```typescript
import { useEffect, useRef, useState } from 'react';
import CodeMirror from '@uiw/react-codemirror';
import { markdown } from '@codemirror/lang-markdown';

interface Props {
  body: string;
  onSave: (body: string) => void;
  /** Autosave debounce in ms. Defaults to 1000. */
  debounceMs?: number;
}

export function JotEditor({ body, onSave, debounceMs = 1000 }: Props) {
  const [value, setValue] = useState(body);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastSaved = useRef(body);

  // Reset state when the editor switches to a different jot.
  useEffect(() => {
    setValue(body);
    lastSaved.current = body;
  }, [body]);

  function scheduleSave(next: string) {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      if (next !== lastSaved.current) {
        lastSaved.current = next;
        onSave(next);
      }
    }, debounceMs);
  }

  return (
    <CodeMirror
      value={value}
      extensions={[markdown()]}
      basicSetup={{ lineNumbers: false, foldGutter: false }}
      onChange={(next) => {
        setValue(next);
        scheduleSave(next);
      }}
      theme="dark"
      className="h-full text-13"
    />
  );
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd desktop && npx vitest run src/renderer/components/__tests__/JotEditor.test.tsx`
Expected: PASS — both tests green.

- [ ] **Step 6: Commit**

```bash
git add desktop/package.json desktop/package-lock.json \
        desktop/src/renderer/components/JotEditor.tsx \
        desktop/src/renderer/components/__tests__/JotEditor.test.tsx
git commit -m "feat(desktop): JotEditor — CodeMirror markdown with 1s autosave"
```

---

## Task 13: Jot screen + sidebar entry

**Files:**
- Create: `desktop/src/renderer/screens/jots.tsx`
- Modify: `desktop/src/renderer/stores/navigation.ts` (add `'jots'`)
- Modify: `desktop/src/renderer/components/Sidebar.tsx` (add nav row)
- Modify: `desktop/src/renderer/App.tsx` (route the new screen)
- Test: `desktop/src/renderer/screens/__tests__/jots.test.tsx` (create)

- [ ] **Step 1: Find the routing point in App.tsx**

Run: `grep -n "switch\|case\|ScreenId\|capture" desktop/src/renderer/App.tsx | head -20`
Note where existing screens are rendered.

- [ ] **Step 2: Add `'jots'` to ScreenId**

Edit `desktop/src/renderer/stores/navigation.ts`:

```typescript
export type ScreenId =
  | 'today'
  | 'connectors'
  | 'meetings'
  | 'capture'
  | 'vault'
  | 'daily'
  | 'setup'
  | 'settings'
  | 'jots';
```

- [ ] **Step 3: Add the sidebar entry**

Edit `desktop/src/renderer/components/Sidebar.tsx`. Add to `NAV_ITEMS` after `'capture'`:

```typescript
{ id: 'jots', icon: 'pencil', label: 'jots' },
```

- [ ] **Step 4: Write the failing test**

Create `desktop/src/renderer/screens/__tests__/jots.test.tsx`:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { JotsScreen } from '../jots';
import type { JotsPage, Note } from '../../../shared/api-types';

const apiRequest = vi.fn();

beforeEach(() => {
  apiRequest.mockReset();
  // @ts-expect-error window.gb injected by preload normally
  window.gb = { api: { request: apiRequest } };
});

function withQuery(children: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

const page: JotsPage = {
  items: [
    {
      id: 'manual-20260514T093015-a',
      path: '20-contexts/sanlam/notes/manual-20260514T093015-a.md',
      title: 'first jot',
      excerpt: 'body',
      context: 'sanlam',
      routingStatus: 'routed',
      tags: [],
      created: '2026-05-14T09:30:15+02:00',
      updated: '2026-05-14T09:30:15+02:00',
    },
  ],
  total: 1,
};

const detail: Note = {
  path: 'p',
  title: 'first jot',
  body: 'first jot\n\nfull body here',
  frontmatter: {},
};

describe('JotsScreen', () => {
  it('renders the tree and loads the first jot on select', async () => {
    apiRequest.mockImplementation(async (_m, path: string) => {
      if (path.includes('source=manual')) return { ok: true, status: 200, data: page };
      return { ok: true, status: 200, data: detail };
    });

    render(withQuery(<JotsScreen />));
    const leaf = await screen.findByText('first jot');
    fireEvent.click(leaf);
    await waitFor(() => expect(screen.getByText(/full body here/)).toBeInTheDocument());
  });
});
```

- [ ] **Step 5: Run test to verify it fails**

Run: `cd desktop && npx vitest run src/renderer/screens/__tests__/jots.test.tsx`
Expected: FAIL — `../jots` does not exist.

- [ ] **Step 6: Implement the screen**

Create `desktop/src/renderer/screens/jots.tsx`:

```typescript
import { useEffect, useMemo, useState } from 'react';
import { TopBar } from '../components/TopBar';
import { Btn } from '../components/Btn';
import { Lucide } from '../components/Lucide';
import { Pill } from '../components/Pill';
import { JotTree } from '../components/JotTree';
import { JotEditor } from '../components/JotEditor';
import {
  useCreateJot,
  useDeleteJot,
  useJot,
  useJots,
  useRouteJot,
  useUpdateJot,
} from '../lib/api/hooks';
import { toast } from '../stores/toast';

const KNOWN_CONTEXTS = ['sanlam', 'codeship', 'reducedrecipes', 'personal'];

export function JotsScreen() {
  const [q, setQ] = useState('');
  const list = useJots({ q: q || undefined });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selectedItem = useMemo(
    () => list.data?.items.find((i) => i.id === selectedId) ?? null,
    [list.data, selectedId],
  );
  const detail = useJot(selectedItem?.path ?? null);

  const createJot = useCreateJot();
  const updateJot = useUpdateJot();
  const routeJot = useRouteJot();
  const deleteJot = useDeleteJot();

  // Auto-select the newest jot when the list first loads.
  useEffect(() => {
    if (selectedId === null && list.data?.items.length) {
      setSelectedId(list.data.items[0]!.id);
    }
  }, [list.data, selectedId]);

  function handleNew() {
    createJot.mutate(
      { body: 'new jot\n\n' },
      {
        onSuccess: (res) => {
          setSelectedId(res.id);
          toast.info('jot created');
        },
        onError: (err) => toast.error(`could not create jot: ${err.message}`),
      },
    );
  }

  function handleSaveBody(next: string) {
    if (!selectedId) return;
    updateJot.mutate({ id: selectedId, body: next });
  }

  function handleReroute(ctx: string) {
    if (!selectedId) return;
    routeJot.mutate({ id: selectedId, context: ctx }, {
      onSuccess: () => toast.info(`re-routed to ${ctx}`),
    });
  }

  function handleDelete() {
    if (!selectedId) return;
    deleteJot.mutate(selectedId, {
      onSuccess: () => { setSelectedId(null); toast.info('jot deleted'); },
    });
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden bg-paper">
      <TopBar
        title="jots"
        subtitle={list.data ? `${list.data.total} total` : '…'}
        right={
          <div className="flex gap-2">
            <Btn variant="primary" size="sm"
                 icon={<Lucide name="plus" size={13} />} onClick={handleNew}>
              new
            </Btn>
          </div>
        }
      />
      <div className="flex flex-shrink-0 border-b border-hairline px-4 py-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="search jots…"
          className="w-full bg-transparent text-12 text-ink-0 outline-none"
        />
      </div>
      <div className="flex flex-1 overflow-hidden">
        <aside className="w-[260px] flex-shrink-0 overflow-y-auto border-r border-hairline">
          <JotTree
            items={list.data?.items ?? []}
            selectedId={selectedId}
            onSelect={setSelectedId}
          />
        </aside>
        <main className="flex flex-1 flex-col">
          {detail.data ? (
            <>
              <div className="flex-1 overflow-auto">
                <JotEditor body={detail.data.body} onSave={handleSaveBody} />
              </div>
              <footer className="flex items-center gap-2 border-t border-hairline px-4 py-2 text-11 text-ink-2">
                {selectedItem?.context && <Pill>{selectedItem.context}</Pill>}
                <Pill>{selectedItem?.routingStatus}</Pill>
                <div className="ml-auto flex gap-2">
                  <select
                    onChange={(e) => { if (e.target.value) handleReroute(e.target.value); }}
                    defaultValue=""
                    className="bg-transparent text-11"
                  >
                    <option value="" disabled>re-route…</option>
                    {KNOWN_CONTEXTS.map((c) => (
                      <option key={c} value={c}>{c}</option>
                    ))}
                  </select>
                  <Btn variant="ghost" size="sm" onClick={handleDelete}>
                    delete
                  </Btn>
                </div>
              </footer>
            </>
          ) : (
            <div className="flex flex-1 items-center justify-center text-13 text-ink-3">
              {list.data?.items.length === 0
                ? 'no jots yet — press ⌥-J to create one'
                : 'select a jot'}
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
```

- [ ] **Step 7: Wire into App.tsx**

Edit `desktop/src/renderer/App.tsx`. Wherever the active screen is rendered (a switch or conditional on `useNavigation().active`), add the new case:

```typescript
import { JotsScreen } from './screens/jots';

// ... in the screen renderer:
{active === 'jots' && <JotsScreen />}
// or, in a switch: case 'jots': return <JotsScreen />;
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd desktop && npx vitest run src/renderer/screens/__tests__/jots.test.tsx`
Expected: PASS.

Also run: `cd desktop && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 9: Manually verify**

`cd desktop && npm run dev` → click "jots" in the sidebar → empty state. Press ⌥-J → type "test sanlam ascp" → ⌘-Enter. Within a few seconds the jot should appear in the tree under either `sanlam` or `unrouted`. Click it → editor shows the body. Edit → save indicator (Network) fires after 1s. Re-route → file moves. Delete → leaf disappears.

- [ ] **Step 10: Commit**

```bash
git add desktop/src/renderer/screens/jots.tsx \
        desktop/src/renderer/screens/__tests__/jots.test.tsx \
        desktop/src/renderer/stores/navigation.ts \
        desktop/src/renderer/components/Sidebar.tsx \
        desktop/src/renderer/App.tsx
git commit -m "feat(desktop): jots screen — tree + editor + re-route + delete"
```

---

## Task 14: End-to-end manual verification

This task has no code — it's an explicit one-time E2E to confirm the full pipeline, before marking the feature done. Run after Task 13.

- [ ] **Step 1: Boot the full stack**

```bash
cd desktop && npm run dev
```

- [ ] **Step 2: Capture via overlay**

Press ⌥-J → a 480×260 frameless overlay appears. Type: `testing poltergeist jots — ascp wizard cognito session #idea`. Press ⌘-Enter. Overlay closes immediately.

Check: `ls -lt ~/ghostbrain/vault/00-inbox/raw/manual/ | head -3`
Within ~3s, run: `ls -lt ~/ghostbrain/vault/20-contexts/*/notes/ 2>/dev/null | grep manual- | head -3`
Expected: the new file appears under one of the routed context folders (sanlam most likely given the body).

- [ ] **Step 3: Verify the frontmatter**

```bash
head -20 ~/ghostbrain/vault/20-contexts/sanlam/notes/manual-*.md | tail -20
```
Expected: `source: manual`, `routingStatus: routed`, `routingMethod: llm`, `tags: [idea]`, a non-empty `routingReasoning`.

- [ ] **Step 4: Verify the audit log**

```bash
tail -5 ~/ghostbrain/audit/$(date +%Y-%m-%d).jsonl
```
Expected: a `manual_jot_routed` line with the same id.

- [ ] **Step 5: Verify it appears in the Jot screen**

Switch to the desktop app, click "jots" in the sidebar. The new entry should be in the tree under its routed context within ~5s (poll interval). Click → editor shows the body.

- [ ] **Step 6: Verify the semantic index picks it up**

The scheduler runs semantic refresh every 15 minutes. To verify without waiting:

```bash
python -m ghostbrain.semantic.refresh
```

Then ask the brain a question that should retrieve the jot:
```bash
curl -s -X POST http://127.0.0.1:8787/v1/answer -H "Content-Type: application/json" \
  -d '{"question": "what did I think about the ascp wizard cognito session?"}' | jq .
```
Expected: the jot path appears in the answer's citations.

- [ ] **Step 7: Document the E2E pass**

Append a one-line note to the spec doc under "Implementation status":
```
- 2026-05-15: E2E pass — overlay → routed → indexed → answer cited.
```

```bash
git add docs/superpowers/specs/2026-05-14-poltergeist-jots-design.md
git commit -m "docs(spec): record Poltergeist Jots E2E pass"
```

---

## Self-Review Notes

After writing this plan, I checked it against the spec:

**Coverage:** All sections of the spec map to tasks — capture flow (Tasks 4 + 8 + 9), data model (Task 1), API surface (Tasks 4-6), routing wiring (Task 4), tree+editor (Tasks 10-13), file-level changes (touched across all tasks), testing strategy (per-task TDD + Task 14 manual E2E). Two minor deviations from the spec, both intentional:
- The spec mentions an "open in Obsidian ↗" button in the editor footer. The screen task implements re-route + delete; the Obsidian handoff is omitted because it adds risk (depends on the user's Obsidian URI scheme setup) without serving the core indexing loop. Easy to add later.
- The spec mentions the "+ new" button could create an unsaved buffer. The implementation in Task 13 short-circuits this — clicking new creates a real jot with placeholder body "new jot\n\n" and routes it immediately. Simpler, fewer states. The user can edit the body afterwards.

**Type consistency:** `JotListItem`, `JotsPage`, `CreateJotResponse`, `RoutingStatus` defined in shared types (Task 10) match the pydantic models in Task 1 (`NoteListItem`, `NotesPage`, etc.). API hook signatures in Task 10 match endpoint request/response shapes in Tasks 4-6.

**No placeholders:** every step has runnable code or an exact command.
