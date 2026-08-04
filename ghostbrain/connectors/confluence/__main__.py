"""CLI runner for the Confluence connector.

Reads sites + spaces from vault/90-meta/routing.yaml. Sites are derived
from the keys of ``confluence.sites`` (or fall back to whatever sites the
Jira config knows about — Confluence and Jira share Atlassian sites).
"""

from __future__ import annotations

import argparse
import logging

import yaml

from ghostbrain.connectors.atlassian._base import AtlassianAuthError
from ghostbrain.connectors.confluence import ConfluenceConnector
from ghostbrain.paths import queue_dir, state_dir, vault_path
from ghostbrain.worker.audit import audit_log

log = logging.getLogger("ghostbrain.connectors.confluence.main")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Confluence pages into the queue.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and normalize but don't enqueue.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    routing = _load_routing()
    confluence_cfg = routing.get("confluence") or {}
    spaces = dict(confluence_cfg.get("spaces") or {})

    # Confluence sites can be configured explicitly, or default to whatever
    # Jira lists (same Atlassian sites, same auth).
    sites = list(confluence_cfg.get("sites") or
                 (routing.get("jira") or {}).get("sites") or [])

    if not sites or not spaces:
        log.warning("Configure confluence.sites and confluence.spaces in "
                    "routing.yaml; nothing to fetch.")
        return

    queue = queue_dir()
    state = state_dir()
    queue.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)

    connector = ConfluenceConnector(
        config={"sites": sites, "spaces": spaces},
        queue_dir=queue,
        state_dir=state,
    )

    try:
        if args.dry_run:
            since = connector._get_last_run()
            events = connector.fetch(since)
            for ev in events:
                meta = ev["metadata"]
                print(f"{meta['space']:8s} v{meta.get('version','?'):>3}  {ev['title']}")
            print(f"\n{len(events)} page(s) (dry-run; not enqueued)")
            return

        count = connector.run()
        audit_log("connector_run", "confluence", events_queued=count)
        print(f"confluence: queued {count} page(s)")
    except AtlassianAuthError as e:
        log.error(str(e))
        audit_log("connector_health_failed", "confluence", error=str(e))
        raise SystemExit(1)


def _load_routing() -> dict:
    f = vault_path() / "90-meta" / "routing.yaml"
    if not f.exists():
        return {}
    return yaml.safe_load(f.read_text(encoding="utf-8")) or {}


if __name__ == "__main__":
    main()
