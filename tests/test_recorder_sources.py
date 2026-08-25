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


def test_google_source_caches_for_refresh_window(monkeypatch):
    from ghostbrain.recorder.sources.google import GoogleSource

    calls = {"n": 0}

    class FakeConnector:
        def __init__(self, config, queue_dir, state_dir):
            pass
        def fetch(self, since):
            calls["n"] += 1
            return [_raw()]

    monkeypatch.setattr(
        "ghostbrain.recorder.sources.google.GoogleCalendarConnector", FakeConnector
    )
    src = GoogleSource({"a@x.com": "work"}, refresh_s=300)
    t0 = datetime.now(timezone.utc)
    assert len(src.events(t0)) == 1
    assert len(src.events(t0 + timedelta(seconds=200))) == 1
    assert calls["n"] == 1                                   # served from cache
    src.events(t0 + timedelta(seconds=301))
    assert calls["n"] == 2                                   # refreshed


def test_google_source_keeps_cache_on_fetch_error(monkeypatch):
    from ghostbrain.recorder.sources.google import GoogleSource

    class FlakyConnector:
        def __init__(self, config, queue_dir, state_dir):
            pass
        calls = 0
        def fetch(self, since):
            FlakyConnector.calls += 1
            if FlakyConnector.calls > 1:
                raise RuntimeError("token expired")
            return [_raw()]

    monkeypatch.setattr(
        "ghostbrain.recorder.sources.google.GoogleCalendarConnector", FlakyConnector
    )
    src = GoogleSource({"a@x.com": "work"}, refresh_s=0)
    t0 = datetime.now(timezone.utc)
    assert len(src.events(t0)) == 1
    assert len(src.events(t0 + timedelta(seconds=1))) == 1   # stale cache, not []
