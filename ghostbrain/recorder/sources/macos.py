"""Apple Calendar meeting source — per-tick query (local, cheap)."""
from __future__ import annotations

import logging
from datetime import datetime

from ghostbrain.connectors.calendar.macos import MacosCalendarConnector
from ghostbrain.paths import queue_dir, state_dir
from ghostbrain.recorder.sources.base import MeetingEvent, events_from_connector_dicts

log = logging.getLogger("ghostbrain.recorder.sources.macos")


class MacosSource:
    id = "macos"

    def __init__(self, accounts: dict[str, str]) -> None:
        self._accounts = dict(accounts)

    def events(self, now: datetime) -> list[MeetingEvent]:
        connector = MacosCalendarConnector(
            config={"accounts": self._accounts, "lookahead_hours": 1},
            queue_dir=queue_dir(),
            state_dir=state_dir(),
        )
        try:
            raw = connector.fetch(now)
        except Exception as e:  # noqa: BLE001
            log.warning("macos calendar query failed: %s", e)
            return []
        return events_from_connector_dicts(raw, self._accounts)
