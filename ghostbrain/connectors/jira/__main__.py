"""CLI runner for the Jira connector.

Run via:
    python -m ghostbrain.connectors.jira
or  ghostbrain-jira-fetch [--dry-run]

Reads sites from vault/90-meta/routing.yaml jira.sites.
"""

from __future__ import annotations

import argparse
import logging

import yaml

from ghostbrain.connectors.atlassian._base import AtlassianAuthError
from ghostbrain.connectors.jira import JiraConnector
from ghostbrain.paths import queue_dir, state_dir, vault_path
from ghostbrain.worker.audit import audit_log

log = logging.getLogger("ghostbrain.connectors.jira.main")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Jira tickets into the queue.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and normalize but don't enqueue.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    routing = _load_routing()
    sites = list((routing.get("jira") or {}).get("sites") or {})
    if not sites:
        log.warning("No jira.sites configured in routing.yaml; nothing to fetch.")
        return

    queue = queue_dir()
    state = state_dir()
    queue.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)

    connector = JiraConnector(
        config={"sites": sites},
        queue_dir=queue,
        state_dir=state,
    )

    try:
        if args.dry_run:
            since = connector._get_last_run()
            events = connector.fetch(since)
            for ev in events:
                meta = ev["metadata"]
                print(f"{meta['key']:14s} [{meta['status']:>14s}] "
                      f"{ev['title']}")
            print(f"\n{len(events)} event(s) (dry-run; not enqueued)")
            return

        count = connector.run()
        audit_log("connector_run", "jira", events_queued=count)
        print(f"jira: queued {count} event(s)")
    except AtlassianAuthError as e:
        log.error(str(e))
        audit_log("connector_health_failed", "jira", error=str(e))
        raise SystemExit(1)


def _load_routing() -> dict:
    f = vault_path() / "90-meta" / "routing.yaml"
    if not f.exists():
        return {}
    return yaml.safe_load(f.read_text(encoding="utf-8")) or {}


if __name__ == "__main__":
    main()
