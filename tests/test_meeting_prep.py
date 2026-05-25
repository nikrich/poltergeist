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


import textwrap
from pathlib import Path

import pytest

from ghostbrain.worker import meeting_prep as mp


@pytest.fixture()
def vault(tmp_path, monkeypatch):
    """Create a fake vault with one calendar event note and one prior meeting."""
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    cal = tmp_path / "20-contexts" / "sanlam" / "calendar"
    cal.mkdir(parents=True)
    (cal / "20260525T090000-eng-standup.md").write_text(textwrap.dedent("""\
        ---
        title: Eng standup
        start: 2026-05-25T09:00:00+02:00
        end: 2026-05-25T09:30:00+02:00
        with:
          - alice@example.com
          - bob@example.com
        location: Zoom
        description: weekly sync — sprint plan
        ---
        """))
    return tmp_path


def test_resolve_event_path_finds_note(vault):
    path = mp.resolve_event_path("20260525T090000-eng-standup")
    assert path is not None
    assert path.name == "20260525T090000-eng-standup.md"


def test_resolve_event_path_missing_returns_none(vault):
    assert mp.resolve_event_path("does-not-exist") is None


def test_event_hash_changes_when_description_changes(vault):
    h1 = mp.event_hash({"start": "x", "end": "y", "description": "v1"})
    h2 = mp.event_hash({"start": "x", "end": "y", "description": "v2"})
    h3 = mp.event_hash({"start": "x", "end": "y", "description": "v1"})
    assert h1 != h2
    assert h1 == h3


from unittest.mock import MagicMock


def test_build_prep_happy_path(vault, monkeypatch):
    """build_prep loads event, queries semantic index, calls LLM, returns Prep."""
    # Mock semantic search to return one related item.
    fake_search = MagicMock(return_value={
        "query": "Eng standup",
        "total": 1,
        "items": [{
            "path": "20-contexts/sanlam/meetings/2026-05-18-eng-standup.md",
            "title": "Eng standup 2026-05-18",
            "snippet": "agreed to spike auth",
            "score": 0.82,
        }],
    })
    monkeypatch.setattr(mp, "_semantic_search", fake_search)

    # Mock the LLM to return a fixed brief.
    fake_llm = MagicMock()
    fake_llm.return_value = MagicMock(text="Continuing the auth spike.")
    monkeypatch.setattr(mp, "_llm_run", fake_llm)

    prep = mp.build_prep("20260525T090000-eng-standup")

    assert prep.event_id == "20260525T090000-eng-standup"
    assert prep.brief == "Continuing the auth spike."
    assert prep.error is None
    assert len(prep.related) == 1
    assert prep.related[0].title == "Eng standup 2026-05-18"
    assert prep.event_snapshot.title == "Eng standup"
    assert prep.event_snapshot.with_ == ["alice@example.com", "bob@example.com"]
    # The brief was generated, so the LLM was called exactly once.
    assert fake_llm.call_count == 1
    # Two queries to the semantic index (title-based and attendee-based).
    assert fake_search.call_count >= 1


def test_build_prep_unknown_event_raises(vault, monkeypatch):
    with pytest.raises(mp.UnknownEvent):
        mp.build_prep("not-a-real-id")


from ghostbrain.llm.client import LLMTimeout


def test_build_prep_llm_timeout_returns_prep_with_error(vault, monkeypatch):
    monkeypatch.setattr(mp, "_semantic_search", MagicMock(return_value={"items": []}))
    monkeypatch.setattr(
        mp,
        "_llm_run",
        MagicMock(side_effect=LLMTimeout("claude -p timed out after 30s")),
    )

    prep = mp.build_prep("20260525T090000-eng-standup")
    assert prep.brief is None
    assert prep.error is not None
    assert "Timeout" in prep.error
    assert prep.event_snapshot.title == "Eng standup"  # snapshot still built
    assert prep.related == []


import json

from ghostbrain.api.repo import meeting_prep as repo


def test_cache_write_then_read(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path))
    snap = EventSnapshot(
        title="t", start="s", end="e", with_=[], location="", description="", hash="h1",
    )
    p = Prep(
        event_id="evt1", brief="hi", related=[], event_snapshot=snap,
        generated_at="2026-05-25T00:00:00+00:00", error=None,
    )
    repo.set_prep(p)
    got = repo.get_prep("evt1", expected_hash="h1")
    assert got is not None
    assert got.brief == "hi"


def test_cache_returns_none_when_hash_mismatches(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path))
    snap = EventSnapshot(
        title="t", start="s", end="e", with_=[], location="", description="", hash="oldhash",
    )
    repo.set_prep(Prep(
        event_id="evt1", brief="hi", related=[], event_snapshot=snap,
        generated_at="2026-05-25T00:00:00+00:00", error=None,
    ))
    # Same event_id, but the live event's fields produce a different hash.
    assert repo.get_prep("evt1", expected_hash="newhash") is None


def test_cache_returns_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path))
    assert repo.get_prep("never-written", expected_hash="x") is None
