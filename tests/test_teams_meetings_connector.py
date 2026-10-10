"""Tests for the Teams meetings connector. GraphClient is mocked."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest


def _conn(tmp_path: Path, client) -> "object":
    from ghostbrain.connectors.microsoft.teams_meetings.connector import (
        TeamsMeetingsConnector,
    )
    return TeamsMeetingsConnector(
        config={"calendar_lookback_days": 7, "body_cap_chars": 100},
        queue_dir=tmp_path / "q",
        state_dir=tmp_path / "s",
        client=client,
    )


def test_normalize_transcript_shape(tmp_path) -> None:
    from ghostbrain.connectors.microsoft.teams_meetings.connector import (
        _normalize_transcript,
    )
    event = _normalize_transcript(
        meeting={"id": "m1", "subject": "Standup",
                 "joinWebUrl": "https://teams/x",
                 "participants": {"organizer": {"upn": "a@b.com"}}},
        transcript={"id": "t1", "createdDateTime": "2026-06-04T09:00:00Z",
                    "endDateTime": "2026-06-04T09:30:00Z"},
        text="WEBVTT\n\nhello world",
        body_cap=100,
    )
    assert event["id"] == "microsoft:transcript:m1:t1"
    assert event["source"] == "teams_meetings"
    assert event["type"] == "meeting_transcript"
    assert event["title"] == "Standup"
    assert "hello world" in event["body"]
    assert event["metadata"]["meetingId"] == "m1"
    assert event["metadata"]["transcriptId"] == "t1"


def test_body_is_capped(tmp_path) -> None:
    from ghostbrain.connectors.microsoft.teams_meetings.connector import (
        _normalize_transcript,
    )
    event = _normalize_transcript(
        meeting={"id": "m", "subject": "S"},
        transcript={"id": "t", "createdDateTime": "2026-06-04T09:00:00Z"},
        text="x" * 5000,
        body_cap=100,
    )
    assert len(event["body"]) == 100


def test_fetch_emits_only_transcripts_newer_than_since(tmp_path) -> None:
    client = MagicMock()
    # One calendar event with an online meeting.
    client.get_all.side_effect = [
        # /me/calendarView
        [{"id": "e1", "isOnlineMeeting": True,
          "onlineMeeting": {"joinUrl": "https://teams/join1"}}],
    ]
    # resolve_meeting -> /me/onlineMeetings filter
    client.get.side_effect = [
        {"value": [{"id": "m1", "subject": "Sync", "joinWebUrl": "https://teams/join1"}]},
        # list transcripts
        {"value": [
            {"id": "old", "createdDateTime": "2026-06-01T09:00:00Z"},
            {"id": "boundary", "createdDateTime": "2026-06-03T00:00:00Z"},
            {"id": "new", "createdDateTime": "2026-06-04T09:00:00Z"},
        ]},
    ]
    conn = _conn(tmp_path, client)

    # Stub transcript text fetch so we don't need a real content call.
    conn._fetch_transcript_text = lambda client, mid, tid: "WEBVTT\n\nbody"

    since = datetime(2026, 6, 3, tzinfo=timezone.utc)
    events = conn.fetch(since)

    ids = [e["id"] for e in events]
    # "old" (before since) and "boundary" (== since, exclusive) both excluded.
    assert ids == ["microsoft:transcript:m1:new"]


def test_fetch_skips_meeting_when_resolve_finds_nothing(tmp_path) -> None:
    client = MagicMock()
    client.get_all.side_effect = [
        [{"id": "e1", "isOnlineMeeting": True,
          "onlineMeeting": {"joinUrl": "https://teams/join1"}}],
    ]
    # _resolve_meeting -> empty value -> ValueError -> logged + skipped
    client.get.side_effect = [{"value": []}]
    conn = _conn(tmp_path, client)
    events = conn.fetch(datetime(2026, 6, 3, tzinfo=timezone.utc))
    assert events == []


def test_fetch_uses_calendarview_with_date_range(tmp_path) -> None:
    client = MagicMock()
    client.get_all.side_effect = [[]]  # no events
    conn = _conn(tmp_path, client)
    conn.fetch(datetime(2026, 6, 3, tzinfo=timezone.utc))
    # Windowed event queries must use /me/calendarView with start/endDateTime,
    # not /me/events with a $filter (which live Graph rejects).
    path, params = client.get_all.call_args.args[0], client.get_all.call_args.args[1]
    assert path == "/me/calendarView"
    assert "startDateTime" in params and "endDateTime" in params
    assert "$filter" not in params


def test_resolve_meeting_ref_escapes_single_quotes(tmp_path) -> None:
    client = MagicMock()
    client.get.return_value = {"value": [{"id": "m1", "subject": "S"}]}
    conn = _conn(tmp_path, client)
    conn._resolve_meeting_ref(client, "https://teams/jo'in")
    sent = client.get.call_args.args[1]["$filter"]
    assert "jo''in" in sent  # single quote doubled for OData


def test_extract_meeting_id() -> None:
    from ghostbrain.connectors.microsoft.teams_meetings.connector import extract_meeting_id
    assert extract_meeting_id("https://teams.microsoft.com/meet/335252331326?p=x") == "335252331326"
    assert extract_meeting_id("335252331326") == "335252331326"
    assert extract_meeting_id(
        "https://teams.microsoft.com/l/meetup-join/19%3ameeting_abc%40thread.v2/0?context=y"
    ) is None


def test_fetch_uses_configured_meetings_without_touching_calendar(tmp_path) -> None:
    from ghostbrain.connectors.microsoft.teams_meetings.connector import (
        TeamsMeetingsConnector,
    )
    client = MagicMock()
    # resolve by meeting id -> /me/onlineMeetings, then its transcripts
    client.get.side_effect = [
        {"value": [{"id": "m1", "subject": "Standup", "joinWebUrl": "u"}]},
        {"value": [{"id": "new", "createdDateTime": "2026-06-04T09:00:00Z"}]},
    ]
    conn = TeamsMeetingsConnector(
        config={"meetings": ["335252331326"], "body_cap_chars": 100},
        queue_dir=tmp_path / "q",
        state_dir=tmp_path / "s",
        client=client,
    )
    conn._fetch_transcript_text = lambda client, mid, tid: "WEBVTT\n\nbody"
    events = conn.fetch(datetime(2026, 6, 3, tzinfo=timezone.utc))
    assert [e["id"] for e in events] == ["microsoft:transcript:m1:new"]
    # A configured list means NO calendar walk (works on transcripts-only scope).
    client.get_all.assert_not_called()
    # Resolution used the joinMeetingId filter, not JoinWebUrl.
    first_filter = client.get.call_args_list[0].args[1]["$filter"]
    assert "joinMeetingId" in first_filter and "335252331326" in first_filter


def test_health_check_false_without_token(tmp_path, monkeypatch) -> None:
    # Patch the symbol the connector module bound at import time.
    monkeypatch.setattr(
        "ghostbrain.connectors.microsoft.teams_meetings.connector.any_token",
        lambda cfg: False,
    )
    conn = _conn(tmp_path, MagicMock())
    assert conn.health_check() is False


def test_extract_join_urls() -> None:
    from ghostbrain.connectors.microsoft.teams_meetings.connector import extract_join_urls
    text = (
        "Join: <https://teams.microsoft.com/l/meetup-join/19%3ameeting_abc%40thread.v2/0"
        "?context=%7b%22Tid%22%3a%22t%22%7d>. Or dial https://teams.microsoft.com/meet/33525233?p=xyz, "
        "again https://teams.microsoft.com/meet/33525233?p=xyz."
    )
    urls = extract_join_urls(text)
    assert urls == [
        "https://teams.microsoft.com/l/meetup-join/19%3ameeting_abc%40thread.v2/0?context=%7b%22Tid%22%3a%22t%22%7d",
        "https://teams.microsoft.com/meet/33525233?p=xyz",
    ]
    assert extract_join_urls("no links here") == []


def test_macos_calendar_discovery_uses_local_events(tmp_path, monkeypatch) -> None:
    from ghostbrain.connectors.microsoft.teams_meetings import connector as mod

    class FakeCal:
        def __init__(self, config, queue_dir, state_dir):
            FakeCal.config = config
        def fetch(self, since):
            return [
                {"title": "Standup", "body": "", "metadata": {
                    "url": "", "location": "Microsoft Teams Meeting",
                    "description": "Join https://teams.microsoft.com/l/meetup-join/19%3ax%40thread.v2/0?context=c"}},
                {"title": "Lunch", "body": "", "metadata": {"url": "", "location": "Cafe", "description": ""}},
                {"title": "Dup", "body": "https://teams.microsoft.com/l/meetup-join/19%3ax%40thread.v2/0?context=c",
                 "metadata": {}},
            ]

    import ghostbrain.connectors.calendar.macos as calmod
    monkeypatch.setattr(calmod, "MacosCalendarConnector", FakeCal)

    client = MagicMock()
    conn = mod.TeamsMeetingsConnector(
        config={"discover_from": "macos_calendar", "calendar_lookback_days": 3,
                "macos_calendars": {"Calendar": "work"}},
        queue_dir=tmp_path / "q", state_dir=tmp_path / "s", client=client,
    )
    refs = conn._meeting_refs(client)
    assert refs == ["https://teams.microsoft.com/l/meetup-join/19%3ax%40thread.v2/0?context=c"]
    assert FakeCal.config["accounts"] == {"Calendar": "work"}
    assert FakeCal.config["lookback_hours"] == 72
    client.get_all.assert_not_called()  # Graph calendar never touched

    # No calendars configured → empty, with a warning rather than a crash.
    conn2 = mod.TeamsMeetingsConnector(
        config={"discover_from": "macos_calendar"}, queue_dir=tmp_path / "q",
        state_dir=tmp_path / "s", client=client,
    )
    assert conn2._meeting_refs(client) == []


def test_graph_calendar_403_explains_the_fix(tmp_path) -> None:
    import requests
    from ghostbrain.connectors.microsoft.graph.auth import MicrosoftAuthError
    client = MagicMock()
    resp = MagicMock(status_code=403)
    client.get_all.side_effect = requests.HTTPError("403 Client Error", response=resp)
    conn = _conn(tmp_path, client)
    with pytest.raises(MicrosoftAuthError, match="discover_from: macos_calendar"):
        conn._meeting_refs(client)
