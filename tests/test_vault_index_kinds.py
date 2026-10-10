"""Graph node kind derived from frontmatter and path."""
from __future__ import annotations

import pytest

from ghostbrain.vault_index.kinds import NOTE_KINDS, note_kind
from ghostbrain.vault_index.parse import parse_note


def _kind(rel: str, frontmatter: str = "") -> str:
    text = f"---\n{frontmatter}---\nbody" if frontmatter else "body"
    return note_kind(parse_note(rel, text, mtime_ns=1, size=1))


def test_note_kinds_are_the_spec_list():
    assert NOTE_KINDS == ("person", "meeting", "decision", "action", "ticket", "doc", "jot", "note")


@pytest.mark.parametrize(
    ("rel", "frontmatter", "expected"),
    [
        ("30-cross-context/people/alex.md", "", "person"),
        ("20-contexts/work/decisions/d.md", "type: artifact\nartifactType: decision\nsource: manual\n", "decision"),
        ("20-contexts/work/actions/a.md", "type: artifact\nartifactType: action_item\n", "action"),
        ("20-contexts/work/calendar/transcripts/t.md", "type: artifact\nartifactType: transcript\n", "meeting"),
        ("20-contexts/work/calendar/e.md", "type: event\n", "meeting"),
        ("20-contexts/work/teams/m.md", "type: meeting_transcript\n", "meeting"),
        ("20-contexts/work/jira/T-1.md", "type: ticket\n", "ticket"),
        ("20-contexts/work/github/pr-1.md", "type: PR\n", "ticket"),
        ("20-contexts/work/confluence/p.md", "type: page\n", "doc"),
        ("20-contexts/work/specs/s.md", "type: artifact\nartifactType: spec\n", "doc"),
        ("00-inbox/raw/manual/manual-1.md", "", "jot"),
        ("20-contexts/work/notes/manual-2.md", "source: manual\n", "jot"),
        ("10-daily/2026-10-09.md", "", "note"),
        ("20-contexts/work/gmail/t.md", "type: email_thread\n", "note"),
    ],
)
def test_note_kind(rel: str, frontmatter: str, expected: str):
    assert _kind(rel, frontmatter) == expected
