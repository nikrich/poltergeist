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


def test_google_source_backs_off_after_fetch_error(monkeypatch):
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
    src = GoogleSource({"a@x.com": "work"}, refresh_s=300)
    t0 = datetime.now(timezone.utc)
    # First call: success, fetch count = 1, cache populated
    assert len(src.events(t0)) == 1
    assert FlakyConnector.calls == 1
    # Second call at t0+301s: fetch raises, fetch count = 2, returns stale cache
    src.events(t0 + timedelta(seconds=301))
    assert FlakyConnector.calls == 2                          # fetch attempted
    # Third call at t0+301s+10s: must NOT fetch (still within backoff window)
    assert len(src.events(t0 + timedelta(seconds=311))) == 1
    assert FlakyConnector.calls == 2                          # no new fetch
    # Fourth call at t0+301s+301s: backoff window expired, fetches again
    src.events(t0 + timedelta(seconds=602))
    assert FlakyConnector.calls == 3                          # fetch attempted again


def test_microsoft_source_maps_graph_events(monkeypatch):
    from ghostbrain.recorder.sources import microsoft as ms

    monkeypatch.setattr(ms, "get_token", lambda config: "tok")

    class FakeClient:
        def __init__(self, token):
            assert token == "tok"
        def get_all(self, path, params, max_items=100):
            assert path == "/me/calendarView"
            assert "startDateTime" in params and "endDateTime" in params
            return [{
                "id": "AAA",
                "subject": "access meeting",
                "start": {"dateTime": "2026-08-24T09:00:00.0000000", "timeZone": "UTC"},
                "end": {"dateTime": "2026-08-24T09:30:00.0000000", "timeZone": "UTC"},
            }]

    monkeypatch.setattr(ms, "GraphClient", FakeClient)
    src = ms.MicrosoftSource({"client_id": "x"}, "sanlam", refresh_s=300)
    events = src.events(datetime(2026, 8, 24, 9, 5, tzinfo=timezone.utc))
    assert src.id == "microsoft"
    assert len(events) == 1
    assert events[0].context == "sanlam"
    assert events[0].event_id == "msgraph:AAA"
    assert events[0].title == "access meeting"
    assert events[0].start == datetime(2026, 8, 24, 9, 0, tzinfo=timezone.utc)
    assert events[0].end == datetime(2026, 8, 24, 9, 30, tzinfo=timezone.utc)


def test_microsoft_source_skips_non_utc_events(monkeypatch, caplog):
    from ghostbrain.recorder.sources import microsoft as ms

    monkeypatch.setattr(ms, "get_token", lambda config: "tok")

    class FakeClient:
        def __init__(self, token): pass
        def get_all(self, path, params, max_items=100):
            return [
                {
                    "id": "UTC1", "subject": "utc meeting",
                    "start": {"dateTime": "2026-08-24T09:00:00.0000000", "timeZone": "UTC"},
                    "end": {"dateTime": "2026-08-24T09:30:00.0000000", "timeZone": "UTC"},
                },
                {
                    "id": "PST1", "subject": "pst meeting",
                    "start": {"dateTime": "2026-08-24T02:00:00.0000000", "timeZone": "Pacific Standard Time"},
                    "end": {"dateTime": "2026-08-24T02:30:00.0000000", "timeZone": "Pacific Standard Time"},
                },
            ]

    monkeypatch.setattr(ms, "GraphClient", FakeClient)
    src = ms.MicrosoftSource({}, "sanlam", refresh_s=300)
    with caplog.at_level("WARNING", logger="ghostbrain.recorder.sources.microsoft"):
        events = src.events(datetime(2026, 8, 24, 9, 5, tzinfo=timezone.utc))

    assert len(events) == 1
    assert events[0].event_id == "msgraph:UTC1"
    assert any("non-UTC" in r.message for r in caplog.records)


