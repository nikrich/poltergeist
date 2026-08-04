"""CLI runner for the GitHub connector.

Run via:
    python -m ghostbrain.connectors.github
or  ghostbrain-github-fetch

Reads orgs from vault/90-meta/routing.yaml github.orgs, runs the connector,
drops normalized events into the queue's pending/. The always-on worker
picks them up.
"""

from __future__ import annotations

import argparse
import logging

import yaml

from ghostbrain.connectors.github import GitHubConnector
from ghostbrain.paths import queue_dir, state_dir, vault_path
from ghostbrain.worker.audit import audit_log

log = logging.getLogger("ghostbrain.connectors.github.main")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch GitHub PRs/issues into the queue.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and normalize but don't enqueue.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    routing = _load_routing()
    orgs = list((routing.get("github") or {}).get("orgs") or {})
    if not orgs:
        log.warning("No github.orgs configured in routing.yaml; nothing to fetch.")
        return

    queue = queue_dir()
    state = state_dir()
    queue.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)

    connector = GitHubConnector(
        config={"orgs": orgs},
        queue_dir=queue,
        state_dir=state,
    )

    if not connector.health_check():
        audit_log("connector_health_failed", "github")
        log.error("gh auth status failed; run `gh auth login`.")
        return

    if args.dry_run:
        since = connector._get_last_run()
        events = connector.fetch(since)
        for ev in events:
            print(f"{ev['type']:6s} {ev['metadata']['repo']}#{ev['metadata']['number']:5d} "
                  f"[{ev['subtype']:>16s}] {ev['title']}")
        print(f"\n{len(events)} event(s) (dry-run; not enqueued)")
        return

    count = connector.run()
    audit_log("connector_run", "github", events_queued=count)
    print(f"github: queued {count} event(s)")


def _load_routing() -> dict:
    f = vault_path() / "90-meta" / "routing.yaml"
    if not f.exists():
        return {}
    return yaml.safe_load(f.read_text(encoding="utf-8")) or {}


if __name__ == "__main__":
    main()
