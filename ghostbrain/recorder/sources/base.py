"""MeetingSource seam: normalized meeting events from any calendar system."""
from __future__ import annotations

import dataclasses
import logging
from datetime import datetime, timezone
from typing import Protocol

log = logging.getLogger("ghostbrain.recorder.sources")


@dataclasses.dataclass
class MeetingEvent:
    event_id: str
    title: str
    context: str
    start: datetime
    end: datetime


class MeetingSource(Protocol):
    id: str
    def events(self, now: datetime) -> list[MeetingEvent]: ...


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        if "T" in value:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def events_from_connector_dicts(
    raw: list[dict], account_contexts: dict[str, str],
) -> list[MeetingEvent]:
    """Parse `CalendarEvent.to_event()` dicts (SPEC §4.2) into MeetingEvents.
    Drops all-day/unparseable events and accounts with no context mapping."""
    out: list[MeetingEvent] = []
    for ev in raw:
        meta = ev.get("metadata") or {}
        if meta.get("isAllDay"):
            continue
        start_raw = str(meta.get("start") or "")
        end_raw = str(meta.get("end") or "")
        # Date-only values (no "T", e.g. "2026-08-24") are all-day events
        # that didn't carry an isAllDay flag — _parse_iso would otherwise
        # accept them as midnight UTC, putting them "in progress" for a
        # full 24h and triggering an unwanted recording.
        if "T" not in start_raw or "T" not in end_raw:
            continue
        start = _parse_iso(start_raw)
        end = _parse_iso(end_raw)
        if start is None or end is None:
            continue
        context = account_contexts.get(str(meta.get("account") or ""), "")
        if not context:
            continue
        out.append(MeetingEvent(
            event_id=str(ev.get("id") or ""),
            title=str(ev.get("title") or ""),
            context=context,
            start=start,
            end=end,
        ))
    return out
