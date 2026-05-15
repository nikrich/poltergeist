"""CLI runner for the Joplin connector.

Run via:
    python -m ghostbrain.connectors.joplin
or  ghostbrain-joplin-fetch

Reads `joplin.token` (and optional `joplin.host` / `joplin.notebooks`)
from vault/90-meta/routing.yaml. The always-on worker picks the queued
events up.
"""

from __future__ import annotations

import argparse
import logging

import yaml

from ghostbrain.connectors.joplin import JoplinConnector
from ghostbrain.paths import queue_dir, state_dir, vault_path
from ghostbrain.worker.audit import audit_log

log = logging.getLogger("ghostbrain.connectors.joplin.main")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Joplin notes into the queue.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and normalize but don't enqueue.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    routing = _load_routing()
    joplin_cfg = routing.get("joplin") or {}
    if not joplin_cfg.get("token"):
        log.warning("joplin.token not set in routing.yaml; nothing to fetch.")
        return

    queue = queue_dir()
    state = state_dir()
    queue.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)

    connector = JoplinConnector(
        config=joplin_cfg,
        queue_dir=queue,
        state_dir=state,
    )

    if not connector.health_check():
        audit_log("connector_health_failed", "joplin")
        log.error(
            "joplin /ping failed. Is Joplin running with Web Clipper "
            "service enabled at %s?", connector.host,
        )
        return

    if args.dry_run:
        since = connector._get_last_run()
        events = connector.fetch(since)
        for ev in events:
            meta = ev.get("metadata") or {}
            print(f"{ev['subtype']:>9s}  [{meta.get('notebook', '?'):>16s}]  "
                  f"{ev['title']}")
        print(f"\n{len(events)} note(s) (dry-run; not enqueued)")
        return

    count = connector.run()
    audit_log("connector_run", "joplin", events_queued=count)
    print(f"joplin: queued {count} event(s)")


def _load_routing() -> dict:
    f = vault_path() / "90-meta" / "routing.yaml"
    if not f.exists():
        return {}
    return yaml.safe_load(f.read_text(encoding="utf-8")) or {}


if __name__ == "__main__":
    main()
