"""Meeting-prep builder.

Composes a prep payload for a single calendar event by reading its
calendar note, finding related items via the semantic index, and
asking ``claude -p`` for a short brief.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

from ghostbrain.paths import vault_path

log = logging.getLogger("ghostbrain.worker.meeting_prep")


def resolve_event_path(event_id: str) -> Path | None:
    """Find the calendar note that produced this event id.

    Agenda uses ``path.stem`` as the id, so we reverse-glob over all
    ``20-contexts/*/calendar/*.md`` files. Returns ``None`` if the event
    has been deleted from the vault.
    """
    vault = vault_path()
    if not vault.exists():
        return None
    target = f"{event_id}.md"
    for path in vault.glob("20-contexts/*/calendar/*.md"):
        if path.name == target:
            return path
    return None


def event_hash(fields: dict[str, Any]) -> str:
    """Stable hash over the cache-busting fields."""
    payload = "|".join(
        str(fields.get(k, "")) for k in ("start", "end", "description")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