def test_microsoft_source_drops_events_without_times(monkeypatch):
    from ghostbrain.recorder.sources import microsoft as ms

    monkeypatch.setattr(ms, "get_token", lambda config: "tok")

    class FakeClient:
        def __init__(self, token): pass
        def get_all(self, path, params, max_items=100):
            return [
                {
                    "id": "NOSTART", "subject": "missing start block",
                    "end": {"dateTime": "2026-08-24T09:30:00.0000000", "timeZone": "UTC"},
                },
                {
                    "id": "EMPTYEND", "subject": "empty end block",
                    "start": {"dateTime": "2026-08-24T09:00:00.0000000", "timeZone": "UTC"},
                    "end": {},
                },
                {
                    "id": "EMPTYSTARTDT", "subject": "empty start dateTime",
                    "start": {"dateTime": "", "timeZone": "UTC"},
                    "end": {"dateTime": "2026-08-24T09:30:00.0000000", "timeZone": "UTC"},
                },
                {
                    "id": "OK", "subject": "well formed",
                    "start": {"dateTime": "2026-08-24T09:00:00.0000000", "timeZone": "UTC"},
                    "end": {"dateTime": "2026-08-24T09:30:00.0000000", "timeZone": "UTC"},
                },
            ]

    monkeypatch.setattr(ms, "GraphClient", FakeClient)
    src = ms.MicrosoftSource({}, "sanlam", refresh_s=300)
    events = src.events(datetime(2026, 8, 24, 9, 5, tzinfo=timezone.utc))
    assert [e.event_id for e in events] == ["msgraph:OK"]


def test_microsoft_source_serves_cache_on_auth_error(monkeypatch):
    from ghostbrain.recorder.sources import microsoft as ms

    calls = {"n": 0}
    def flaky_token(config):
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("consent revoked")
        return "tok"
    monkeypatch.setattr(ms, "get_token", flaky_token)

    class FakeClient:
        def __init__(self, token): pass
        def get_all(self, path, params, max_items=100):
            return [{
                "id": "AAA", "subject": "m",
                "start": {"dateTime": "2026-08-24T09:00:00", "timeZone": "UTC"},
                "end": {"dateTime": "2026-08-24T09:30:00", "timeZone": "UTC"},
            }]
    monkeypatch.setattr(ms, "GraphClient", FakeClient)

    src = ms.MicrosoftSource({}, "sanlam", refresh_s=300)
    t0 = datetime.now(timezone.utc)
    # First call: success, get_token count = 1, cache populated
    assert len(src.events(t0)) == 1
    assert calls["n"] == 1
    # Second call at t0+301s: get_token raises, count = 2, returns stale cache
    assert len(src.events(t0 + timedelta(seconds=301))) == 1
    assert calls["n"] == 2                                     # auth attempted
    # Third call at t0+301s+10s: must NOT attempt (still within backoff window)
    assert len(src.events(t0 + timedelta(seconds=311))) == 1
    assert calls["n"] == 2                                     # no new attempt
    # Fourth call at t0+301s+301s: backoff window expired, attempts again
    src.events(t0 + timedelta(seconds=602))
    assert calls["n"] == 3                                     # auth attempted again


def test_select_sources_from_configured_blocks():
    from ghostbrain.recorder.sources import select_sources
    routing = {
        "calendar": {"macos": {"accounts": {"Work": "w"}},
                     "google": {"accounts": {"a@x.com": "w"}}},
        "microsoft": {"client_id": "c", "calendar_context": "sanlam"},
    }
    sources, excluded = select_sources(routing, {}, platform="win32")
    ids = sorted(s.id for s in sources)
    assert ids == ["google", "microsoft"]          # macos excluded off-darwin
    assert any("macos" in r for r in excluded)

    sources, _ = select_sources(routing, {}, platform="darwin")
    assert sorted(s.id for s in sources) == ["google", "macos", "microsoft"]


def test_select_sources_microsoft_needs_context():
    from ghostbrain.recorder.sources import select_sources
    sources, excluded = select_sources({"microsoft": {"client_id": "c"}}, {}, platform="win32")
    assert sources == []
    assert any("calendar_context" in r for r in excluded)


def test_select_sources_override_pins_list():
    from ghostbrain.recorder.sources import select_sources
    routing = {"calendar": {"google": {"accounts": {"a@x.com": "w"}}},
               "microsoft": {"client_id": "c", "calendar_context": "s"}}
    sources, _ = select_sources(routing, {"meeting_sources": ["google"]}, platform="win32")
    assert [s.id for s in sources] == ["google"]


def test_dedupe_events_first_wins():
    from ghostbrain.recorder.sources import dedupe_events
    now = datetime.now(timezone.utc)
    a = MeetingEvent("e1", "from-google", "w", now, now + timedelta(minutes=30))
    b = MeetingEvent("e1", "from-elsewhere", "w", now, now + timedelta(minutes=30))
    assert [e.title for e in dedupe_events([a, b])] == ["from-google"]
