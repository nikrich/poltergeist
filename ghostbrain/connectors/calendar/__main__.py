"""CLI runner for calendar fetchers. Iterates configured providers in
``routing.yaml calendar.<provider>``, normalizes events, queues them.

Today only Google is implemented; the dispatcher is shaped so other
providers (ICS, Microsoft Graph) slot in without touching this module.
"""

from __future__ import annotations

import argparse
import logging

import yaml

from ghostbrain.connectors.calendar.google import GoogleCalendarConnector
from ghostbrain.connectors.calendar.google.auth import GoogleAuthError
from ghostbrain.paths import queue_dir, state_dir, vault_path
from ghostbrain.worker.audit import audit_log

log = logging.getLogger("ghostbrain.connectors.calendar.main")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch calendar events into the queue.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and normalize but don't enqueue.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    routing = _load_routing()
    cal_cfg = (routing.get("calendar") or {})
    google_cfg = cal_cfg.get("google") or {}
    accounts = dict(google_cfg.get("accounts") or {})

    if not accounts:
        log.warning("No calendar.google.accounts configured in routing.yaml. "
                    "Nothing to fetch.")
        return

    queue = queue_dir()
    state = state_dir()
    queue.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)

    connector = GoogleCalendarConnector(
        config={
            "accounts": accounts,
            "calendars_per_account": google_cfg.get("calendars_per_account") or {},
        },
        queue_dir=queue,
        state_dir=state,
    )

    try:
        if args.dry_run:
            since = connector._get_last_run()
            events = connector.fetch(since)
            for ev in events:
                meta = ev["metadata"]
                marker = "[all-day]" if meta["isAllDay"] else "[meeting]"
                print(f"{marker} {meta['account']:32s} {meta['start']:25s} "
                      f"{ev['title']}")
            print(f"\n{len(events)} event(s) (dry-run; not enqueued)")
            return

        count = connector.run()
        audit_log("connector_run", "calendar.google", events_queued=count)
        print(f"calendar (google): queued {count} event(s)")
    except GoogleAuthError as e:
        log.error(str(e))
        audit_log("connector_health_failed", "calendar.google", error=str(e))
        raise SystemExit(1)


def _load_routing() -> dict:
    f = vault_path() / "90-meta" / "routing.yaml"
    if not f.exists():
        return {}
    return yaml.safe_load(f.read_text(encoding="utf-8")) or {}


if __name__ == "__main__":
    main()
