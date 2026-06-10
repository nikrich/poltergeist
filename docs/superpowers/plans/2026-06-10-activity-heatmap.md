# Activity Heatmap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A GitHub-style contribution heatmap of Poltergeist activity per day — a new `GET /v1/activity/heatmap` endpoint that aggregates the audit jsonl files server-side, a `?date=` drill-down on the existing `GET /v1/activity`, an `ActivityHeatmap` renderer component with 5 intensity buckets, a compact 12-week tile on the today dashboard, and a dedicated activity sidebar screen with a full-year heatmap, per-day log, and source filter chips that link into `NoteView`.

**Architecture:** The Python sidecar already reads `vault/90-meta/audit/YYYY-MM-DD.jsonl` in `ghostbrain/api/repo/activity.py` (one JSON event per line; the date is the filename). This plan refactors that module to share one line-parsing helper across three readers: the existing `list_activity(window_minutes)`, a new `list_activity_for_date(day)`, and a new `build_heatmap(days)` aggregator that walks the audit dir once and returns `{days, total, maxCount}`. The renderer never receives raw event streams for the year view. Cross-screen day preselection (today tile → activity screen) uses a tiny zustand store (`useSelectedDay`), the same pattern as the existing `selected-event.ts` used by `meetings:openPrep`.

**Tech Stack:** Python 3.11 + FastAPI (sidecar), pytest (backend tests, fixtures from `ghostbrain/api/tests/conftest.py`), Electron + React + TypeScript (desktop), Zustand (state), React Query (data), Vitest + React Testing Library (renderer tests).

**Spec:** `docs/superpowers/specs/2026-06-10-activity-heatmap-design.md`

**Verified baselines (2026-06-10, this worktree):**

- Backend: `/Users/jannik/development/nikrich/ghost-brain/.venv/bin/python -m pytest ghostbrain/api/tests/ -q` → **42 passed** (run from the worktree root).
- Desktop: `cd desktop && npx vitest run` → **18 passed** (5 files). `cd desktop && npm run typecheck` → clean.
- Real audit event shapes (from `~/ghostbrain/vault/90-meta/audit/2026-06-10.jsonl`): `{"ts": "...", "event_type": "connector_skipped", "event_id": "joplin", "reason": "not_configured"}` — many events have **no `source` field** and `event_id` values **repeat within a day** (e.g. `joplin` on every scheduler cycle). Tests never depend on real files; they write fixtures into the tmp vault.

**Two deliberate decisions (read before implementing):**

1. The repo's existing `_source_for` falls back to `"ghostbrain"` for sourceless events; the spec buckets those as `"system"`. The heatmap's `bySource` and the day-log rows must agree, otherwise the activity screen's source chips can't filter the rows. This plan changes the shared fallback to `"system"` everywhere. No existing test asserts `"ghostbrain"`, and the today-feed icon `assets/connectors/${source}.svg` 404s silently for the fallback bucket either way (there is no `ghostbrain.svg` and no `system.svg`).
2. `list_activity_for_date` always synthesizes row ids (`audit-{date}-{lineno}`) instead of reusing `event_id`, because `event_id` repeats within a day and the renderer uses the id as a React key. `list_activity` keeps its existing id behavior untouched.

---

## Task 1: Backend repo — heatmap aggregation + per-day listing

**Files:**
- Modify: `ghostbrain/api/repo/activity.py`
- Test: `ghostbrain/api/tests/test_activity_heatmap_repo.py` (create)

- [ ] **Step 1: Write the failing test**

Create `ghostbrain/api/tests/test_activity_heatmap_repo.py`:

