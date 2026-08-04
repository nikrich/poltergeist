"""Tests for inverse search (unexpected references)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml


def _write_note(
    vault: Path, *, rel_path: str, context: str, body: str,
    actor: str = "", created: datetime | None = None,
    title: str = "Note",
) -> Path:
    created = created or datetime.now(timezone.utc)
    meta = {
        "id": rel_path.split("/")[-1].replace(".md", ""),
        "context": context,
        "type": "note",
        "source": "manual",
        "actorId": actor,
        "created": created.isoformat(),
        "title": title,
    }
    path = vault / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\n{yaml.safe_dump(meta).rstrip()}\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return path


def _write_config(vault: Path, body: dict) -> None:
    cfg = vault / "90-meta" / "config.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(yaml.safe_dump(body), encoding="utf-8")


def test_returns_empty_when_no_watched_names(vault: Path) -> None:
    from ghostbrain.metrics.inverse_search import find_unexpected_references
    _write_config(vault, {"inverse_search": {"watched_names": {}}})
    assert find_unexpected_references() == []


def test_finds_mention_in_body(vault: Path) -> None:
    from ghostbrain.metrics.inverse_search import find_unexpected_references

    _write_config(vault, {"inverse_search": {
        "watched_names": {"julia": ["Julia", "julia v"]},
        "lookback_days": 7,
    }})
    _write_note(
        vault, rel_path="20-contexts/work/confluence/page1.md",
        context="work",
        body="Julia approved the funding doc on Tuesday.",
        actor="confluence:other-user",
    )

    refs = find_unexpected_references()
    assert len(refs) == 1
    assert refs[0].name_key == "julia"
    assert refs[0].matched_phrase == "Julia"
    assert refs[0].note_context == "work"
    assert "Julia approved" in refs[0].excerpt


def test_skips_when_actor_is_the_watched_person(vault: Path) -> None:
    """If the watched person authored the note, don't surface it."""
    from ghostbrain.metrics.inverse_search import find_unexpected_references

    _write_config(vault, {"inverse_search": {
        "watched_names": {"sam": ["sam"]},
    }})
    _write_note(
        vault, rel_path="20-contexts/consulting/note.md",
        context="consulting",
        body="sam wrote this himself",
        actor="claude-code:sam",
    )
    assert find_unexpected_references() == []


def test_word_boundaries_dont_match_substrings(vault: Path) -> None:
    """'jul' should not match inside 'July' if it's a separate watched name."""
    from ghostbrain.metrics.inverse_search import find_unexpected_references

    _write_config(vault, {"inverse_search": {
        "watched_names": {"jul": ["jul"]},
    }})
    _write_note(
        vault, rel_path="20-contexts/personal/n.md",
        context="personal",
        body="meeting in July",
        actor="other",
    )
    assert find_unexpected_references() == []


def test_cross_context_flag_set(vault: Path) -> None:
    """When `expected_contexts` is configured, mentions outside it are flagged."""
    from ghostbrain.metrics.inverse_search import find_unexpected_references

    _write_config(vault, {"inverse_search": {
        "watched_names": {"julia": ["Julia"]},
        "expected_contexts": {"julia": ["work"]},
    }})
    _write_note(
        vault, rel_path="20-contexts/work/n.md",
        context="work", body="Julia signed off.", actor="other",
    )
    _write_note(
        vault, rel_path="20-contexts/consulting/n.md",
        context="consulting", body="Julia is also seen here.", actor="other",
    )

    refs = find_unexpected_references()
    by_ctx = {r.note_context: r for r in refs}
    assert by_ctx["work"].is_cross_context is False
    assert by_ctx["consulting"].is_cross_context is True


def test_lookback_filters_old_notes(vault: Path) -> None:
    from ghostbrain.metrics.inverse_search import find_unexpected_references

    _write_config(vault, {"inverse_search": {
        "watched_names": {"julia": ["Julia"]},
        "lookback_days": 3,
    }})
    _write_note(
        vault, rel_path="20-contexts/work/old.md",
        context="work", body="Julia stuff.", actor="other",
        created=datetime.now(timezone.utc) - timedelta(days=10),
    )
    _write_note(
        vault, rel_path="20-contexts/work/new.md",
        context="work", body="Julia stuff.", actor="other",
        created=datetime.now(timezone.utc),
    )

    refs = find_unexpected_references()
    paths = [r.note_path for r in refs]
    assert any("new.md" in p for p in paths)
    assert not any("old.md" in p for p in paths)


def test_case_insensitive(vault: Path) -> None:
    from ghostbrain.metrics.inverse_search import find_unexpected_references

    _write_config(vault, {"inverse_search": {
        "watched_names": {"julia": ["Julia"]},
    }})
    _write_note(
        vault, rel_path="20-contexts/work/n.md",
        context="work", body="JULIA in caps.", actor="other",
    )
    assert len(find_unexpected_references()) == 1
