"""Google Calendar connector. Multi-account.

Auth flow: a single Google Cloud OAuth client (Desktop app) is used for
all accounts. Each account gets its own refresh token at
``~/.ghostbrain/state/google_calendar.<slug>.token``. The
``ghostbrain-calendar-auth google <email>`` CLI runs the one-time browser
consent flow per account.

Fetch: pulls events for today + tomorrow from each account's primary
calendar (or any calendar IDs listed in routing.yaml). Normalizes to the
provider-agnostic ``CalendarEvent`` shape, then to the SPEC §4.2 event.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ghostbrain.connectors._base import Connector
from ghostbrain.connectors.calendar._base import (
    CalendarEvent,
    event_id_slug,
)
from ghostbrain.connectors.calendar.google.auth import (
    GoogleAuthError,
    load_credentials,
)

log = logging.getLogger("ghostbrain.connectors.calendar.google")

DEFAULT_LOOKAHEAD_HOURS = 36  # today + tomorrow morning
SCOPES = ("https://www.googleapis.com/auth/calendar.readonly",)


class GoogleCalendarConnector(Connector):
    name = "google_calendar"
    version = "1.0"

    def __init__(
        self,
        config: dict,
        queue_dir: Path,
        state_dir: Path,
    ) -> None:
        super().__init__(config, queue_dir, state_dir)
        # config["accounts"] is { email: context, ... }
        self.account_contexts: dict[str, str] = dict(config.get("accounts") or {})
        # config["calendars_per_account"] is optional override:
        # { email: ["primary", "<calendar-id>", ...] }
        self.calendars_per_account: dict[str, list[str]] = dict(
            config.get("calendars_per_account") or {}
        )
        self.lookahead_hours = int(
            config.get("lookahead_hours") or DEFAULT_LOOKAHEAD_HOURS
        )

    def health_check(self) -> bool:
        if not self.account_contexts:
            return False
        try:
            for email in self.account_contexts:
                load_credentials(email)
        except GoogleAuthError:
            return False
        return True

    def fetch(self, since: datetime) -> list[dict]:
        if not self.account_contexts:
            log.info("no google accounts configured; skipping")
            return []

        events: list[dict] = []
        now = datetime.now(timezone.utc)
        time_min = now.isoformat()
        time_max = (now + timedelta(hours=self.lookahead_hours)).isoformat()

        for email in self.account_contexts:
            try:
                events.extend(
                    self._fetch_account(email, time_min, time_max)
                )
            except GoogleAuthError as e:
                log.warning("auth missing for %s: %s — run "
                            "ghostbrain-calendar-auth google %s",
                            email, e, email)
            except Exception as e:  # noqa: BLE001
                log.exception("google calendar fetch failed for %s: %s",
                              email, e)

        log.info("google calendar fetch: %d event(s) across %d account(s)",
                 len(events), len(self.account_contexts))
        return events

    def normalize(self, raw: dict) -> dict:
        return raw

    # ------------------------------------------------------------------
    # Per-account fetch
    # ------------------------------------------------------------------

    def _fetch_account(
        self,
        email: str,
        time_min: str,
        time_max: str,
    ) -> list[dict]:
        creds = load_credentials(email)
        # Lazy import — google libs are heavy and only this codepath needs them.
        from googleapiclient.discovery import build
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)

        calendar_ids = self.calendars_per_account.get(email) or ["primary"]

        events: list[dict] = []
        for cal_id in calendar_ids:
            try:
                resp = service.events().list(
                    calendarId=cal_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=50,
                ).execute()
            except Exception as e:  # noqa: BLE001
                log.warning("calendar %s on %s failed: %s", cal_id, email, e)
                continue

            for raw in resp.get("items", []) or []:
                ce = self._to_calendar_event(raw, account=email)
                if ce is not None:
                    events.append(ce.to_event())
        return events

    def _to_calendar_event(
        self,
        raw: dict,
        *,
        account: str,
    ) -> CalendarEvent | None:
        if raw.get("status") == "cancelled":
            return None

        start_obj = raw.get("start") or {}
        end_obj = raw.get("end") or {}

        is_all_day = "date" in start_obj
        if is_all_day:
            start = start_obj.get("date", "")
            end = end_obj.get("date", "")
        else:
            start = start_obj.get("dateTime", "")
            end = end_obj.get("dateTime", "")

        if not start:
            return None

        organizer = (raw.get("organizer") or {}).get("email", "") or ""
        attendees = tuple(
            a.get("email", "")
            for a in (raw.get("attendees") or [])
            if a.get("email")
        )

        return CalendarEvent(
            provider="google",
            account=account,
            event_id=str(raw.get("id") or ""),
            title=str(raw.get("summary") or "(no title)"),
            start=str(start),
            end=str(end),
            is_all_day=is_all_day,
            location=str(raw.get("location") or ""),
            organizer=organizer,
            attendees=attendees,
            description=str(raw.get("description") or "")[:5000],
            url=str(raw.get("htmlLink") or ""),
            raw=raw,
        )
