"""CLI runner for the Slack connector.

Run via::

    python -m ghostbrain.connectors.slack
    ghostbrain-slack-fetch

Reads workspaces from ``vault/90-meta/routing.yaml:slack.workspaces``,
runs the connector, and drops normalized events into the queue's
pending/. The always-on worker picks them up.

Dry-run preview for full-pull mode::

    python -m ghostbrain.connectors.slack --dry-run --mode full --days 1

This pulls 1 day of history from every channel without saving cursors
and without enqueueing, then prints the LLM's keep/skip decision per
message so you can eyeball quality before flipping ``mode: full`` in
``routing.yaml``.
"""

from __future__ import annotations

import argparse
import logging
from collections import defaultdict

import yaml

from ghostbrain.connectors.slack import SlackConnector
from ghostbrain.connectors.slack.connector import MessageDecision
from ghostbrain.paths import queue_dir, state_dir, vault_path
from ghostbrain.worker.audit import audit_log

log = logging.getLogger("ghostbrain.connectors.slack.main")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch Slack messages into the queue.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Fetch and classify but don't enqueue or advance cursors.",
    )
    parser.add_argument(
        "--mode", choices=("mentions", "full"),
        help="Override mode in routing.yaml. Useful with --dry-run to "
             "preview full-pull before flipping the config.",
    )
    parser.add_argument(
        "--days", type=int,
        help="Override initial_lookback_days (full-pull only).",
    )
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

    # Apply CLI overrides per workspace before constructing the connector.
    if args.mode or args.days is not None:
        workspaces = {
            slug: _override(cfg or {}, mode=args.mode, days=args.days)
            for slug, cfg in workspaces.items()
        }

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
        _run_dry(connector)
        return

    count = connector.run()
    audit_log("connector_run", "slack", events_queued=count)
    print(f"slack: queued {count} event(s)")


def _override(cfg: dict, *, mode: str | None, days: int | None) -> dict:
    new = dict(cfg)
    if mode:
        new["mode"] = mode
    if days is not None:
        new["initial_lookback_days"] = days
    return new


def _run_dry(connector: SlackConnector) -> None:
    """Execute the fetch in preview mode and print per-message decisions.

    Full-pull workspaces emit a :class:`MessageDecision` for every
    message considered. Mentions-mode workspaces don't have a
    keep/skip step (search.messages is already filtered) — for those
    we just print the resulting events.
    """
    decisions_by_ws: dict[str, list[MessageDecision]] = {}
    events: list[dict] = []
    from datetime import datetime, timezone
    since = datetime.now(timezone.utc)

    for ws in connector.workspaces:
        try:
            if ws.mode == "full":
                collector: list[MessageDecision] = []
                evs = connector._fetch_workspace_full(
                    ws, dry_run_collector=collector,
                )
                decisions_by_ws[ws.slug] = collector
                events.extend(evs)
            else:
                events.extend(connector._fetch_workspace(ws))
        except Exception as e:  # noqa: BLE001
            log.warning("slack dry-run: %s failed: %s", ws.slug, e)

    for slug, decisions in decisions_by_ws.items():
        _print_decisions(slug, decisions)

    # Mentions-mode workspaces produce events directly (no keep/skip step).
    mentions_events = [
        e for e in events
        if e.get("metadata", {}).get("keep_reason") is None
    ]
    if mentions_events:
        print(f"\n--- {len(mentions_events)} mention event(s) (mentions mode) ---")
        for ev in mentions_events:
            md = ev["metadata"]
            channel = (
                f"DM/{md.get('user_name') or md.get('user_id') or '?'}"
                if md.get("is_dm")
                else f"#{md.get('channel_name') or '?'}"
            )
            print(f"  {channel:30s} {ev['title']}")

    print(f"\nDRY-RUN: {len(events)} event(s) would be enqueued. "
          f"Cursors NOT advanced. Re-run drops to write mode.")


def _print_decisions(workspace: str, decisions: list[MessageDecision]) -> None:
    """Group decisions by channel; show kept/skipped counts + samples."""
    by_chan: dict[str, list[MessageDecision]] = defaultdict(list)
    for d in decisions:
        by_chan[d.channel].append(d)

    print(f"\n=== workspace {workspace} ===")
    total_kept = sum(1 for d in decisions if d.kept)
    print(f"{len(decisions)} message(s) considered, {total_kept} kept")
    for chan in sorted(by_chan):
        items = by_chan[chan]
        kept = sum(1 for d in items if d.kept)
        print(f"\n  #{chan} — {kept}/{len(items)} kept")
        # Show every kept; sample 3 skipped so user can see what the gate
        # rejected without drowning in deploy/CI noise.
        kept_items = [d for d in items if d.kept]
        skipped_items = [d for d in items if not d.kept][:3]
        for d in kept_items:
            score = f" (score={d.score})" if d.score is not None else ""
            print(f"    ✓ {d.reason}{score}: {_short(d.msg.get('text', ''))}")
        for d in skipped_items:
            score = f" (score={d.score})" if d.score is not None else ""
            print(f"    ✗ {d.reason}{score}: {_short(d.msg.get('text', ''))}")
        if len(items) - len(kept_items) > 3:
            print(f"    … {len(items) - len(kept_items) - 3} more skipped")


def _short(text: str, limit: int = 100) -> str:
    t = (text or "").replace("\n", " ").strip()
    return t if len(t) <= limit else t[: limit - 1] + "…"


def _load_routing() -> dict:
    f = vault_path() / "90-meta" / "routing.yaml"
    if not f.exists():
        return {}
    return yaml.safe_load(f.read_text(encoding="utf-8")) or {}


if __name__ == "__main__":
    main()
