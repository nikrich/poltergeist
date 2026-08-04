"""``ghostbrain-metrics`` — write a velocity snapshot to vault/50-team/velocity/."""

from __future__ import annotations

import argparse
import logging
from datetime import date

from ghostbrain.metrics.snapshot import build_snapshot, write_snapshot
from ghostbrain.worker.audit import audit_log


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a velocity snapshot.")
    parser.add_argument("--date", help="Target date (YYYY-MM-DD). Default: today.")
    parser.add_argument("--print-only", action="store_true",
                        help="Print to stdout instead of writing to the vault.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    snap = build_snapshot()

    if args.print_only:
        from ghostbrain.metrics.snapshot import render_markdown
        print(render_markdown(snap))
        return

    target = date.fromisoformat(args.date) if args.date else None
    out = write_snapshot(snap, target_date=target)
    audit_log(
        "metrics_snapshot",
        snap.generated_at.date().isoformat(),
        path=str(out),
        stale_prs=len(snap.stale_prs),
        stale_tickets=len(snap.stale_tickets),
        checkins=len(snap.checkins),
    )
    print(f"Wrote {out}")
    print(f"  stale PRs:     {len(snap.stale_prs)}")
    print(f"  stale tickets: {len(snap.stale_tickets)}")
    print(f"  check-ins:     {len(snap.checkins)}")


if __name__ == "__main__":
    main()
