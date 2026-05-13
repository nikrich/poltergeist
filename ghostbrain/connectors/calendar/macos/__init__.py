"""Apple Calendar (macOS) connector.

Reads events directly from ``Calendar.app`` via JXA (JavaScript for
Automation, ``osascript -l JavaScript``). No API tokens, no third-party
auth — Apple Calendar is already syncing whatever accounts the user
added in System Settings → Internet Accounts (iCloud, Google, Exchange).

This is the path that works for tenants like Sanlam where Microsoft
Graph delegated permission is admin-blocked: Calendar.app uses Apple's
sanctioned EAS/EWS connection, ghostbrain just reads the local cache.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ghostbrain.connectors._base import Connector
from ghostbrain.connectors.calendar._base import CalendarEvent

log = logging.getLogger("ghostbrain.connectors.calendar.macos")

DEFAULT_LOOKAHEAD_HOURS = 36
# Past events earlier today need to be captured too — the connector used to
# only look forward, so meetings already finished were never ingested.
DEFAULT_LOOKBACK_HOURS = 24
OSASCRIPT_TIMEOUT_S = 180  # AppleScript whose-predicate is slow for recurring events


def _fetch_via_eventkit(
    start: datetime, end: datetime, calendar_names: list[str],
) -> list[dict] | None:
    """Pull events via EventKit (PyObjC). Returns events in the JXA shape so the
    callsite can normalize uniformly. Returns None to signal "fall back to JXA"
    (PyObjC not installed, permission denied, etc).

    Why this exists: AppleScript's `cal.events.whose(startDate>X)` does NOT
    expand recurring events — it returns only the master record, whose
    startDate is the FIRST occurrence (often months/years ago). EventKit's
    predicate-based fetch expands recurrences natively.
    """
    try:
        from EventKit import EKEventStore
        from Foundation import NSDate
    except ImportError:
        return None

    store = EKEventStore.alloc().init()

    # Permission gate. On macOS 14+ use the new API; pre-14 falls back.
    granted = [None]
    def _cb(g, err):
        granted[0] = bool(g)
    try:
        store.requestFullAccessToEventsWithCompletion_(_cb)
    except AttributeError:
        from EventKit import EKEntityTypeEvent
        store.requestAccessToEntityType_completion_(EKEntityTypeEvent, _cb)

    # Spin the runloop briefly so the callback can fire. EventKit calls the
    # block on the main runloop — drain a few iterations to let it complete.
    import time
    from Foundation import NSRunLoop
    deadline = time.time() + 5.0
    while granted[0] is None and time.time() < deadline:
        NSRunLoop.currentRunLoop().runUntilDate_(
            NSDate.dateWithTimeIntervalSinceNow_(0.05)
        )

    if granted[0] is False:
        log.warning(
            "EventKit access denied. Open System Settings → Privacy & "
            "Security → Calendars and toggle access for the Python process. "
            "Falling back to JXA (recurring events will be missed)."
        )
        return None
    if granted[0] is None:
        # Authorization status fallback — older macOS sometimes returns access
        # without firing the callback in time.
        try:
            from EventKit import EKAuthorizationStatusAuthorized, EKEntityTypeEvent
            from EventKit import EKEventStore
            current = EKEventStore.authorizationStatusForEntityType_(EKEntityTypeEvent)
            if current != EKAuthorizationStatusAuthorized:
                log.warning(
                    "EventKit authorization unresolved (status=%s); falling back to JXA",
                    current,
                )
                return None
        except Exception:  # noqa: BLE001
            return None

    start_ns = NSDate.dateWithTimeIntervalSince1970_(start.timestamp())
    end_ns = NSDate.dateWithTimeIntervalSince1970_(end.timestamp())
    predicate = store.predicateForEventsWithStartDate_endDate_calendars_(
        start_ns, end_ns, None,  # None = all visible calendars
    )
    raw_events = store.eventsMatchingPredicate_(predicate) or []

    out: list[dict] = []
    name_set = set(calendar_names)
    for ev in raw_events:
        cal_name = str(ev.calendar().title())
        if cal_name not in name_set:
            continue
        start_dt = ev.startDate()
        end_dt = ev.endDate()
        # EventKit's external identifier is stable across syncs and unique per
        # recurring instance. eventIdentifier() differs between expansions and
        # the master record.
        ext_id = str(ev.calendarItemExternalIdentifier() or ev.eventIdentifier() or "")
        # For recurring instances, the external id is shared across occurrences,
        # so suffix with the start time to keep each instance distinct.
        uid = f"{ext_id}:{start_dt.timeIntervalSince1970():.0f}" if ext_id else ""
        out.append({
            "calendar": cal_name,
            "uid": uid,
            "summary": str(ev.title() or ""),
            "start": _iso(start_dt),
            "end": _iso(end_dt),
            "location": str(ev.location() or ""),
            "description": (str(ev.notes() or "") or "")[:5000],
            "allDay": bool(ev.isAllDay()),
            "url": str(ev.URL().absoluteString()) if ev.URL() else "",
        })
    return out


def _iso(nsdate) -> str:
    """NSDate → ISO 8601 UTC string with Z suffix to match JXA's toISOString()."""
    import datetime as _dt
    ts = nsdate.timeIntervalSince1970()
    return _dt.datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


