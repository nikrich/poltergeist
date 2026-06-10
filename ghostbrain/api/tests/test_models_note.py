"""Schema contract for the note model used by the jot endpoints."""
import pytest
from pydantic import ValidationError

from ghostbrain.api.models.note import Note, NoteListItem, NotesPage


def test_note_accepts_jot_frontmatter():
    note = Note(
        path="20-contexts/sanlam/notes/manual-20260514T093015-x.md",
        title="ghostbrain idea",
        body="thoughts about the ascp wizard flow",
        frontmatter={
            "id": "manual-20260514T093015-x",
            "type": "note",
            "source": "manual",
            "context": "sanlam",
            "routingStatus": "routed",
            "routingMethod": "llm",
            "routingConfidence": 0.82,
            "tags": ["idea", "ui"],
        },
    )
    assert note.frontmatter["routingStatus"] == "routed"


def test_note_list_item_shape():
    item = NoteListItem(
        id="manual-20260514T093015-x",
        path="20-contexts/sanlam/notes/manual-20260514T093015-x.md",
        title="ghostbrain idea",
        excerpt="thoughts about the…",
        context="sanlam",
        routingStatus="routed",
        tags=["idea"],
        created="2026-05-14T09:30:15+02:00",
        updated="2026-05-14T09:30:15+02:00",
    )
    assert item.routingStatus == "routed"


def test_notes_page_shape():
    page = NotesPage(items=[], total=0)
    assert page.total == 0


def test_note_list_item_rejects_unknown_routing_status_and_accepts_null_context():
    kwargs = dict(
        id="manual-20260514T093015-x",
        path="00-inbox/manual-20260514T093015-x.md",
        title="ghostbrain idea",
        excerpt="thoughts about the…",
        tags=[],
        created="2026-05-14T09:30:15+02:00",
        updated="2026-05-14T09:30:15+02:00",
    )
    with pytest.raises(ValidationError):
        NoteListItem(context="sanlam", routingStatus="unknown", **kwargs)
    item = NoteListItem(context=None, routingStatus="pending", **kwargs)
    assert item.context is None