```python
"""Heatmap aggregation + per-day listing in the activity repo.

All tests write fixture jsonl files into the tmp vault's audit dir
(tmp_vault fixture from conftest creates 90-meta/audit/ and sets VAULT_PATH).
"""
import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from ghostbrain.api.repo.activity import build_heatmap, list_activity_for_date


def _write_lines(vault: Path, date_iso: str, lines: list[str]) -> None:
    audit = vault / "90-meta" / "audit"
    (audit / f"{date_iso}.jsonl").write_text("\n".join(lines) + "\n")


def _event(date_iso: str, **fields) -> str:
    record = {"ts": f"{date_iso}T10:00:00+00:00", "event_type": "event_processed"}
    record.update(fields)
    return json.dumps(record)


def test_heatmap_counts_multiple_days_with_by_source(tmp_vault: Path):
    today = datetime.now(timezone.utc).date()
    d1 = (today - timedelta(days=1)).isoformat()
    d2 = (today - timedelta(days=3)).isoformat()
    _write_lines(tmp_vault, d1, [
        _event(d1, source="gmail"),
        _event(d1, source="gmail"),
        _event(d1, source="slack"),
    ])
    _write_lines(tmp_vault, d2, [_event(d2, source="gmail")])
    result = build_heatmap(days=365)
    assert result["total"] == 4
    assert result["maxCount"] == 3
    by_date = {d["date"]: d for d in result["days"]}
    assert by_date[d1]["count"] == 3
    assert by_date[d1]["bySource"] == {"gmail": 2, "slack": 1}
    assert by_date[d2]["count"] == 1
    # days come back ascending by date (sorted glob over the filenames)
    assert [d["date"] for d in result["days"]] == [d2, d1]


def test_heatmap_buckets_digest_and_sourceless_events(tmp_vault: Path):
    today = datetime.now(timezone.utc).date().isoformat()
    _write_lines(tmp_vault, today, [
        _event(today, event_type="digest_generated"),
        _event(today, event_type="connector_skipped", event_id="joplin"),
        _event(today, source="jira"),
    ])
    result = build_heatmap(days=7)
    assert len(result["days"]) == 1
    assert result["days"][0]["bySource"] == {"digest": 1, "system": 1, "jira": 1}


def test_heatmap_skips_malformed_lines_with_warning(tmp_vault: Path, caplog):
    today = datetime.now(timezone.utc).date().isoformat()
    _write_lines(tmp_vault, today, [
        _event(today, source="gmail"),
        "{ this is not json",
        _event(today, source="gmail"),
    ])
    with caplog.at_level(logging.WARNING, logger="ghostbrain.api.repo.activity"):
        result = build_heatmap(days=7)
    assert result["days"][0]["count"] == 2
    assert any("malformed audit line" in r.getMessage() for r in caplog.records)


def test_heatmap_excludes_files_outside_range(tmp_vault: Path):
    today = datetime.now(timezone.utc).date()
    inside = (today - timedelta(days=6)).isoformat()
    outside = (today - timedelta(days=7)).isoformat()
    _write_lines(tmp_vault, inside, [_event(inside, source="gmail")])
    _write_lines(tmp_vault, outside, [_event(outside, source="gmail")])
    # days=7 → window is [today-6 .. today]
    result = build_heatmap(days=7)
    assert [d["date"] for d in result["days"]] == [inside]


def test_heatmap_empty_audit_dir(tmp_vault: Path):
    assert build_heatmap(days=365) == {"days": [], "total": 0, "maxCount": 0}


def test_heatmap_omits_day_whose_file_has_no_valid_events(tmp_vault: Path):
    today = datetime.now(timezone.utc).date().isoformat()
    _write_lines(tmp_vault, today, ["not json at all"])
    result = build_heatmap(days=7)
    assert result["days"] == []
    assert result["maxCount"] == 0


def test_heatmap_ignores_non_date_filenames(tmp_vault: Path):
    audit = tmp_vault / "90-meta" / "audit"
    (audit / "README.jsonl").write_text("{}\n")
    assert build_heatmap(days=7)["days"] == []


def test_list_for_date_returns_all_rows_newest_first(tmp_vault: Path):
    _write_lines(tmp_vault, "2026-06-04", [
        json.dumps({
            "ts": "2026-06-04T08:00:00+00:00",
            "event_type": "event_processed",
            "event_id": "evt-a",
            "source": "gmail",
            "inbox_path": "/v/00-inbox/raw/gmail/20260604T080000-morning-mail.md",
        }),
        json.dumps({
            "ts": "2026-06-04T17:00:00+00:00",
            "event_type": "digest_generated",
            "event_id": "2026-06-04",
            "path": "/v/10-daily/2026-06-04.md",
        }),
    ])
    rows = list_activity_for_date(date(2026, 6, 4))
    # ids are synthesized per line (event_id repeats within a day in real
    # audit logs, and the renderer keys rows by id) — newest first.
    assert [r["id"] for r in rows] == ["audit-2026-06-04-1", "audit-2026-06-04-0"]
    assert rows[0]["source"] == "digest"
    assert rows[0]["verb"] == "wrote digest"
    assert rows[1]["source"] == "gmail"
    assert rows[1]["subject"] == "morning-mail"
    assert rows[1]["at"] == "2026-06-04T08:00:00+00:00"


def test_list_for_date_missing_file_returns_empty(tmp_vault: Path):
    assert list_activity_for_date(date(1999, 1, 1)) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run (from the worktree root):
```bash
/Users/jannik/development/nikrich/ghost-brain/.venv/bin/python -m pytest ghostbrain/api/tests/test_activity_heatmap_repo.py -v
```
Expected: FAIL — `ImportError: cannot import name 'build_heatmap'`.

- [ ] **Step 3: Implement — replace `ghostbrain/api/repo/activity.py`**

Replace the whole file with:

```python
"""Recent activity, per-day listing, and heatmap aggregation from the audit log."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from ghostbrain.paths import audit_dir

log = logging.getLogger("ghostbrain.api.repo.activity")


def _relative(when: datetime) -> str:
    delta = datetime.now(timezone.utc) - when
    secs = int(delta.total_seconds())
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86_400:
        return f"{secs // 3600}h"
    return f"{secs // 86_400}d"


def _verb_for(event_type: str) -> str:
    mapping = {
        "digest_generated": "wrote digest",
        "event_processed": "processed",
        "event_routed": "routed",
        "artifact_extracted": "extracted",
    }
    if event_type in mapping:
        return mapping[event_type]
    return event_type.replace("_", " ")


def _strip_inbox_timestamp_prefix(name: str) -> str:
    """Strip leading 'YYYYMMDDTHHMMSS-' prefix from inbox basenames."""
    parts = name.split("-", 1)
    if len(parts) < 2:
        return name
    head = parts[0]
    # The inbox convention is e.g. '20260507T144500'. Check it looks like
    # 8-digit-date + 'T' + time.
    if "T" in head and head[:8].isdigit():
        return parts[1]
    return name


def _subject_for(event: dict) -> str:
    inbox_path = event.get("inbox_path")
    if isinstance(inbox_path, str) and inbox_path:
        return _strip_inbox_timestamp_prefix(Path(inbox_path).stem)
    path = event.get("path")
    if isinstance(path, str) and path:
        return Path(path).stem
    event_id = event.get("event_id")
    if event_id:
        return str(event_id)
    return ""


def _note_path_for(event: dict) -> str | None:
    """Vault-relative path of the note this audit row is about, if any.

    The audit log stores absolute paths or vault-relative paths depending on
    the producer. Strip a leading vault prefix when present so the UI can
    feed the result straight into /v1/notes?path=...
    """
    from ghostbrain.paths import vault_path

    raw = event.get("inbox_path") or event.get("path")
    if not isinstance(raw, str) or not raw:
        return None
    if raw.startswith("/"):
        try:
            return str(Path(raw).resolve().relative_to(vault_path().resolve()))
        except ValueError:
            return None
    return raw


def _source_for(event: dict) -> str:
    """Bucket an audit event by source.

    `digest_generated` → "digest"; an explicit `source` field wins; everything
    else (scheduler/connector internals with no source) buckets as "system".
    Shared by the activity rows AND the heatmap aggregation so the activity
    screen's source chips line up with the day-log rows.
    """
    et = event.get("event_type", "")
    if et == "digest_generated":
        return "digest"
    src = event.get("source")
    return src if isinstance(src, str) and src else "system"


def _iter_day_events(path: Path) -> Iterator[tuple[int, dict]]:
    """Yield (lineno, event) for each well-formed line of one audit file.

    Malformed lines are skipped with a warning — a corrupt line must never
    500 an endpoint.
    """
    for lineno, line in enumerate(path.read_text().splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            log.warning("skipping malformed audit line %s:%d", path.name, lineno)
            continue
        if not isinstance(event, dict):
            log.warning("skipping non-object audit line %s:%d", path.name, lineno)
            continue
        yield lineno, event


def _row_for(event: dict, *, row_id: str) -> dict | None:
    """Build one ActivityRow dict, or None when the ts is unusable.

    The returned dict carries a private "_when" datetime for callers that
    need to filter by time; callers must pop it before returning rows.
    """
    ts_str = event.get("ts", "")
    try:
        when = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return {
        "id": row_id,
        "source": _source_for(event),
        "verb": _verb_for(event.get("event_type", "")),
        "subject": _subject_for(event),
        "atRelative": _relative(when),
        "at": ts_str,
        "path": _note_path_for(event),
        "_when": when,
    }


def list_activity(window_minutes: int = 240) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    audit = audit_dir()
    if not audit.exists():
        return []
    items: list[dict] = []
    today = datetime.now(timezone.utc).date()
    for offset in range(2):  # today + yesterday (covers any reasonable windowMinutes)
        day = today - timedelta(days=offset)
        path = audit / f"{day.isoformat()}.jsonl"
        if not path.exists():
            continue
        for lineno, event in _iter_day_events(path):
            event_id = event.get("event_id")
            row_id = str(event_id) if event_id else f"audit-{day.isoformat()}-{lineno}"
            row = _row_for(event, row_id=row_id)
            if row is None:
                continue
            when = row.pop("_when")
            if when < cutoff:
                continue
            items.append(row)
    items.sort(key=lambda r: r["at"], reverse=True)
    return items


def list_activity_for_date(day: date) -> list[dict]:
    """All audit rows for one calendar day, newest first.

    Row ids are always synthesized from the line number: real audit logs
    repeat event_id within a day (e.g. connector_skipped/joplin on every
    scheduler cycle) and the renderer keys rows by id.
    """
    path = audit_dir() / f"{day.isoformat()}.jsonl"
    if not path.exists():
        return []
    items: list[dict] = []
    for lineno, event in _iter_day_events(path):
        row = _row_for(event, row_id=f"audit-{day.isoformat()}-{lineno}")
        if row is None:
            continue
        row.pop("_when")
        items.append(row)
    items.sort(key=lambda r: r["at"], reverse=True)
    return items


def build_heatmap(days: int = 365) -> dict:
    """Aggregate per-day event counts + per-source breakdown.

    Walks the audit directory once. Days with no audit file — or whose file
    yields zero well-formed events — are omitted; the renderer fills
    zero-level squares. maxCount lets the renderer bucket intensities
    without a second pass.
    """
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days - 1)
    audit = audit_dir()
    if not audit.exists():
        return {"days": [], "total": 0, "maxCount": 0}
    out: list[dict] = []
    total = 0
    max_count = 0
    for path in sorted(audit.glob("*.jsonl")):
        try:
            day = date.fromisoformat(path.stem)
        except ValueError:
            log.warning("ignoring non-date audit file %s", path.name)
            continue
        if day < start or day > today:
            continue
        count = 0
        by_source: dict[str, int] = {}
        for _lineno, event in _iter_day_events(path):
            count += 1
            src = _source_for(event)
            by_source[src] = by_source.get(src, 0) + 1
        if count == 0:
            continue
        out.append({"date": day.isoformat(), "count": count, "bySource": by_source})
        total += count
        max_count = max(max_count, count)
    return {"days": out, "total": total, "maxCount": max_count}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
/Users/jannik/development/nikrich/ghost-brain/.venv/bin/python -m pytest ghostbrain/api/tests/test_activity_heatmap_repo.py -v
```
Expected: PASS — 9 tests green.

- [ ] **Step 5: Verify no regression in the existing suite**

```bash
/Users/jannik/development/nikrich/ghost-brain/.venv/bin/python -m pytest ghostbrain/api/tests/ -q
```
Expected: **51 passed** (42 baseline + 9 new). The 4 existing tests in `test_activity.py` exercise the refactored `list_activity` and must stay green.

- [ ] **Step 6: Commit**

```bash
git add ghostbrain/api/repo/activity.py ghostbrain/api/tests/test_activity_heatmap_repo.py
git commit -m "feat(api): heatmap aggregation + per-day listing in activity repo"
```

---

## Task 2: Backend routes — GET /v1/activity/heatmap + date param on /v1/activity

**Files:**
- Modify: `ghostbrain/api/models/activity.py`
- Modify: `ghostbrain/api/routes/activity.py`
- Test: `ghostbrain/api/tests/test_activity_heatmap.py` (create)

- [ ] **Step 1: Write the failing test**

Create `ghostbrain/api/tests/test_activity_heatmap.py`:

```python
"""GET /v1/activity/heatmap and the new ?date= param on GET /v1/activity."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient


