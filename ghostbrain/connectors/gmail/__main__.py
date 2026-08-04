"""CLI runner for the Gmail connector.

Run via:
    python -m ghostbrain.connectors.gmail
or  ghostbrain-gmail-fetch

Reads accounts from ``vault/90-meta/routing.yaml:gmail.accounts``, runs
the connector against each, drops normalized thread events into the
queue's pending/. The always-on worker picks them up.
"""

from __future__ import annotations

import argparse
import logging

import yaml

from ghostbrain.connectors.gmail import GmailConnector
from ghostbrain.paths import queue_dir, state_dir, vault_path
from ghostbrain.worker.audit import audit_log

log = logging.getLogger("ghostbrain.connectors.gmail.main")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch Gmail threads into the queue.",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and normalize but don't enqueue.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    routing = _load_routing()
    gmail_cfg = routing.get("gmail") or {}
    accounts = gmail_cfg.get("accounts") or {}
    if not accounts:
        log.warning(
            "No gmail.accounts configured in routing.yaml; nothing to fetch.",
        )
        return

    queue = queue_dir()
    state = state_dir()
    queue.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)

    connector = GmailConnector(
        config={
            "accounts": accounts,
            "denylist_domains": gmail_cfg.get("denylist_domains") or [],
            "relevance_gate": gmail_cfg.get("relevance_gate", True),
            "relevance_model": gmail_cfg.get("relevance_model"),
        },
        queue_dir=queue,
        state_dir=state,
    )

    if not connector.health_check():
        audit_log("connector_health_failed", "gmail")
        log.error(
            "Gmail credentials missing or invalid for one or more accounts. "
            "Run `ghostbrain-gmail-auth <email>` to (re)authorize.",
        )
        return

    if args.dry_run:
        since = connector._get_last_run()
        events = connector.fetch(since)
        for ev in events:
            md = ev["metadata"]
            unread = "unread" if md.get("is_unread") else "read"
            print(
                f"{md['account']:30s} [{unread:>6s}] "
                f"{md['from_address']:40s} {ev['title']}"
            )
        print(f"\n{len(events)} event(s) (dry-run; not enqueued)")
        return

    count = connector.run()
    audit_log("connector_run", "gmail", events_queued=count)
    print(f"gmail: queued {count} event(s)")


def _load_routing() -> dict:
    f = vault_path() / "90-meta" / "routing.yaml"
    if not f.exists():
        return {}
    return yaml.safe_load(f.read_text(encoding="utf-8")) or {}


if __name__ == "__main__":
    main()
