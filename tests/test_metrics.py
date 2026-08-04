"""Tests for metrics: staleness + check-in suggestions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml


def _write_note(path: Path, frontmatter_dict: dict[str, Any], body: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    yaml_block = yaml.safe_dump(frontmatter_dict, sort_keys=False).rstrip()
    path.write_text(f"---\n{yaml_block}\n---\n\n{body}\n", encoding="utf-8")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# staleness
# ---------------------------------------------------------------------------


def test_stale_pr_flagged_when_old(vault: Path) -> None:
    from ghostbrain.metrics.staleness import find_stale_items

    now = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
    pr_dir = vault / "20-contexts" / "consulting" / "github" / "prs"
    _write_note(pr_dir / "old.md", {
        "id": "github:pr:consulting/x#1", "type": "pr",
        "context": "consulting", "source": "github",
        "title": "Old PR", "state": "OPEN",
        "updated": _iso(now - timedelta(days=5)),
    })
    _write_note(pr_dir / "fresh.md", {
        "id": "github:pr:consulting/x#2", "type": "pr",
        "context": "consulting", "source": "github",
        "title": "Fresh PR", "state": "OPEN",
        "updated": _iso(now - timedelta(hours=6)),
    })
    _write_note(pr_dir / "merged.md", {
        "id": "github:pr:consulting/x#3", "type": "pr",
        "context": "consulting", "source": "github",
        "title": "Done PR", "state": "MERGED",
        "updated": _iso(now - timedelta(days=10)),
    })

    items = find_stale_items(now=now)
    titles = [i.title for i in items]
    assert "Old PR" in titles
    assert "Fresh PR" not in titles
    assert "Done PR" not in titles  # closed states excluded


def test_stale_ticket_flagged(vault: Path) -> None:
    from ghostbrain.metrics.staleness import find_stale_items

    now = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
    tk_dir = vault / "20-contexts" / "work" / "jira" / "tickets"
    _write_note(tk_dir / "stale.md", {
        "id": "jira:acme:Helix-1", "type": "ticket",
        "context": "work", "source": "jira",
        "title": "Helix-1 stale work", "status": "In Progress",
        "key": "Helix-1",
        "updated": _iso(now - timedelta(days=10)),
    })
    _write_note(tk_dir / "fresh.md", {
        "id": "jira:acme:Helix-2", "type": "ticket",
        "context": "work", "source": "jira",
        "title": "Helix-2 fresh", "status": "In Progress",
        "key": "Helix-2",
        "updated": _iso(now - timedelta(days=2)),
    })
    _write_note(tk_dir / "done.md", {
        "id": "jira:acme:Helix-3", "type": "ticket",
        "context": "work", "source": "jira",
        "title": "Helix-3 done", "status": "Done",
        "key": "Helix-3",
        "updated": _iso(now - timedelta(days=20)),
    })

    items = find_stale_items(now=now)
    keys = [i.extra.get("key") for i in items if i.kind == "ticket"]
    assert "Helix-1" in keys
    assert "Helix-2" not in keys
    assert "Helix-3" not in keys


# ---------------------------------------------------------------------------
# check-ins
# ---------------------------------------------------------------------------


def test_checkin_for_pending_review(vault: Path) -> None:
    from ghostbrain.metrics.checkins import suggest_checkins

    now = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
    pr_dir = vault / "20-contexts" / "work" / "github" / "prs"
    _write_note(pr_dir / "review.md", {
        "id": "github:pr:acme/x#42", "type": "pr",
        "context": "work", "source": "github",
        "title": "feat: thing",
        "state": "OPEN", "repo": "acme/x", "number": 42,
        "updated": _iso(now - timedelta(days=4)),
        "rawData": {
            "author": {"login": "alex"},
            "metadata": {"origin": "review-requested"},
        },
    })

    suggestions = suggest_checkins(now=now)
    assert len(suggestions) == 1
    assert suggestions[0].person == "alex"
    assert "review-requested" in suggestions[0].reason


def test_checkin_for_idle_assignee(vault: Path) -> None:
    from ghostbrain.metrics.checkins import suggest_checkins

    now = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
    tk_dir = vault / "20-contexts" / "work" / "jira" / "tickets"
    _write_note(tk_dir / "stuck.md", {
        "id": "jira:acme:Helix-9", "type": "ticket",
        "context": "work", "source": "jira",
        "title": "Helix-9 stuck",
        "status": "In Progress", "key": "Helix-9",
        "updated": _iso(now - timedelta(days=10)),
        "rawData": {
            "fields": {"assignee": {"displayName": "Lawrence"}},
        },
    })

    suggestions = suggest_checkins(now=now)
    assert any(s.person == "Lawrence" for s in suggestions)
    s = next(s for s in suggestions if s.person == "Lawrence")
    assert "Helix-9" in s.reason


def test_checkin_for_overdue_one_on_one(vault: Path) -> None:
    from ghostbrain.metrics.checkins import suggest_checkins

    now = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
    cal_dir = vault / "20-contexts" / "consulting" / "calendar"
    _write_note(cal_dir / "1-1.md", {
        "id": "calendar:google:x:y", "type": "event",
        "context": "consulting", "source": "calendar",
        "title": "1:1 with Manager",
        "start": _iso(now - timedelta(days=20)),
        "end":   _iso(now - timedelta(days=20, hours=-1)),
        "isAllDay": False,
    })

    suggestions = suggest_checkins(now=now, last_1_1_gap_days=14)
    assert any("Manager" in s.person for s in suggestions)


def test_checkin_no_one_on_one_if_recent(vault: Path) -> None:
    from ghostbrain.metrics.checkins import suggest_checkins

    now = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)
    cal_dir = vault / "20-contexts" / "consulting" / "calendar"
    _write_note(cal_dir / "1-1.md", {
        "id": "calendar:google:x:y", "type": "event",
        "context": "consulting", "source": "calendar",
        "title": "1:1 with Alex",
        "start": _iso(now - timedelta(days=5)),
        "end":   _iso(now - timedelta(days=5, hours=-1)),
        "isAllDay": False,
    })

    suggestions = suggest_checkins(now=now, last_1_1_gap_days=14)
    assert not any("Alex" in s.person for s in suggestions)


def test_checkins_dedup_per_person(vault: Path) -> None:
    """If the same person appears for multiple reasons, keep the most acute."""
    from ghostbrain.metrics.checkins import suggest_checkins

    now = datetime(2026, 5, 8, 12, 0, tzinfo=timezone.utc)

    pr_dir = vault / "20-contexts" / "work" / "github" / "prs"
    _write_note(pr_dir / "review.md", {
        "id": "p1", "type": "pr", "context": "work", "source": "github",
        "title": "x", "state": "OPEN", "repo": "x", "number": 1,
        "updated": _iso(now - timedelta(days=3)),  # 3 days
        "rawData": {
            "author": {"login": "alex"},
            "metadata": {"origin": "review-requested"},
        },
    })
    cal_dir = vault / "20-contexts" / "consulting" / "calendar"
    _write_note(cal_dir / "1-1.md", {
        "id": "e1", "type": "event", "context": "consulting",
        "source": "calendar",
        "title": "1:1 with Alex",
        "start": _iso(now - timedelta(days=30)),  # 30 days — bigger
        "end":   _iso(now - timedelta(days=30, hours=-1)),
        "isAllDay": False,
    })

    suggestions = suggest_checkins(now=now)
    alex_entries = [s for s in suggestions if s.person.lower() == "alex"]
    assert len(alex_entries) == 1
    # The 30-day-gap reason should win (it's more acute).
    assert "1:1" in alex_entries[0].reason


# ---------------------------------------------------------------------------
# snapshot CLI
# ---------------------------------------------------------------------------


def test_snapshot_writes_velocity_file(vault: Path) -> None:
    from ghostbrain.metrics.snapshot import build_snapshot, write_snapshot

    snap = build_snapshot()
    out = write_snapshot(snap)

    assert out.exists()
    body = out.read_text()
    assert "Velocity snapshot" in body
    assert "Check-ins suggested" in body
    assert "Stale PRs" in body
    assert "Stale tickets" in body
