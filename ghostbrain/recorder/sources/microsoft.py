"""Microsoft meeting source — Graph /me/calendarView via the shared graph
client. Spec correction (2026-08-24): there is no normalized MS calendar
connector to wrap, so this source calls Graph directly. Requires the
Calendars.Read delegated scope; without consent, get_token/get_all fail and
this source degrades to its cache (empty at startup) — visible in recorder
status, never a daemon crash."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from ghostbrain.connectors.microsoft.graph.auth import get_token
from ghostbrain.connectors.microsoft.graph.client import GraphClient
from ghostbrain.recorder.sources.base import MeetingEvent

log = logging.getLogger("ghostbrain.recorder.sources.microsoft")


class MicrosoftSource:
    id = "microsoft"

    def __init__(self, ms_config: dict, context: str, *, refresh_s: int = 300) -> None:
        self._config = dict(ms_config)
        self._context = context
        self._refresh_s = refresh_s
        self._cache: list[MeetingEvent] = []
        self._fetched_at: datetime | None = None

    def events(self, now: datetime) -> list[MeetingEvent]:
        if (self._fetched_at is not None
                and (now - self._fetched_at).total_seconds() < self._refresh_s):
            return self._cache
        try:
            client = GraphClient(get_token(self._config))
            raw = client.get_all("/me/calendarView", {
                "startDateTime": (now - timedelta(hours=1)).isoformat(),
                "endDateTime": (now + timedelta(hours=1)).isoformat(),
                "$select": "id,subject,start,end,isCancelled",
                "$top": 50,
            }, max_items=100)
        except Exception as e:  # noqa: BLE001
            log.warning("graph calendarView failed (%s); serving cached list", e)
            self._fetched_at = now
            return self._cache
        self._cache = [ev for ev in (self._map(item) for item in raw) if ev]
        self._fetched_at = now
        return self._cache

    def _map(self, item: dict) -> MeetingEvent | None:
        if item.get("isCancelled"):
            return None
        start = self._graph_dt(item.get("start") or {})
        end = self._graph_dt(item.get("end") or {})
        if start is None or end is None:
            return None
        return MeetingEvent(
            event_id=f"msgraph:{item.get('id', '')}",
            title=str(item.get("subject") or ""),
            context=self._context,
            start=start,
            end=end,
        )

    @staticmethod
    def _graph_dt(block: dict) -> datetime | None:
        raw, tz = str(block.get("dateTime") or ""), str(block.get("timeZone") or "UTC")
        if not raw:
            return None
        if "T" not in raw:
            # Date-only value (all-day event) — treat like base.py's
            # events_from_connector_dicts date-only guard: accepting it as
            # midnight UTC would put the event "in progress" for 24h.
            return None
        if tz != "UTC":
            log.warning("non-UTC calendarView timezone %r; skipping event", tz)
            return None
        raw = raw.split(".")[0]        # trim Graph's 7-digit fractional seconds
        try:
            return datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
        except ValueError:
            return None
