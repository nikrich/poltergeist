"""Shared types for calendar connectors. The provider connectors emit
``CalendarEvent`` instances; the runner normalizes them to the standard
event shape (SPEC §4.2)."""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from typing import Any


@dataclasses.dataclass
class CalendarEvent:
    """Provider-agnostic calendar event payload.

    All-day events use ``"YYYY-MM-DD"`` strings for ``start``/``end``;
    timed events use ISO8601 with offset (``"2026-05-09T10:00:00+02:00"``).
    """

    provider: str               # "google" | "ics" | "microsoft"
    account: str                # email or ICS URL slug — identifies which feed
    event_id: str               # provider-side unique id
    title: str
    start: str                  # ISO8601 or YYYY-MM-DD
    end: str
    is_all_day: bool
    location: str = ""
    organizer: str = ""
    attendees: tuple[str, ...] = ()
    description: str = ""
    url: str = ""
    raw: dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_event(self) -> dict[str, Any]:
        """Render to the SPEC §4.2 event shape."""
        return {
            "id": f"calendar:{self.provider}:{self.account}:{self.event_id}",
            "source": "calendar",
            "type": "event",
            "subtype": "all-day" if self.is_all_day else "meeting",
            "timestamp": self.start,
            "actorId": f"calendar:{self.organizer}" if self.organizer else "calendar:?",
            "title": self.title,
            "body": self._render_body(),
            "url": self.url,
            "rawData": self.raw,
            "metadata": {
                "provider": self.provider,
                "account": self.account,
                "eventId": self.event_id,
                "start": self.start,
                "end": self.end,
                "isAllDay": self.is_all_day,
                "location": self.location,
                "organizer": self.organizer,
                "attendees": list(self.attendees),
            },
        }

    def _render_body(self) -> str:
        lines: list[str] = []
        when = (
            f"All day {self.start}"
            if self.is_all_day
            else f"{self.start} → {self.end}"
        )
        lines.append(f"**When:** {when}")
        if self.location:
            lines.append(f"**Where:** {self.location}")
        if self.organizer:
            lines.append(f"**Organizer:** {self.organizer}")
        if self.attendees:
            shown = ", ".join(self.attendees[:8])
            extra = f" (+{len(self.attendees) - 8} more)" if len(self.attendees) > 8 else ""
            lines.append(f"**Attendees:** {shown}{extra}")
        if self.description:
            lines.append("")
            lines.append(self.description.strip())
        return "\n".join(lines)


def event_id_slug(account: str) -> str:
    """Filename-safe slug derived from an email or feed url."""
    return (
        account.lower()
        .replace("@", "_at_")
        .replace(".", "_")
        .replace("/", "_")
        .replace(":", "_")
    )


def parse_iso(value: str) -> datetime | None:
    """Parse Google/ISO datetime strings, including all-day ``YYYY-MM-DD``.

    Returns timezone-aware datetime when possible; for all-day events
    returns the local-naive midnight of that date.
    """
    if not value:
        return None
    try:
        if "T" in value:
            # google's ISO uses 'Z' for UTC; fromisoformat in 3.11 handles it.
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return datetime.fromisoformat(value).replace(tzinfo=None)
    except ValueError:
        return None
