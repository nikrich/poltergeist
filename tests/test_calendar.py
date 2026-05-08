"""Tests for the Google calendar connector + digest integration.

Auth is mocked so no real tokens are touched.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


_RAW_TIMED_EVENT = {
    "id": "abc123",
    "status": "confirmed",
    "summary": "Standup",
    "description": "Daily standup with the team.",
    "location": "Online — Zoom",
    "htmlLink": "https://calendar.google.com/event?eid=...",
    "start": {"dateTime": "2026-05-09T10:00:00+02:00",
              "timeZone": "Africa/Johannesburg"},
    "end":   {"dateTime": "2026-05-09T10:30:00+02:00"},
    "organizer": {"email": "manager@codeship.app", "displayName": "Manager"},
    "attendees": [
        {"email": "jannik@codeship.app"},
        {"email": "alex@codeship.app"},
    ],
}

_RAW_ALL_DAY = {
    "id": "allday-1",
    "status": "confirmed",
    "summary": "Public holiday",
    "start": {"date": "2026-05-09"},
    "end":   {"date": "2026-05-10"},
}


def test_calendar_event_to_event_shape() -> None:
    from ghostbrain.connectors.calendar._base import CalendarEvent

    ce = CalendarEvent(
        provider="google", account="jannik@codeship.app",
        event_id="abc", title="Standup",
        start="2026-05-09T10:00:00+02:00",
        end="2026-05-09T10:30:00+02:00",
        is_all_day=False,
        location="Online — Zoom",
        organizer="manager@codeship.app",
        attendees=("jannik@codeship.app", "alex@codeship.app"),
    )
    ev = ce.to_event()

    assert ev["id"] == "calendar:google:jannik@codeship.app:abc"
    assert ev["source"] == "calendar"
    assert ev["type"] == "event"
    assert ev["subtype"] == "meeting"
    assert ev["title"] == "Standup"
    assert ev["metadata"]["account"] == "jannik@codeship.app"
    assert ev["metadata"]["isAllDay"] is False
    assert ev["metadata"]["start"] == "2026-05-09T10:00:00+02:00"
    assert "Online — Zoom" in ev["body"]


def test_all_day_event_marks_subtype(vault: Path) -> None:
    from ghostbrain.connectors.calendar._base import CalendarEvent

    ce = CalendarEvent(
        provider="google", account="x@y.com", event_id="i",
        title="Holiday",
        start="2026-05-09", end="2026-05-10",
        is_all_day=True,
    )
    ev = ce.to_event()
    assert ev["subtype"] == "all-day"
    assert "All day" in ev["body"]


def test_google_connector_fetches_with_mocked_service(vault: Path, tmp_path: Path) -> None:
    from ghostbrain.connectors.calendar.google import GoogleCalendarConnector

    connector = GoogleCalendarConnector(
        config={"accounts": {"jannik@codeship.app": "codeship"}},
        queue_dir=tmp_path / "q",
        state_dir=tmp_path / "s",
    )

    fake_events = MagicMock()
    fake_events.list().execute.return_value = {
        "items": [_RAW_TIMED_EVENT, _RAW_ALL_DAY],
    }
    fake_service = MagicMock()
    fake_service.events.return_value = fake_events

    with patch("ghostbrain.connectors.calendar.google.load_credentials",
               return_value=MagicMock()), \
         patch("googleapiclient.discovery.build", return_value=fake_service):
        events = connector.fetch(datetime(2026, 5, 9, tzinfo=timezone.utc))

    assert len(events) == 2
    types = {ev["subtype"] for ev in events}
    assert types == {"meeting", "all-day"}
    assert all(ev["source"] == "calendar" for ev in events)


def test_google_connector_skips_cancelled(vault: Path, tmp_path: Path) -> None:
    from ghostbrain.connectors.calendar.google import GoogleCalendarConnector
    connector = GoogleCalendarConnector(
        config={"accounts": {"a@b.com": "personal"}},
        queue_dir=tmp_path / "q", state_dir=tmp_path / "s",
    )
    cancelled = {**_RAW_TIMED_EVENT, "status": "cancelled"}
    ce = connector._to_calendar_event(cancelled, account="a@b.com")
    assert ce is None


def test_router_path_routes_calendar_event(vault: Path) -> None:
    from ghostbrain.worker.router import route_event

    routing = {
        "calendar": {
            "google": {
                "accounts": {
                    "jannik@codeship.app": "codeship",
                    "jannik811@gmail.com": "personal",
                },
            },
        },
    }
    event = {
        "id": "calendar:google:jannik@codeship.app:abc",
        "source": "calendar",
        "type": "event",
        "title": "Standup",
        "metadata": {
            "provider": "google",
            "account": "jannik@codeship.app",
        },
    }
    decision = route_event(event, routing=routing)
    assert decision.context == "codeship"
    assert decision.method == "path"


def test_digest_loads_today_calendar(vault: Path) -> None:
    """The digest loader scans 20-contexts/*/calendar/*.md and surfaces
    notes whose `start` frontmatter lands on the digest date."""
    import yaml
    from ghostbrain.worker.digest import build_digest_input

    cal_dir = vault / "20-contexts" / "codeship" / "calendar"
    cal_dir.mkdir(parents=True, exist_ok=True)
    note = (
        "---\n"
        + yaml.safe_dump({
            "id": "x",
            "type": "event",
            "context": "codeship",
            "source": "calendar",
            "title": "Standup",
            "start": "2026-05-09T10:00:00+02:00",
            "end":   "2026-05-09T10:30:00+02:00",
            "isAllDay": False,
            "location": "Zoom",
            "organizer": "manager@codeship.app",
            "provider": "google",
            "account": "jannik@codeship.app",
        }, sort_keys=False)
        + "---\n\n# Standup\n"
    )
    (cal_dir / "20260509T100000-standup.md").write_text(note)

    digest = build_digest_input(target_date=date(2026, 5, 9))
    assert len(digest.today_calendar) == 1
    item = digest.today_calendar[0]
    assert item.title == "Standup"
    assert item.context == "codeship"
    assert item.start.startswith("2026-05-09")


def test_digest_ignores_calendar_for_other_dates(vault: Path) -> None:
    import yaml
    from ghostbrain.worker.digest import build_digest_input

    cal_dir = vault / "20-contexts" / "codeship" / "calendar"
    cal_dir.mkdir(parents=True, exist_ok=True)
    note = (
        "---\n"
        + yaml.safe_dump({
            "id": "x", "type": "event", "context": "codeship",
            "source": "calendar", "title": "Tomorrow event",
            "start": "2026-05-10T10:00:00+02:00",
            "end": "2026-05-10T10:30:00+02:00",
            "isAllDay": False,
        }, sort_keys=False)
        + "---\n"
    )
    (cal_dir / "x.md").write_text(note)

    digest = build_digest_input(target_date=date(2026, 5, 9))
    assert digest.today_calendar == []