def _write_audit_event(vault: Path, date_iso: str, event: dict) -> None:
    audit = vault / "90-meta" / "audit"
    path = audit / f"{date_iso}.jsonl"
    with path.open("a") as f:
        f.write(json.dumps(event) + "\n")


def test_heatmap_empty(client: TestClient, auth_headers: dict[str, str]):
    res = client.get("/v1/activity/heatmap", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == {"days": [], "total": 0, "maxCount": 0}


def test_heatmap_aggregates_with_by_source(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    today = datetime.now(timezone.utc).date().isoformat()
    _write_audit_event(tmp_vault, today, {
        "ts": f"{today}T10:00:00+00:00",
        "event_type": "event_processed",
        "event_id": "evt1",
        "source": "gmail",
    })
    _write_audit_event(tmp_vault, today, {
        "ts": f"{today}T11:00:00+00:00",
        "event_type": "connector_skipped",
        "event_id": "joplin",
    })
    res = client.get("/v1/activity/heatmap?days=30", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 2
    assert data["maxCount"] == 2
    assert data["days"] == [
        {"date": today, "count": 2, "bySource": {"gmail": 1, "system": 1}}
    ]


def test_heatmap_days_bounds(client: TestClient, auth_headers: dict[str, str]):
    assert client.get("/v1/activity/heatmap?days=0", headers=auth_headers).status_code == 422
    assert client.get("/v1/activity/heatmap?days=731", headers=auth_headers).status_code == 422
    assert client.get("/v1/activity/heatmap?days=1", headers=auth_headers).status_code == 200
    assert client.get("/v1/activity/heatmap?days=730", headers=auth_headers).status_code == 200


def test_activity_date_param_returns_whole_day(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    day = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
    _write_audit_event(tmp_vault, day, {
        "ts": f"{day}T09:00:00+00:00",
        "event_type": "event_processed",
        "event_id": "evt1",
        "source": "gmail",
    })
    res = client.get(f"/v1/activity?date={day}", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["id"] == f"audit-{day}-0"
    assert data[0]["source"] == "gmail"
    assert data[0]["verb"] == "processed"


def test_activity_date_wins_over_window_minutes(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    day = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
    _write_audit_event(tmp_vault, day, {
        "ts": f"{day}T09:00:00+00:00",
        "event_type": "event_processed",
        "event_id": "evt1",
        "source": "gmail",
    })
    # windowMinutes=1 alone would exclude a 30-day-old event; date wins.
    res = client.get(f"/v1/activity?date={day}&windowMinutes=1", headers=auth_headers)
    assert res.status_code == 200
    assert len(res.json()) == 1


def test_activity_invalid_date_422(client: TestClient, auth_headers: dict[str, str]):
    assert client.get("/v1/activity?date=not-a-date", headers=auth_headers).status_code == 422
    assert client.get("/v1/activity?date=2026-13-45", headers=auth_headers).status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

```bash
/Users/jannik/development/nikrich/ghost-brain/.venv/bin/python -m pytest ghostbrain/api/tests/test_activity_heatmap.py -v
```
Expected: FAIL — `/v1/activity/heatmap` returns 404 (route missing); the `?date=` tests return the windowMinutes behavior (empty list) instead of the day's rows.

- [ ] **Step 3: Add the response models**

Replace `ghostbrain/api/models/activity.py`:

```python
"""Activity row + heatmap schemas."""
from pydantic import BaseModel, ConfigDict


class ActivityRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    source: str
    verb: str
    subject: str
    atRelative: str
    at: str
    path: str | None = None


class HeatmapDay(BaseModel):
    date: str  # YYYY-MM-DD
    count: int
    bySource: dict[str, int]


class HeatmapResponse(BaseModel):
    days: list[HeatmapDay]
    total: int
    maxCount: int
```

- [ ] **Step 4: Wire the routes**

Replace `ghostbrain/api/routes/activity.py`:

```python
"""GET /v1/activity + GET /v1/activity/heatmap."""
import datetime as dt

from fastapi import APIRouter, Query

from ghostbrain.api.models.activity import ActivityRow, HeatmapResponse
from ghostbrain.api.repo.activity import (
    build_heatmap,
    list_activity,
    list_activity_for_date,
)

router = APIRouter(prefix="/v1/activity", tags=["activity"])


@router.get("/heatmap", response_model=HeatmapResponse)
def activity_heatmap(days: int = Query(365, ge=1, le=730)) -> dict:
    return build_heatmap(days=days)


@router.get("", response_model=list[ActivityRow])
def activity(
    windowMinutes: int = Query(240, ge=1, le=10_080),
    date: dt.date | None = Query(None),
) -> list[dict]:
    # `date` wins over windowMinutes when both are supplied (spec §2).
    # FastAPI's dt.date coercion gives the 422 for malformed dates for free.
    if date is not None:
        return list_activity_for_date(date)
    return list_activity(window_minutes=windowMinutes)
```

(No change to `ghostbrain/api/main.py` — the router is already included.)

- [ ] **Step 5: Run test to verify it passes**

```bash
/Users/jannik/development/nikrich/ghost-brain/.venv/bin/python -m pytest ghostbrain/api/tests/test_activity_heatmap.py ghostbrain/api/tests/test_activity.py -v
```
Expected: PASS — 6 new + 4 existing tests green.

Then the full suite:
```bash
/Users/jannik/development/nikrich/ghost-brain/.venv/bin/python -m pytest ghostbrain/api/tests/ -q
```
Expected: **57 passed**.

- [ ] **Step 6: Commit**

```bash
git add ghostbrain/api/models/activity.py ghostbrain/api/routes/activity.py \
        ghostbrain/api/tests/test_activity_heatmap.py
git commit -m "feat(api): GET /v1/activity/heatmap + date param on /v1/activity"
```

---

## Task 3: Shared TS types + React Query hooks

**Files:**
- Modify: `desktop/src/shared/api-types.ts`
- Modify: `desktop/src/renderer/lib/api/hooks.ts`
- Test: `desktop/src/renderer/__tests__/activity-hooks.test.tsx` (create)

- [ ] **Step 1: Write the failing test**

Create `desktop/src/renderer/__tests__/activity-hooks.test.tsx`:

```tsx
import { renderHook, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

import { useActivityHeatmap, useActivityForDate } from '../lib/api/hooks';
import type { HeatmapResponse } from '../../shared/api-types';

const apiRequest = vi.fn();

beforeEach(() => {
  apiRequest.mockReset();
  window.gb.api.request = apiRequest as typeof window.gb.api.request;
});

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

const payload: HeatmapResponse = {
  days: [{ date: '2026-06-04', count: 23, bySource: { gmail: 9, slack: 5, system: 9 } }],
  total: 23,
  maxCount: 23,
};

describe('useActivityHeatmap', () => {
  it('fetches /v1/activity/heatmap with the days param', async () => {
    apiRequest.mockResolvedValueOnce({ ok: true, status: 200, data: payload });
    const { result } = renderHook(() => useActivityHeatmap(84), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiRequest).toHaveBeenCalledWith('GET', '/v1/activity/heatmap?days=84');
    expect(result.current.data).toEqual(payload);
  });
});

describe('useActivityForDate', () => {
  it('fetches the day log for a date', async () => {
    apiRequest.mockResolvedValueOnce({ ok: true, status: 200, data: [] });
    const { result } = renderHook(() => useActivityForDate('2026-06-04'), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiRequest).toHaveBeenCalledWith('GET', '/v1/activity?date=2026-06-04');
  });

  it('does not fetch when date is null', () => {
    renderHook(() => useActivityForDate(null), { wrapper: makeWrapper() });
    expect(apiRequest).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd desktop && npx vitest run src/renderer/__tests__/activity-hooks.test.tsx
```
Expected: FAIL — `useActivityHeatmap` / `useActivityForDate` are not exported from `../lib/api/hooks`.

- [ ] **Step 3: Add the shared types**

Edit `desktop/src/shared/api-types.ts`. Directly after the existing `ActivityRow` interface (which ends with `path: string | null;` and a closing brace), add:

```typescript
export interface HeatmapDay {
  date: string; // YYYY-MM-DD
  count: number;
  bySource: Record<string, number>;
}

export interface HeatmapResponse {
  days: HeatmapDay[];
  total: number;
  maxCount: number;
}
```

- [ ] **Step 4: Add the hooks**

Edit `desktop/src/renderer/lib/api/hooks.ts`:

1. In the `import type { ... } from '../../../shared/api-types';` block, add `HeatmapResponse,` (alphabetically, after `DailyPage,` and before `MeetingsPage,`).
2. Directly after the existing `useRecentActivity` function, add:

```typescript
export function useActivityHeatmap(days = 365) {
  return useQuery({
    queryKey: ['activity', 'heatmap', days],
    queryFn: () => get<HeatmapResponse>(`/v1/activity/heatmap?days=${days}`),
    staleTime: 60_000,
  });
}

export function useActivityForDate(date: string | null) {
  return useQuery({
    queryKey: ['activity', 'date', date],
    queryFn: () => get<ActivityRow[]>(`/v1/activity?date=${date}`),
    enabled: date !== null,
    staleTime: 60_000,
  });
}
```

(No query-key collision: `useRecentActivity` keys are `['activity', <number>]`; these are `['activity', 'heatmap', <number>]` and `['activity', 'date', <string>]`.)

- [ ] **Step 5: Run test + typecheck to verify it passes**

```bash
cd desktop && npx vitest run src/renderer/__tests__/activity-hooks.test.tsx
```
Expected: PASS — 3 tests green.

```bash
cd desktop && npm run typecheck
```
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add desktop/src/shared/api-types.ts desktop/src/renderer/lib/api/hooks.ts \
        desktop/src/renderer/__tests__/activity-hooks.test.tsx
git commit -m "feat(desktop): heatmap api types + useActivityHeatmap/useActivityForDate hooks"
```

---

## Task 4: ActivityHeatmap component

**Files:**
- Create: `desktop/src/renderer/components/ActivityHeatmap.tsx`
- Test: `desktop/src/renderer/__tests__/ActivityHeatmap.test.tsx` (create)

Grid orientation: 7 rows (Monday top) × N week-columns, last column contains `endDate`. `endDate` is injectable so tests are deterministic; production callers omit it (defaults to today). 2026-06-01 and 2026-06-08 are Mondays and 2026-06-10 is a Wednesday — the tests below rely on that fixed calendar.

- [ ] **Step 1: Write the failing test**

Create `desktop/src/renderer/__tests__/ActivityHeatmap.test.tsx`:

```tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import React from 'react';

import { ActivityHeatmap, indexHeatmapDays, levelFor } from '../components/ActivityHeatmap';
import type { HeatmapDay } from '../../shared/api-types';

const days: HeatmapDay[] = [
  { date: '2026-06-04', count: 23, bySource: { gmail: 9, slack: 5, system: 9 } },
  { date: '2026-06-09', count: 1, bySource: { gmail: 1 } },
];

describe('levelFor', () => {
  it('returns 0 for zero counts or zero maxCount', () => {
    expect(levelFor(0, 40)).toBe(0);
    expect(levelFor(5, 0)).toBe(0);
  });

  it('buckets counts into quartiles of maxCount', () => {
    expect(levelFor(1, 40)).toBe(1);
    expect(levelFor(10, 40)).toBe(1);
    expect(levelFor(11, 40)).toBe(2);
    expect(levelFor(20, 40)).toBe(2);
    expect(levelFor(21, 40)).toBe(3);
    expect(levelFor(30, 40)).toBe(3);
    expect(levelFor(31, 40)).toBe(4);
    expect(levelFor(40, 40)).toBe(4);
  });

  it('clamps counts above maxCount to 4', () => {
    expect(levelFor(99, 40)).toBe(4);
  });
});

describe('ActivityHeatmap', () => {
  it('renders one button per past day with an aria-label', () => {
    render(
      <ActivityHeatmap
        days={indexHeatmapDays(days)}
        weeks={2}
        maxCount={23}
        endDate="2026-06-10"
      />,
    );
    // endDate 2026-06-10 is a Wednesday → first column Jun 1–7 (7 buttons),
    // last column Jun 8–10 (3 buttons); Jun 11–14 are aria-hidden placeholders.
    expect(screen.getAllByRole('button')).toHaveLength(10);
    expect(
      screen.getByRole('button', { name: '2026-06-04 — 23 events' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: '2026-06-09 — 1 event' }),
    ).toBeInTheDocument();
  });

  it('assigns intensity buckets from maxCount', () => {
    render(
      <ActivityHeatmap
        days={indexHeatmapDays(days)}
        weeks={2}
        maxCount={23}
        endDate="2026-06-10"
      />,
    );
    expect(
      screen.getByRole('button', { name: '2026-06-04 — 23 events' }),
    ).toHaveAttribute('data-level', '4');
    expect(
      screen.getByRole('button', { name: '2026-06-09 — 1 event' }),
    ).toHaveAttribute('data-level', '1');
    expect(
      screen.getByRole('button', { name: '2026-06-01 — 0 events' }),
    ).toHaveAttribute('data-level', '0');
  });

  it('fires onSelectDay with the ISO date', () => {
    const onSelectDay = vi.fn();
    render(
      <ActivityHeatmap
        days={indexHeatmapDays(days)}
        weeks={2}
        maxCount={23}
        endDate="2026-06-10"
        onSelectDay={onSelectDay}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: '2026-06-04 — 23 events' }));
    expect(onSelectDay).toHaveBeenCalledWith('2026-06-04');
  });

  it('shows weekday hints in full mode and hides them in compact mode', () => {
    const { rerender } = render(
      <ActivityHeatmap days={{}} weeks={2} maxCount={0} endDate="2026-06-10" />,
    );
    expect(screen.getByText('mon')).toBeInTheDocument();
    expect(screen.getByText('wed')).toBeInTheDocument();
    expect(screen.getByText('fri')).toBeInTheDocument();
    rerender(
      <ActivityHeatmap days={{}} weeks={2} maxCount={0} endDate="2026-06-10" compact />,
    );
    expect(screen.queryByText('mon')).not.toBeInTheDocument();
  });

  it('labels the month of the first column', () => {
    render(<ActivityHeatmap days={{}} weeks={2} maxCount={0} endDate="2026-06-10" />);
    // Both columns are June → exactly one label.
    expect(screen.getByText('jun')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd desktop && npx vitest run src/renderer/__tests__/ActivityHeatmap.test.tsx
```
Expected: FAIL — `../components/ActivityHeatmap` does not exist.

- [ ] **Step 3: Implement the component**

Create `desktop/src/renderer/components/ActivityHeatmap.tsx`:

```tsx
import type { HeatmapDay } from '../../shared/api-types';

export interface ActivityHeatmapProps {
  /** Heatmap payload indexed by ISO date — build with indexHeatmapDays(). */
  days: Record<string, HeatmapDay>;
  /** Number of week-columns; the last column contains endDate. */
  weeks: number;
  /** Server-side max daily count — drives the intensity buckets. */
  maxCount: number;
  selectedDate?: string | null;
  onSelectDay?: (date: string) => void;
  /** Compact tile mode: smaller cells, no weekday gutter. */
  compact?: boolean;
  /** Last day of the grid (ISO date). Defaults to today; injectable for tests. */
  endDate?: string;
}

export function indexHeatmapDays(days: HeatmapDay[]): Record<string, HeatmapDay> {
  const index: Record<string, HeatmapDay> = {};
  for (const d of days) index[d.date] = d;
  return index;
}

/** Bucket a daily count into 0–4: zero, then quartiles of maxCount. */
export function levelFor(count: number, maxCount: number): 0 | 1 | 2 | 3 | 4 {
  if (count <= 0 || maxCount <= 0) return 0;
  const level = Math.ceil((Math.min(count, maxCount) / maxCount) * 4);
  return Math.max(1, Math.min(4, level)) as 1 | 2 | 3 | 4;
}

// Level 0 uses the hairline tone; 1–3 are neon at 25/50/75% alpha; 4 is full
// neon — consistent with the design tokens in styles.css / colors_and_type.css.
const LEVEL_BG = [
  'var(--hairline)',
  'color-mix(in srgb, var(--neon) 25%, transparent)',
  'color-mix(in srgb, var(--neon) 50%, transparent)',
  'color-mix(in srgb, var(--neon) 75%, transparent)',
  'var(--neon)',
] as const;

const MONTHS = [
  'jan', 'feb', 'mar', 'apr', 'may', 'jun',
  'jul', 'aug', 'sep', 'oct', 'nov', 'dec',
] as const;

// [row, label] — rows are Monday-first (0=mon … 6=sun).
const WEEKDAY_HINTS: Array<[number, string]> = [
  [0, 'mon'],
  [2, 'wed'],
  [4, 'fri'],
];

function isoDate(d: Date): string {
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${m}-${day}`;
}

function parseIso(iso: string): Date {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y!, m! - 1, d!);
}

function addDays(d: Date, n: number): Date {
  const c = new Date(d);
  c.setDate(c.getDate() + n);
  return c;
}

function mondayOf(d: Date): Date {
  const dow = (d.getDay() + 6) % 7; // 0=mon … 6=sun
  return addDays(d, -dow);
}

export function ActivityHeatmap({
  days,
  weeks,
  maxCount,
  selectedDate,
  onSelectDay,
  compact = false,
  endDate,
}: ActivityHeatmapProps) {
  const cell = compact ? 9 : 12;
  const gap = compact ? 2 : 3;
  const gutter = compact ? 0 : 26;
  const end = endDate ? parseIso(endDate) : new Date();
  const firstMonday = addDays(mondayOf(end), -7 * (weeks - 1));

  const columns: Date[] = [];
  for (let w = 0; w < weeks; w += 1) columns.push(addDays(firstMonday, w * 7));

  const monthLabels = columns.map((monday, i) => {
    const month = monday.getMonth();
    if (i === 0 || month !== columns[i - 1]!.getMonth()) return MONTHS[month]!;
    return '';
  });

  return (
    <div className="flex flex-col gap-1" data-testid="activity-heatmap">
      {/* month labels */}
      <div
        className="grid font-mono text-9 text-ink-3"
        style={{
          gridTemplateColumns: `repeat(${weeks}, ${cell}px)`,
          gap: `${gap}px`,
          marginLeft: gutter,
        }}
      >
        {monthLabels.map((label, i) => (
          <span key={i} className="overflow-visible whitespace-nowrap">
            {label}
          </span>
        ))}
      </div>
      <div className="flex" style={{ gap: `${gap}px` }}>
        {/* weekday gutter (non-compact only) */}
        {!compact && (
          <div
            className="relative flex-shrink-0 font-mono text-9 text-ink-3"
            style={{ width: gutter - gap, height: 7 * cell + 6 * gap }}
          >
            {WEEKDAY_HINTS.map(([row, label]) => (
              <span
                key={label}
                className="absolute left-0"
                style={{ top: row * (cell + gap) }}
              >
                {label}
              </span>
            ))}
          </div>
        )}
        {/* cells — column flow so each week-column reads top (mon) to bottom (sun) */}
        <div
          className="grid"
          style={{
            gridTemplateColumns: `repeat(${weeks}, ${cell}px)`,
            gridTemplateRows: `repeat(7, ${cell}px)`,
            gridAutoFlow: 'column',
            gap: `${gap}px`,
          }}
        >
          {columns.flatMap((monday) =>
            Array.from({ length: 7 }, (_, row) => {
              const d = addDays(monday, row);
              const iso = isoDate(d);
              if (d > end) {
                // Future days keep the grid shape but are not interactive.
                return (
                  <span
                    key={`pad-${iso}`}
                    aria-hidden
                    style={{ width: cell, height: cell }}
                  />
                );
              }
              const count = days[iso]?.count ?? 0;
              const level = levelFor(count, maxCount);
              const selected = selectedDate === iso;
              return (
                <button
                  key={iso}
                  type="button"
                  data-level={level}
                  data-date={iso}
                  aria-label={`${iso} — ${count} ${count === 1 ? 'event' : 'events'}`}
                  onClick={onSelectDay ? () => onSelectDay(iso) : undefined}
                  className="cursor-pointer border-0 p-0"
                  style={{
                    width: cell,
                    height: cell,
                    borderRadius: 2,
                    background: LEVEL_BG[level],
                    outline: selected ? '1px solid var(--neon)' : 'none',
                    outlineOffset: 1,
                  }}
                />
              );
            }),
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd desktop && npx vitest run src/renderer/__tests__/ActivityHeatmap.test.tsx
```
Expected: PASS — 6 tests green.

```bash
cd desktop && npm run typecheck
```
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/renderer/components/ActivityHeatmap.tsx \
        desktop/src/renderer/__tests__/ActivityHeatmap.test.tsx
git commit -m "feat(desktop): ActivityHeatmap component with 5 intensity buckets"
```

---

## Task 5: Activity screen + ScreenId + sidebar + App routing

**Files:**
- Create: `desktop/src/renderer/stores/selected-day.ts`
- Create: `desktop/src/renderer/components/ActivityFeedRow.tsx` (extracted from today.tsx)
- Create: `desktop/src/renderer/screens/activity.tsx`
- Modify: `desktop/src/renderer/stores/navigation.ts`
- Modify: `desktop/src/renderer/components/Sidebar.tsx`
- Modify: `desktop/src/renderer/App.tsx`
- Modify: `desktop/src/renderer/screens/today.tsx` (use the extracted row)
- Test: `desktop/src/renderer/__tests__/ActivityScreen.test.tsx` (create)
- Test: `desktop/src/renderer/__tests__/App.test.tsx` (extend)

- [ ] **Step 1: Write the failing screen test**

Create `desktop/src/renderer/__tests__/ActivityScreen.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

import { ActivityScreen } from '../screens/activity';
import { useSelectedDay } from '../stores/selected-day';
import { useNoteView } from '../stores/note-view';
import type { ActivityRow, HeatmapResponse } from '../../shared/api-types';

// Dynamic recent dates: the screen's heatmap always ends at the real today,
// so fixture days must fall inside the rendered window whenever the test runs.
function recentIso(daysAgo: number): string {
  const d = new Date();
  d.setDate(d.getDate() - daysAgo);
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${m}-${day}`;
}

const D_MAIN = recentIso(6);
const D_OTHER = recentIso(1);

const heatmapPayload: HeatmapResponse = {
  days: [
    { date: D_MAIN, count: 3, bySource: { gmail: 2, system: 1 } },
    { date: D_OTHER, count: 1, bySource: { slack: 1 } },
  ],
  total: 4,
  maxCount: 3,
};

const rowsMain: ActivityRow[] = [
  {
    id: `audit-${D_MAIN}-2`,
    source: 'gmail',
    verb: 'processed',
    subject: 'newsletters',
    atRelative: '6d',
    at: `${D_MAIN}T10:30:00+00:00`,
    path: '20-contexts/personal/notes/newsletters.md',
  },
  {
    id: `audit-${D_MAIN}-1`,
    source: 'gmail',
    verb: 'processed',
    subject: 'standup-notes',
    atRelative: '6d',
    at: `${D_MAIN}T09:00:00+00:00`,
    path: null,
  },
  {
    id: `audit-${D_MAIN}-0`,
    source: 'system',
    verb: 'connector skipped',
    subject: 'joplin',
    atRelative: '6d',
    at: `${D_MAIN}T08:00:00+00:00`,
    path: null,
  },
];

const apiRequest = vi.fn();

beforeEach(() => {
  apiRequest.mockReset();
  apiRequest.mockImplementation(async (_method: string, path: string) => {
    if (path.startsWith('/v1/activity/heatmap')) {
      return { ok: true, status: 200, data: heatmapPayload };
    }
    if (path === `/v1/activity?date=${D_MAIN}`) {
      return { ok: true, status: 200, data: rowsMain };
    }
    return { ok: true, status: 200, data: [] };
  });
  window.gb.api.request = apiRequest as typeof window.gb.api.request;
  useSelectedDay.setState({ selectedDate: D_MAIN });
  useNoteView.setState({ path: null });
});

function wrap(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{node}</QueryClientProvider>;
}

describe('ActivityScreen', () => {
  it('renders the year heatmap and the selected day log', async () => {
    render(wrap(<ActivityScreen />));
    expect(
      await screen.findByRole('button', { name: `${D_MAIN} — 3 events` }),
    ).toBeInTheDocument();
    expect(await screen.findByText('newsletters')).toBeInTheDocument();
    expect(screen.getByText('standup-notes')).toBeInTheDocument();
    expect(screen.getByText('joplin')).toBeInTheDocument();
  });

  it('clicking a heatmap day loads that day log', async () => {
    render(wrap(<ActivityScreen />));
    const cell = await screen.findByRole('button', { name: `${D_OTHER} — 1 event` });
    fireEvent.click(cell);
    expect(useSelectedDay.getState().selectedDate).toBe(D_OTHER);
    await waitFor(() =>
      expect(apiRequest).toHaveBeenCalledWith('GET', `/v1/activity?date=${D_OTHER}`),
    );
  });

  it('source chips filter the visible rows client-side', async () => {
    render(wrap(<ActivityScreen />));
    await screen.findByText('newsletters');
    fireEvent.click(screen.getByRole('button', { name: /^gmail/ }));
    expect(screen.getByText('newsletters')).toBeInTheDocument();
    expect(screen.getByText('standup-notes')).toBeInTheDocument();
    expect(screen.queryByText('joplin')).not.toBeInTheDocument();
  });

  it('clicking a row with a path opens NoteView', async () => {
    render(wrap(<ActivityScreen />));
    fireEvent.click(await screen.findByText('newsletters'));
    expect(useNoteView.getState().path).toBe(
      '20-contexts/personal/notes/newsletters.md',
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd desktop && npx vitest run src/renderer/__tests__/ActivityScreen.test.tsx
```
Expected: FAIL — `../screens/activity` and `../stores/selected-day` do not exist.

- [ ] **Step 3: Create the selected-day store**

Create `desktop/src/renderer/stores/selected-day.ts`:

```typescript
import { create } from 'zustand';

interface SelectedDayState {
  /** ISO date (YYYY-MM-DD) preselected for the activity screen; null = today. */
  selectedDate: string | null;
  setSelectedDate: (date: string | null) => void;
}

export const useSelectedDay = create<SelectedDayState>((set) => ({
  selectedDate: null,
  setSelectedDate: (selectedDate) => set({ selectedDate }),
}));
```

- [ ] **Step 4: Extract the activity feed row from today.tsx**

Create `desktop/src/renderer/components/ActivityFeedRow.tsx` (the body is the existing `ActivityRowComp` from `today.tsx`, verbatim):

```tsx
import type { ActivityRow } from '../../shared/api-types';

interface Props {
  source: ActivityRow['source'];
  verb: ActivityRow['verb'];
  subject: ActivityRow['subject'];
  time: string;
  onClick?: () => void;
}

export function ActivityFeedRow({ source, verb, subject, time, onClick }: Props) {
  const className =
    'flex w-full items-center gap-[10px] rounded-sm px-[6px] py-2 text-left' +
    (onClick ? ' cursor-pointer hover:bg-paper' : '');
  const content = (
    <>
      <img
        src={`assets/connectors/${source}.svg`}
        alt=""
        className="h-[14px] w-[14px] opacity-90"
      />
      <span className="font-mono text-10 text-ink-2">{verb}</span>
      <span className="flex-1 overflow-hidden text-ellipsis whitespace-nowrap text-12 text-ink-0">
        {subject}
      </span>
      <span className="font-mono text-10 text-ink-3">{time}</span>
    </>
  );
  if (onClick) {
    return (
      <button type="button" onClick={onClick} className={className}>
        {content}
      </button>
    );
  }
  return <div className={className}>{content}</div>;
}
```

Then edit `desktop/src/renderer/screens/today.tsx`:

1. Add to the component imports (next to the other `../components/` imports):
   ```typescript
   import { ActivityFeedRow } from '../components/ActivityFeedRow';
   ```
2. Delete the entire `interface ActivityRowCompProps { ... }` and `function ActivityRowComp(...) { ... }` block (the one rendering `assets/connectors/${source}.svg` with the `verb`/`subject`/`time` spans — it is now `ActivityFeedRow`).
3. In `ActivityList`, change `<ActivityRowComp` to `<ActivityFeedRow` (props are identical).

- [ ] **Step 5: Implement the screen**

Create `desktop/src/renderer/screens/activity.tsx`:

```tsx
import { useEffect, useMemo, useState } from 'react';
import { TopBar } from '../components/TopBar';
import { Panel } from '../components/Panel';
import { ActivityFeedRow } from '../components/ActivityFeedRow';
import { ActivityHeatmap, indexHeatmapDays } from '../components/ActivityHeatmap';
import { PanelEmpty } from '../components/PanelEmpty';
import { PanelError } from '../components/PanelError';
import { SkeletonRows } from '../components/SkeletonRows';
import { useActivityForDate, useActivityHeatmap } from '../lib/api/hooks';
import { useNoteView } from '../stores/note-view';
import { useSelectedDay } from '../stores/selected-day';

function todayIso(): string {
  const d = new Date();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${m}-${day}`;
}

function timeOf(at: string): string {
  const d = new Date(at);
  if (Number.isNaN(d.getTime())) return '';
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

export function ActivityScreen() {
  const heatmap = useActivityHeatmap(365);
  const selectedDate = useSelectedDay((s) => s.selectedDate);
  const setSelectedDate = useSelectedDay((s) => s.setSelectedDate);
  const selected = selectedDate ?? todayIso();
  const dayLog = useActivityForDate(selected);
  const openNote = useNoteView((s) => s.open);
  const [sourceFilter, setSourceFilter] = useState<string | null>(null);

  // Chips are derived per-day; switching day resets the filter.
  useEffect(() => setSourceFilter(null), [selected]);

  const index = useMemo(
    () => indexHeatmapDays(heatmap.data?.days ?? []),
    [heatmap.data],
  );
  const bySource = index[selected]?.bySource ?? {};
  const chips = Object.entries(bySource).sort((a, b) => b[1] - a[1]);
  const rows = (dayLog.data ?? []).filter(
    (r) => sourceFilter === null || r.source === sourceFilter,
  );

  return (
    <div className="flex-1 overflow-y-auto bg-paper">
      <TopBar
        title="activity"
        subtitle={
          heatmap.data ? `${heatmap.data.total} events · last 12 months` : '…'
        }
      />
      <div className="mx-auto flex max-w-[1100px] flex-col gap-4 px-8 pb-10 pt-6">
        <Panel title="contributions" subtitle="every audit event · one square per day">
          {heatmap.isLoading && <SkeletonRows count={3} />}
          {heatmap.isError && (
            <PanelError
              message={
                heatmap.error instanceof Error
                  ? heatmap.error.message
                  : 'failed to load heatmap'
              }
              onRetry={() => heatmap.refetch()}
            />
          )}
          {heatmap.data && (
            <div className="overflow-x-auto p-1">
              <ActivityHeatmap
                days={index}
                weeks={53}
                maxCount={heatmap.data.maxCount}
                selectedDate={selected}
                onSelectDay={setSelectedDate}
              />
            </div>
          )}
        </Panel>

        <Panel
          title="day log"
          subtitle={selected}
          action={
            chips.length > 0 ? (
              <div className="flex flex-wrap justify-end gap-1">
                <SourceChip
                  label="all"
                  count={dayLog.data?.length ?? 0}
                  active={sourceFilter === null}
                  onClick={() => setSourceFilter(null)}
                />
                {chips.map(([src, n]) => (
                  <SourceChip
                    key={src}
                    label={src}
                    count={n}
                    active={sourceFilter === src}
                    onClick={() => setSourceFilter(src)}
                  />
                ))}
              </div>
            ) : undefined
          }
        >
          {dayLog.isLoading && <SkeletonRows count={4} />}
          {dayLog.isError && (
            <PanelError
              message={
                dayLog.error instanceof Error
                  ? dayLog.error.message
                  : 'failed to load day log'
              }
              onRetry={() => dayLog.refetch()}
            />
          )}
          {dayLog.data && rows.length === 0 && (
            <PanelEmpty
              icon="activity"
              message="activity appears as poltergeist lives with you"
            />
          )}
          {rows.map((row) => (
            <ActivityFeedRow
              key={row.id}
              source={row.source}
              verb={row.verb}
              subject={row.subject}
              time={timeOf(row.at)}
              onClick={row.path ? () => openNote(row.path!) : undefined}
            />
          ))}
        </Panel>
      </div>
    </div>
  );
}

function SourceChip({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`cursor-pointer rounded-pill border px-2 py-[2px] font-mono text-10 transition-colors duration-[120ms] ${
        active
          ? 'border-neon/40 bg-neon/12 text-neon-ink'
          : 'border-hairline bg-transparent text-ink-2 hover:bg-vellum'
      }`}
    >
      {label} <span className="text-ink-3">{count}</span>
    </button>
  );
}
```

- [ ] **Step 6: Wire navigation, sidebar, and App**

Edit `desktop/src/renderer/stores/navigation.ts` — extend the union:

```typescript
export type ScreenId =
  | 'today'
  | 'activity'
  | 'connectors'
  | 'meetings'
  | 'capture'
  | 'vault'
  | 'daily'
  | 'setup'
  | 'settings';
```

Edit `desktop/src/renderer/components/Sidebar.tsx` — in `NAV_ITEMS`, insert after the `today` entry (spec: icon `calendar-days`; `lucide-react` exports `CalendarDays`, which the `Lucide` wrapper resolves from the kebab name):

```typescript
  { id: 'activity', icon: 'calendar-days', label: 'activity' },
```

Edit `desktop/src/renderer/App.tsx`:

1. Add the import next to the other screens:
   ```typescript
   import { ActivityScreen } from './screens/activity';
   ```
2. In the screen conditionals, after `{active === 'today' && <TodayScreen />}` add:
   ```typescript
   {active === 'activity' && <ActivityScreen />}
   ```

- [ ] **Step 7: Extend the App test with sidebar navigation**

Replace `desktop/src/renderer/__tests__/App.test.tsx`:

```tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import App from '../App';
import { useNavigation } from '../stores/navigation';

function wrap() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  useNavigation.setState({ active: 'today' });
});

describe('App', () => {
  it('renders the brand without throwing', async () => {
    wrap();
    expect(await screen.findByText('poltergeist')).toBeInTheDocument();
  });

  it('navigates to the activity screen from the sidebar', async () => {
    wrap();
    fireEvent.click(await screen.findByRole('button', { name: 'activity' }));
    expect(
      await screen.findByRole('heading', { name: 'activity', level: 1 }),
    ).toBeInTheDocument();
  });
});
```

- [ ] **Step 8: Run tests to verify they pass**

```bash
cd desktop && npx vitest run src/renderer/__tests__/ActivityScreen.test.tsx src/renderer/__tests__/App.test.tsx
```
Expected: PASS — 4 screen tests + 2 App tests green.

```bash
cd desktop && npx vitest run
```
Expected: **32 passed** (18 baseline + 3 hooks + 6 heatmap + 4 screen + 1 new App test). The today-screen still compiles against `ActivityFeedRow`.

```bash
cd desktop && npm run typecheck
```
Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add desktop/src/renderer/stores/selected-day.ts \
        desktop/src/renderer/stores/navigation.ts \
        desktop/src/renderer/components/ActivityFeedRow.tsx \
        desktop/src/renderer/components/Sidebar.tsx \
        desktop/src/renderer/screens/activity.tsx \
        desktop/src/renderer/screens/today.tsx \
        desktop/src/renderer/App.tsx \
        desktop/src/renderer/__tests__/ActivityScreen.test.tsx \
        desktop/src/renderer/__tests__/App.test.tsx
git commit -m "feat(desktop): activity screen with year heatmap, day log, source chips"
```

---

## Task 6: Today-dashboard 12-week heatmap tile

**Files:**
- Create: `desktop/src/renderer/components/ActivityHeatmapTile.tsx`
- Modify: `desktop/src/renderer/screens/today.tsx`
- Test: `desktop/src/renderer/__tests__/ActivityHeatmapTile.test.tsx` (create)

- [ ] **Step 1: Write the failing test**

Create `desktop/src/renderer/__tests__/ActivityHeatmapTile.test.tsx`:

```tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

import { ActivityHeatmapTile } from '../components/ActivityHeatmapTile';
import { useNavigation } from '../stores/navigation';
import { useSelectedDay } from '../stores/selected-day';
import type { HeatmapResponse } from '../../shared/api-types';

function recentIso(daysAgo: number): string {
  const d = new Date();
  d.setDate(d.getDate() - daysAgo);
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${m}-${day}`;
}

const D = recentIso(3);

const payload: HeatmapResponse = {
  days: [{ date: D, count: 23, bySource: { gmail: 23 } }],
  total: 23,
  maxCount: 23,
};

const apiRequest = vi.fn();

beforeEach(() => {
  apiRequest.mockReset();
  apiRequest.mockResolvedValue({ ok: true, status: 200, data: payload });
  window.gb.api.request = apiRequest as typeof window.gb.api.request;
  useNavigation.setState({ active: 'today' });
  useSelectedDay.setState({ selectedDate: null });
});

function wrap(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{node}</QueryClientProvider>;
}

describe('ActivityHeatmapTile', () => {
  it('requests 84 days (12 weeks) of heatmap data', async () => {
    render(wrap(<ActivityHeatmapTile />));
    await screen.findByRole('button', { name: `${D} — 23 events` });
    expect(apiRequest).toHaveBeenCalledWith('GET', '/v1/activity/heatmap?days=84');
  });

  it('cell click preselects the day and navigates to the activity screen', async () => {
    render(wrap(<ActivityHeatmapTile />));
    fireEvent.click(await screen.findByRole('button', { name: `${D} — 23 events` }));
    expect(useSelectedDay.getState().selectedDate).toBe(D);
    expect(useNavigation.getState().active).toBe('activity');
  });

  it('the open action navigates without preselecting a day', async () => {
    useSelectedDay.setState({ selectedDate: D });
    render(wrap(<ActivityHeatmapTile />));
    fireEvent.click(await screen.findByRole('button', { name: 'open' }));
    expect(useSelectedDay.getState().selectedDate).toBe(null);
    expect(useNavigation.getState().active).toBe('activity');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd desktop && npx vitest run src/renderer/__tests__/ActivityHeatmapTile.test.tsx
```
Expected: FAIL — `../components/ActivityHeatmapTile` does not exist.

- [ ] **Step 3: Implement the tile**

Create `desktop/src/renderer/components/ActivityHeatmapTile.tsx`:

```tsx
import { useMemo } from 'react';
import { Btn } from './Btn';
import { Lucide } from './Lucide';
import { Panel } from './Panel';
import { PanelError } from './PanelError';
import { SkeletonRows } from './SkeletonRows';
import { ActivityHeatmap, indexHeatmapDays } from './ActivityHeatmap';
import { useActivityHeatmap } from '../lib/api/hooks';
import { useNavigation } from '../stores/navigation';
import { useSelectedDay } from '../stores/selected-day';

const TILE_WEEKS = 12;
const TILE_DAYS = TILE_WEEKS * 7; // 84

export function ActivityHeatmapTile() {
  const heatmap = useActivityHeatmap(TILE_DAYS);
  const setActive = useNavigation((s) => s.setActive);
  const setSelectedDate = useSelectedDay((s) => s.setSelectedDate);
  const index = useMemo(
    () => indexHeatmapDays(heatmap.data?.days ?? []),
    [heatmap.data],
  );

  return (
    <Panel
      title="ghost activity"
      subtitle="last 12 weeks"
      action={
        <Btn
          variant="ghost"
          size="sm"
          iconRight={<Lucide name="arrow-right" size={12} />}
          onClick={() => {
            setSelectedDate(null); // activity screen defaults to today
            setActive('activity');
          }}
        >
          open
        </Btn>
      }
    >
      {heatmap.isLoading && <SkeletonRows count={2} />}
      {heatmap.isError && (
        <PanelError
          message={
            heatmap.error instanceof Error
              ? heatmap.error.message
              : 'failed to load activity heatmap'
          }
          onRetry={() => heatmap.refetch()}
        />
      )}
      {heatmap.data && (
        <div className="p-1">
          <ActivityHeatmap
            days={index}
            weeks={TILE_WEEKS}
            maxCount={heatmap.data.maxCount}
            compact
            onSelectDay={(date) => {
              setSelectedDate(date);
              setActive('activity');
            }}
          />
        </div>
      )}
    </Panel>
  );
}
```

- [ ] **Step 4: Place the tile on the today screen**

Edit `desktop/src/renderer/screens/today.tsx`:

1. Add the import next to the other component imports:
   ```typescript
   import { ActivityHeatmapTile } from '../components/ActivityHeatmapTile';
   ```
2. Insert the tile between the two-column agenda/activity grid and the connectors panel. Find:

   ```tsx
        </div>

        {/* Connector pulse strip */}
   ```

   (the `</div>` closing the `{/* Two-column: agenda + activity */}` grid) and change it to:

   ```tsx
        </div>

        {/* 12-week activity heatmap */}
        <ActivityHeatmapTile />

        {/* Connector pulse strip */}
   ```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd desktop && npx vitest run src/renderer/__tests__/ActivityHeatmapTile.test.tsx
```
Expected: PASS — 3 tests green.

```bash
cd desktop && npx vitest run
```
Expected: **35 passed**.

```bash
cd desktop && npm run typecheck
```
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add desktop/src/renderer/components/ActivityHeatmapTile.tsx \
        desktop/src/renderer/screens/today.tsx \
        desktop/src/renderer/__tests__/ActivityHeatmapTile.test.tsx
git commit -m "feat(desktop): 12-week activity heatmap tile on today dashboard"
```

---

## Task 7: Full regression + manual end-to-end verification

No new code — confirm the whole feature against the real vault before calling it done.

- [ ] **Step 1: Full automated regression**

From the worktree root:
```bash
/Users/jannik/development/nikrich/ghost-brain/.venv/bin/python -m pytest ghostbrain/api/tests/ -q
```
Expected: **57 passed**.

```bash
cd desktop && npx vitest run && npm run typecheck
```
Expected: **35 passed**, typecheck clean.

- [ ] **Step 2: Boot the sidecar against the real vault**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/feat-activity-and-import
/Users/jannik/development/nikrich/ghost-brain/.venv/bin/python -m ghostbrain.api
```
Expected: a single line `READY port=<PORT> token=<TOKEN> scheduler=off` (scheduler stays off without `GHOSTBRAIN_SCHEDULER_ENABLED=1`; VAULT_PATH unset → it reads `~/ghostbrain/vault`). Note PORT and TOKEN.

- [ ] **Step 3: Curl the heatmap endpoint**

In a second terminal (substitute PORT/TOKEN from the READY line):
```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:$PORT/v1/activity/heatmap?days=30" | python3 -m json.tool | head -40
```
Expected: JSON with `days` containing real dates (the audit dir has files for 2026-06-04 … 2026-06-10), each with `count` and a `bySource` map containing keys like `gmail`, `slack`, and `system` (sourceless `connector_skipped`/`connector_crashed` events bucket as `system`); `total` > 0 and `maxCount` ≥ every day's `count`.

- [ ] **Step 4: Curl the date drill-down**

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:$PORT/v1/activity?date=$(date +%F)" | python3 -m json.tool | head -40
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:$PORT/v1/activity?date=banana"
```
Expected: first call returns today's full row list (ids like `audit-<date>-<lineno>`, newest first); second prints `422`. Stop the sidecar (Ctrl-C) when done.

- [ ] **Step 5: Visual check in the app**

```bash
cd desktop && npm run dev
```

Checklist:
- Today screen shows the "ghost activity · last 12 weeks" tile between the agenda/activity row and the connectors strip; recent days are neon-tinted.
- Clicking a tile cell lands on the activity screen with that day outlined and its log shown; clicking "open" lands with today selected.
- Sidebar shows "activity" (calendar-days icon) right under "today"; the row highlights when active.
- Activity screen: full-year heatmap with month labels on top and mon/wed/fri hints on the left; hovering/focusing a cell reads "YYYY-MM-DD — N events" (VoiceOver or devtools accessibility pane).
- Day log: source chips ("all", then per-source with counts) filter rows instantly; a row with a vault path opens NoteView; a day with no events shows "activity appears as poltergeist lives with you".
- Theme toggle (settings) keeps the level-0 squares visible in both themes (hairline tone).

- [ ] **Step 6: Record the E2E pass**

Append under a new "Implementation status" heading at the bottom of `docs/superpowers/specs/2026-06-10-activity-heatmap-design.md`:
```
## Implementation status

- 2026-06-XX: E2E pass — heatmap endpoint + date drill-down verified against the real vault; tile → screen → day log → NoteView flow verified visually.
```

```bash
git add docs/superpowers/specs/2026-06-10-activity-heatmap-design.md
git commit -m "docs(spec): record activity heatmap E2E pass"
```

---

## Self-Review Notes

After writing this plan, I checked it against the spec and the actual codebase on this branch:

**Coverage:** Backend §1 (heatmap endpoint: days 1–730 default 365, bySource, maxCount, omitted empty days, malformed-line warning) → Tasks 1–2. Backend §2 (`?date=` extension, date wins, 422) → Tasks 1–2. Desktop §3 (component, 5 buckets from maxCount, neon 25/50/75/100 + hairline level-0, button cells with aria-labels, month labels, mon/wed/fri hints, compact mode) → Task 4. §4 (today tile, cell click preselects) → Task 6. §5 (screen, ScreenId, sidebar calendar-days, year heatmap, day log default today, chips from bySource, NoteView links, hooks with 60s staleTime) → Tasks 3 + 5. Error handling (PanelError, empty-day copy) → Tasks 5–6. Testing section → per-task TDD + Task 7 manual E2E.

**Deliberate deviations (all argued from the real code):**
1. **`_source_for` fallback "ghostbrain" → "system"** (Task 1). The spec's chips are derived from `bySource` and filter `ActivityRow.source` client-side — the two mappings must be identical or chip-filtering silently breaks. Changing the shared fallback is the smallest change that satisfies the spec's "else bucketed as system" wording. No existing test asserts the old value; the only consumer renders `assets/connectors/${source}.svg`, which has neither `ghostbrain.svg` nor `system.svg`, so the visible behavior is unchanged.
2. **Synthetic day-log row ids** (`audit-{date}-{lineno}`). Real audit files repeat `event_id` within a day (verified: `connector_skipped`/`joplin` repeats every scheduler cycle), and the renderer keys rows by `id`. The existing `list_activity` id behavior is untouched.
3. **`ActivityFeedRow` extracted from `today.tsx`** rather than re-implemented — the spec says "reusing the existing activity-feed row rendering", and the component was previously file-private (`ActivityRowComp`).
4. **`endDate` prop added to `ActivityHeatmap`** beyond the spec's prop list, solely so component tests are calendar-deterministic; production callers omit it.
5. **Day-log rows show local `HH:MM`** instead of `atRelative` — a relative "6d" is the same for every row of a past day and useless inside a single-day log. `atRelative` is still served and used by the today feed.
6. **Screen/tile tests use dynamically computed recent dates** (the screen's heatmap window always ends at the real today), while pure component tests pin `endDate="2026-06-10"`.

**Type consistency:** `HeatmapDay`/`HeatmapResponse` in `desktop/src/shared/api-types.ts` (Task 3) mirror the pydantic models in `ghostbrain/api/models/activity.py` (Task 2), which mirror the dict literals produced by `build_heatmap` (Task 1). `useActivityForDate` returns `ActivityRow[]` — the response model of the extended route. `ActivityHeatmapProps.days: Record<string, HeatmapDay>` is produced only via the exported `indexHeatmapDays`, used by both the screen (Task 5) and the tile (Task 6). `ScreenId` gains exactly one member, `'activity'`, consumed by Sidebar/App/tile.

**Counts:** backend 42 → 51 (Task 1) → 57 (Task 2); desktop 18 → 21 (Task 3) → 27 (Task 4) → 32 (Task 5) → 35 (Task 6).

**No placeholders:** every step has complete runnable code or an exact command with its expected outcome.
