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
