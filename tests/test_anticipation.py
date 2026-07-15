"""Tests for anticipation prompts (weekday × context histogram)."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml


def _configure(vault: Path, ctxs: list[str]) -> None:
    """Point the vault's configured context list at the contexts these
    fixtures use (bootstrap seeds neutral defaults that don't include them)."""
    f = vault / "90-meta" / "routing.yaml"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("contexts:\n" + "\n".join(f"  - {c}" for c in ctxs))


def _write_audit(vault: Path, day: date, ctx_counts: dict[str, int]) -> None:
    f = vault / "90-meta" / "audit" / f"{day.isoformat()}.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("a", encoding="utf-8") as h:
        for ctx, n in ctx_counts.items():
            for _ in range(n):
                h.write(json.dumps({
                    "event_type": "event_processed", "status": "success",
                    "context": ctx, "source": "github",
                }) + "\n")


def _write_calendar_event(
    vault: Path, *, context: str, start: datetime, title: str = "Meeting",
) -> None:
    folder = vault / "20-contexts" / context / "calendar"
    folder.mkdir(parents=True, exist_ok=True)
    meta = {
        "id": title.lower().replace(" ", "-") + "-" + start.isoformat()[:10],
        "context": context, "type": "event", "source": "calendar",
        "start": start.isoformat(),
        "end": (start + timedelta(hours=1)).isoformat(),
        "isAllDay": False,
        "title": title, "created": start.isoformat(),
    }
    path = folder / f"{meta['id']}.md"
    path.write_text(
        f"---\n{yaml.safe_dump(meta).rstrip()}\n---\n\n# {title}\n",
        encoding="utf-8",
    )


def test_no_history_returns_empty(vault: Path) -> None:
    from ghostbrain.metrics.anticipation import detect_anticipations
    assert detect_anticipations(today=date(2026, 5, 8)) == []


def test_flags_context_with_history_but_no_today_activity(vault: Path) -> None:
    from ghostbrain.metrics.anticipation import detect_anticipations

    _configure(vault, ["sanlam", "codeship", "reducedrecipes", "personal"])
    today = date(2026, 5, 8)  # Friday
    # Build 4 prior Fridays with sanlam=10 each → median 10 ≥ floor.
    for weeks_back in range(1, 5):
        prior_friday = today - timedelta(weeks=weeks_back)
        _write_audit(vault, prior_friday, {"sanlam": 10})
    # Today is empty for sanlam.
    refs = detect_anticipations(today=today, lookback_days=30,
                                 activity_floor=3)
    contexts = [a.context for a in refs]
    assert "sanlam" in contexts


def test_does_not_flag_when_context_active_today(vault: Path) -> None:
    from ghostbrain.metrics.anticipation import detect_anticipations

    _configure(vault, ["sanlam", "codeship", "reducedrecipes", "personal"])
    today = date(2026, 5, 8)
    for weeks_back in range(1, 5):
        prior = today - timedelta(weeks=weeks_back)
        _write_audit(vault, prior, {"sanlam": 10})
    # Today HAS sanlam activity → should not flag.
    _write_audit(vault, today, {"sanlam": 4})

    refs = detect_anticipations(today=today, lookback_days=30,
                                 activity_floor=3)
    assert "sanlam" not in [a.context for a in refs]


def test_does_not_flag_when_calendar_has_event_today(vault: Path) -> None:
    from ghostbrain.metrics.anticipation import detect_anticipations

    _configure(vault, ["sanlam", "codeship", "reducedrecipes", "personal"])
    today = date(2026, 5, 8)
    for weeks_back in range(1, 5):
        prior = today - timedelta(weeks=weeks_back)
        _write_audit(vault, prior, {"sanlam": 10})
    # Today has a calendar event for sanlam.
    _write_calendar_event(
        vault, context="sanlam",
        start=datetime(2026, 5, 8, 9, 0, tzinfo=timezone.utc),
    )

    refs = detect_anticipations(today=today, lookback_days=30,
                                 activity_floor=3)
    assert "sanlam" not in [a.context for a in refs]


def test_below_activity_floor_not_flagged(vault: Path) -> None:
    """Contexts that only barely show on this weekday shouldn't flag."""
    from ghostbrain.metrics.anticipation import detect_anticipations

    _configure(vault, ["sanlam", "codeship", "reducedrecipes", "personal"])
    today = date(2026, 5, 8)
    # 1 event on each prior Friday → median 1 < default floor 3.
    for weeks_back in range(1, 5):
        _write_audit(vault, today - timedelta(weeks=weeks_back),
                      {"sanlam": 1})
    refs = detect_anticipations(today=today, lookback_days=30)
    assert refs == []


def test_only_known_contexts_evaluated(vault: Path) -> None:
    from ghostbrain.metrics.anticipation import detect_anticipations

    _configure(vault, ["sanlam", "codeship", "reducedrecipes", "personal"])
    today = date(2026, 5, 8)
    for weeks_back in range(1, 5):
        prior = today - timedelta(weeks=weeks_back)
        _write_audit(vault, prior, {"strange_ctx": 50})
    # Strange context should never appear in anticipations even if active.
    refs = detect_anticipations(today=today, lookback_days=30,
                                 activity_floor=3)
    assert all(a.context in ("sanlam", "codeship", "reducedrecipes",
                              "personal") for a in refs)
