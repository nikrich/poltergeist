"""Google Calendar meeting source — cached; remote API polled at most every
`refresh_s` while the daemon evaluates eligibility every tick."""
from __future__ import annotations

import logging
from datetime import datetime

from ghostbrain.connectors.calendar.google import GoogleCalendarConnector
from ghostbrain.paths import queue_dir, state_dir
from ghostbrain.recorder.sources.base import MeetingEvent, events_from_connector_dicts

log = logging.getLogger("ghostbrain.recorder.sources.google")


class GoogleSource:
    id = "google"

    def __init__(self, accounts: dict[str, str], *, refresh_s: int = 300) -> None:
        self._accounts = dict(accounts)
        self._refresh_s = refresh_s
        self._cache: list[MeetingEvent] = []
        self._fetched_at: datetime | None = None

    def events(self, now: datetime) -> list[MeetingEvent]:
        if (self._fetched_at is not None
                and (now - self._fetched_at).total_seconds() < self._refresh_s):
            return self._cache
        connector = GoogleCalendarConnector(
            config={"accounts": self._accounts, "lookahead_hours": 1},
            queue_dir=queue_dir(),
            state_dir=state_dir(),
        )
        try:
            raw = connector.fetch(now)
        except Exception as e:  # noqa: BLE001
            log.warning("google calendar fetch failed (%s); serving cached list", e)
            self._fetched_at = now      # back off a full window, don't hammer
            return self._cache
        self._cache = events_from_connector_dicts(raw, self._accounts)
        self._fetched_at = now
        return self._cache
