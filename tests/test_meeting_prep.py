"""Tests for the meeting-prep models, builder, and cache repo."""
from __future__ import annotations

from ghostbrain.api.models.meeting import EventSnapshot, Prep, RelatedItem


def test_prep_model_round_trips():
    snap = EventSnapshot(
        title="Eng standup",
        start="2026-05-25T09:00:00+02:00",
        end="2026-05-25T09:30:00+02:00",
        with_=["alice@example.com", "bob@example.com"],
        location="Zoom",
        description="weekly sync",
        hash="abc123",
    )
    rel = RelatedItem(
        path="20-contexts/sanlam/meetings/2026-05-18-eng-standup.md",
        title="Eng standup 2026-05-18",
        source="meeting",
        snippet="discussed sprint plan",
        score=0.81,
    )
    prep = Prep(
        event_id="20260525T090000-eng-standup",
        brief="Continuing last week's sprint plan thread.",
        related=[rel],
        event_snapshot=snap,
        generated_at="2026-05-25T08:55:00+02:00",
        error=None,
    )
    dumped = prep.model_dump(by_alias=True)
    assert dumped["eventId"] == "20260525T090000-eng-standup"
    assert dumped["related"][0]["path"].endswith("-eng-standup.md")
    assert dumped["eventSnapshot"]["with"] == ["alice@example.com", "bob@example.com"]
    assert dumped["generatedAt"] == "2026-05-25T08:55:00+02:00"
