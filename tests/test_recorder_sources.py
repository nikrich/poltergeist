"""MeetingSource adapters: normalized-event parsing, caching, selection."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ghostbrain.recorder.sources.base import MeetingEvent, events_from_connector_dicts


def _raw(event_id="calendar:google:a@x.com:e1", account="a@x.com",
         start=None, end=None, title="standup"):
    now = datetime.now(timezone.utc)
    return {
        "id": event_id,
        "title": title,
        "metadata": {
            "account": account,
            "start": (start or now).isoformat(),
            "end": (end or now + timedelta(minutes=30)).isoformat(),
        },
    }


def test_parses_normalized_event():
    events = events_from_connector_dicts([_raw()], {"a@x.com": "work"})
    assert len(events) == 1
    ev = events[0]
    assert ev.context == "work"
    assert ev.event_id == "calendar:google:a@x.com:e1"
    assert ev.start.tzinfo is not None


def test_drops_unmapped_account():
    assert events_from_connector_dicts([_raw(account="other@x.com")], {"a@x.com": "work"}) == []


def test_drops_missing_times():
    raw = _raw()
    raw["metadata"]["start"] = ""
    assert events_from_connector_dicts([raw], {"a@x.com": "work"}) == []


def test_macos_source_wraps_connector(monkeypatch):
    from ghostbrain.recorder.sources.macos import MacosSource

    class FakeConnector:
        def __init__(self, config, queue_dir, state_dir):
            assert config["accounts"] == {"Work": "work"}
        def fetch(self, since):
            return [_raw(account="Work")]

    monkeypatch.setattr(
        "ghostbrain.recorder.sources.macos.MacosCalendarConnector", FakeConnector
    )
    src = MacosSource({"Work": "work"})
    events = src.events(datetime.now(timezone.utc))
    assert src.id == "macos"
    assert events[0].context == "work"
