"""CLI runner for calendar fetchers. Iterates configured providers in
``routing.yaml calendar.<provider>``, normalizes events, queues them.

Providers: ``google`` (OAuth) + ``macos`` (Apple Calendar via JXA).
"""

from __future__ import annotations

import argparse
import logging

import yaml

from ghostbrain.connectors._base import Connector
from ghostbrain.connectors.calendar.google import GoogleCalendarConnector
from ghostbrain.connectors.calendar.google.auth import GoogleAuthError
from ghostbrain.connectors.calendar.macos import MacosCalendarConnector
from ghostbrain.paths import queue_dir, state_dir, vault_path
from ghostbrain.worker.audit import audit_log

log = logging.getLogger("ghostbrain.connectors.calendar.main")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch calendar events into the queue.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and normalize but don't enqueue.")
    parser.add_argument("--provider", choices=("google", "macos"),
                        help="Run a single provider only (default: all configured).")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    routing = _load_routing()
    cal_cfg = (routing.get("calendar") or {})

    queue = queue_dir()
    state = state_dir()
    queue.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)

    providers: list[tuple[str, Connector]] = []

    google_cfg = cal_cfg.get("google") or {}
    google_accounts = dict(google_cfg.get("accounts") or {})
    if google_accounts and (args.provider in (None, "google")):
        providers.append(("google", GoogleCalendarConnector(
            config={
                "accounts": google_accounts,
                "calendars_per_account": google_cfg.get("calendars_per_account") or {},
            },
            queue_dir=queue,
            state_dir=state,
        )))

    macos_cfg = cal_cfg.get("macos") or {}
    macos_accounts = dict(macos_cfg.get("accounts") or {})
    if macos_accounts and (args.provider in (None, "macos")):
        providers.append(("macos", MacosCalendarConnector(
            config={"accounts": macos_accounts},
            queue_dir=queue,
            state_dir=state,
        )))

    if not providers:
        log.warning("No calendar providers configured in routing.yaml. Nothing to fetch.")
        return

    total_queued = 0
    for name, connector in providers:
        try:
            if args.dry_run:
                since = connector._get_last_run()
                events = connector.fetch(since)
                for ev in events:
                    meta = ev["metadata"]
                    marker = "[all-day]" if meta.get("isAllDay") else "[meeting]"
                    print(f"{marker} ({name}) {meta['account']:32s} "
                          f"{meta['start']:25s} {ev['title']}")
                print(f"  → {name}: {len(events)} event(s) (dry-run)")
                total_queued += len(events)
            else:
                count = connector.run()
                audit_log("connector_run", f"calendar.{name}", events_queued=count)
                print(f"calendar ({name}): queued {count} event(s)")
                total_queued += count
        except GoogleAuthError as e:
            log.error("google: %s", e)
            audit_log("connector_health_failed", "calendar.google", error=str(e))
        except Exception as e:  # noqa: BLE001
            log.exception("calendar %s failed: %s", name, e)
            audit_log("connector_health_failed", f"calendar.{name}", error=str(e))

    if args.dry_run:
        print(f"\nTotal: {total_queued} event(s) (dry-run; not enqueued)")


def _load_routing() -> dict:
    f = vault_path() / "90-meta" / "routing.yaml"
    if not f.exists():
        return {}
    return yaml.safe_load(f.read_text(encoding="utf-8")) or {}


if __name__ == "__main__":
    main()