JXA_SCRIPT = r"""
ObjC.import('Foundation');

function run(argv) {
    if (argv.length < 3) {
        return JSON.stringify({error: "usage: <startISO> <endISO> <calendarNameJSON>"});
    }
    var startIso = argv[0];
    var endIso = argv[1];
    var targetNames = JSON.parse(argv[2]);

    var startDate = new Date(startIso);
    var endDate = new Date(endIso);

    var Calendar = Application('Calendar');
    Calendar.includeStandardAdditions = true;

    var allCalendars = Calendar.calendars();
    var results = [];
    var errors = [];

    for (var i = 0; i < allCalendars.length; i++) {
        var cal = allCalendars[i];
        var calName;
        try {
            calName = cal.name();
        } catch (e) {
            continue;
        }
        if (targetNames.length > 0 && targetNames.indexOf(calName) === -1) {
            continue;
        }
        var events;
        try {
            events = cal.events.whose({_and: [
                {startDate: {_greaterThan: startDate}},
                {startDate: {_lessThan: endDate}},
            ]})();
        } catch (e) {
            errors.push({calendar: calName, error: String(e)});
            continue;
        }
        for (var j = 0; j < events.length; j++) {
            var ev = events[j];
            try {
                results.push({
                    calendar: calName,
                    uid: safeGet(ev, 'uid'),
                    summary: safeGet(ev, 'summary') || "",
                    start: isoOrNull(safeGet(ev, 'startDate')),
                    end: isoOrNull(safeGet(ev, 'endDate')),
                    location: safeGet(ev, 'location') || "",
                    description: (safeGet(ev, 'description') || "").substring(0, 5000),
                    allDay: !!safeGet(ev, 'alldayEvent'),
                    url: safeGet(ev, 'url') || "",
                });
            } catch (e) {
                // skip malformed events
            }
        }
    }

    return JSON.stringify({events: results, errors: errors});
}

function safeGet(obj, prop) {
    try {
        var fn = obj[prop];
        if (typeof fn === 'function') return fn();
        return fn;
    } catch (e) {
        return null;
    }
}

function isoOrNull(d) {
    if (!d) return null;
    try {
        return d.toISOString();
    } catch (e) {
        return null;
    }
}
"""


