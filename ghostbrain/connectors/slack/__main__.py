"""CLI runner for the Slack connector.

Run via:
    python -m ghostbrain.connectors.slack
or  ghostbrain-slack-fetch

Reads workspaces from ``vault/90-meta/routing.yaml:slack.workspaces``,
runs the connector, drops normalized mention events into the queue's
pending/. The always-on worker picks them up.
"""

from __future__ import annotations

import argparse
import logging

import yaml

from ghostbrain.connectors.slack import SlackConnector
from ghostbrain.paths import queue_dir, state_dir, vault_path
from ghostbrain.worker.audit import audit_log

log = logging.getLogger("ghostbrain.connectors.slack.main")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch Slack mentions into the queue.",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and normalize but don't enqueue.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    routing = _load_routing()
    slack_cfg = routing.get("slack") or {}
    workspaces = slack_cfg.get("workspaces") or {}
    if not workspaces:
        log.warning(
            "No slack.workspaces configured in routing.yaml; nothing to fetch.",
        )
        return

    queue = queue_dir()
    state = state_dir()
    queue.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)

    connector = SlackConnector(
        config={"workspaces": workspaces},
        queue_dir=queue,
        state_dir=state,
    )

    if not connector.health_check():
        audit_log("connector_health_failed", "slack")
        log.error(
            "Slack token missing for one or more workspaces. Run "
            "`ghostbrain-slack-token-add <workspace> <xoxp-token>`.",
        )
        return

    if args.dry_run:
        since = connector._get_last_run()
        events = connector.fetch(since)
        for ev in events:
            md = ev["metadata"]
            channel = (
                f"DM/{md.get('user_name') or md.get('user_id') or '?'}"
                if md.get("is_dm") else f"#{md.get('channel_name') or '?'}"
            )
            print(
                f"{md['workspace_slug']:14s} {channel:30s} "
                f"@{md.get('user_name') or md.get('user_id') or '?':<20s} "
                f"{ev['title']}"
            )
        print(f"\n{len(events)} mention(s) (dry-run; not enqueued)")
        return

    count = connector.run()
    audit_log("connector_run", "slack", events_queued=count)
    print(f"slack: queued {count} event(s)")


def _load_routing() -> dict:
    f = vault_path() / "90-meta" / "routing.yaml"
    if not f.exists():
        return {}
    return yaml.safe_load(f.read_text(encoding="utf-8")) or {}


if __name__ == "__main__":
    main()
