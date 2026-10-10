"""What a note *is*, for graph colouring: one of NOTE_KINDS.

Derived from frontmatter ``artifactType``, ``type``, ``source`` and the path.
Order matters: a decision extracted from a manual jot is a decision, not a jot.
"""
from __future__ import annotations

from ghostbrain.vault_index.links import PEOPLE_DIR
from ghostbrain.vault_index.parse import NoteEntry

NOTE_KINDS: tuple[str, ...] = (
    "person", "meeting", "decision", "action", "ticket", "doc", "jot", "note",
)
MANUAL_INBOX = "00-inbox/raw/manual/"
_MEETING_TYPES = frozenset({"event", "meeting", "meeting_transcript"})
_TICKET_TYPES = frozenset({"ticket", "issue", "pr"})
_DOC_TYPES = frozenset({"page", "doc"})


def _low(value: str | None) -> str:
    return (value or "").strip().lower()


def note_kind(entry: NoteEntry) -> str:
    artifact, typ, source = _low(entry.artifact_type), _low(entry.type), _low(entry.source)
    if entry.path.startswith(PEOPLE_DIR + "/"):
        return "person"
    if artifact == "decision":
        return "decision"
    if artifact in ("action_item", "action"):
        return "action"
    if artifact == "transcript" or typ in _MEETING_TYPES:
        return "meeting"
    if typ in _TICKET_TYPES:
        return "ticket"
    if typ in _DOC_TYPES or artifact == "spec":
        return "doc"
    if entry.path.startswith(MANUAL_INBOX) or source == "manual":
        return "jot"
    return "note"
