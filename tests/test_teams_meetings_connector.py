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
        "ghostbrain.connectors.microsoft.teams_meetings.connector.have_token",
        lambda cfg: False,
    )
    conn = _conn(tmp_path, MagicMock())
    assert conn.health_check() is False