class MacosCalendarConnector(Connector):
    name = "macos_calendar"
    version = "1.0"

    def __init__(
        self,
        config: dict,
        queue_dir: Path,
        state_dir: Path,
    ) -> None:
        super().__init__(config, queue_dir, state_dir)
        # config["accounts"] is { calendar_name: context }.
        self.calendar_contexts: dict[str, str] = dict(config.get("accounts") or {})
        self.lookahead_hours = int(
            config.get("lookahead_hours") or DEFAULT_LOOKAHEAD_HOURS
        )
        self.lookback_hours = int(
            config.get("lookback_hours") or DEFAULT_LOOKBACK_HOURS
        )
        self._osascript = shutil.which("osascript") or "/usr/bin/osascript"

    def health_check(self) -> bool:
        if not self.calendar_contexts:
            return False
        # If osascript is callable AND Calendar.app responds with at least one
        # calendar, we're good.
        try:
            cmd = [
                self._osascript,
                "-e",
                'tell application "Calendar" to return count of calendars',
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            return proc.returncode == 0 and (proc.stdout or "").strip().isdigit()
        except Exception:  # noqa: BLE001
            return False

    def fetch(self, since: datetime) -> list[dict]:
        if not self.calendar_contexts:
            log.info("no macos calendars configured; skipping")
            return []

        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=self.lookback_hours)
        end = now + timedelta(hours=self.lookahead_hours)

        target_names = list(self.calendar_contexts.keys())

        # Try EventKit first — it expands recurring events, which AppleScript's
        # `whose` predicate does not. Fall back to JXA if EventKit isn't
        # installed (no PyObjC) or permission was denied.
        events_raw = _fetch_via_eventkit(start, end, target_names)
        source = "eventkit"
        if events_raw is None:
            source = "jxa"
            try:
                payload = self._run_jxa(start, end, target_names)
            except Exception as e:  # noqa: BLE001
                log.exception("macos calendar fetch failed: %s", e)
                return []
            events_raw = payload.get("events") or []
            for err in payload.get("errors") or []:
                log.warning("macos calendar fetch error for %s: %s",
                            err.get("calendar"), err.get("error"))

        events: list[dict] = []
        for raw in events_raw:
            ce = self._to_calendar_event(raw)
            if ce is not None:
                events.append(ce.to_event())

        log.info("macos calendar fetch (%s): %d event(s) across %d calendar(s)",
                 source, len(events), len(target_names))
        return events

    def normalize(self, raw: dict) -> dict:
        return raw

    # ------------------------------------------------------------------

    def _run_jxa(
        self,
        start: datetime,
        end: datetime,
        calendar_names: list[str],
    ) -> dict[str, Any]:
        cmd = [
            self._osascript,
            "-l", "JavaScript",
            "-e", JXA_SCRIPT,
            start.isoformat(),
            end.isoformat(),
            json.dumps(calendar_names),
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=OSASCRIPT_TIMEOUT_S,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"osascript exited {proc.returncode}: "
                f"{(proc.stderr or '').strip()[:300]}"
            )
        try:
            return json.loads(proc.stdout or "{}")
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"osascript stdout not JSON: {proc.stdout[:300]!r}"
            ) from e

    def _to_calendar_event(self, raw: dict) -> CalendarEvent | None:
        cal_name = raw.get("calendar") or ""
        if not cal_name:
            return None
        if cal_name not in self.calendar_contexts:
            return None
        start = raw.get("start") or ""
        if not start:
            return None
        end = raw.get("end") or start
        is_all_day = bool(raw.get("allDay"))

        # All-day events come back as midnight ISO strings; render as date-only
        # to match Google's all-day shape.
        if is_all_day and "T" in start:
            start = start.split("T", 1)[0]
            if end and "T" in end:
                end = end.split("T", 1)[0]

        return CalendarEvent(
            provider="macos",
            account=cal_name,
            event_id=str(raw.get("uid") or ""),
            title=str(raw.get("summary") or "(no title)"),
            start=start,
            end=end,
            is_all_day=is_all_day,
            location=str(raw.get("location") or ""),
            organizer="",  # JXA Calendar dictionary doesn't expose organizer well
            attendees=(),
            description=str(raw.get("description") or ""),
            url=str(raw.get("url") or ""),
            raw=raw,
        )
