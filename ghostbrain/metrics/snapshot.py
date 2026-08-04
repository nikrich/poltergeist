"""Top-level metrics snapshot. Produces a markdown summary written to
``vault/50-team/velocity/<date>.md``."""

from __future__ import annotations

import dataclasses
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ghostbrain.metrics.checkins import CheckinSuggestion, suggest_checkins
from ghostbrain.metrics.staleness import StaleItem, find_stale_items
from ghostbrain.paths import vault_path


@dataclasses.dataclass
class Snapshot:
    generated_at: datetime
    stale_prs: list[StaleItem]
    stale_tickets: list[StaleItem]
    checkins: list[CheckinSuggestion]


def build_snapshot(now: datetime | None = None) -> Snapshot:
    now = now or datetime.now(timezone.utc)
    stale = find_stale_items(now=now)
    return Snapshot(
        generated_at=now,
        stale_prs=[i for i in stale if i.kind == "pr"],
        stale_tickets=[i for i in stale if i.kind == "ticket"],
        checkins=suggest_checkins(now=now),
    )


def write_snapshot(snap: Snapshot, target_date: date | None = None) -> Path:
    target_date = target_date or snap.generated_at.date()
    out_dir = vault_path() / "50-team" / "velocity"
    out_dir.mkdir(parents=True, exist_ok=True)

    front: dict[str, Any] = {
        "id": f"velocity-{target_date.isoformat()}",
        "type": "velocity-snapshot",
        "context": "cross",
        "source": "metrics",
        "created": snap.generated_at.isoformat(),
        "date": target_date.isoformat(),
        "stalePRCount": len(snap.stale_prs),
        "staleTicketCount": len(snap.stale_tickets),
        "checkinCount": len(snap.checkins),
    }
    yaml_block = yaml.safe_dump(front, sort_keys=False, allow_unicode=True).rstrip()

    body = render_markdown(snap)
    path = out_dir / f"{target_date.isoformat()}.md"
    path.write_text(f"---\n{yaml_block}\n---\n\n{body}", encoding="utf-8")
    return path


def render_markdown(snap: Snapshot) -> str:
    parts: list[str] = []
    parts.append(f"# Velocity snapshot — {snap.generated_at.date().isoformat()}")
    parts.append("")

    parts.append("## Check-ins suggested")
    parts.append("")
    if snap.checkins:
        for s in snap.checkins:
            parts.append(f"- worth a check-in with **{s.person}** because {s.reason}")
    else:
        parts.append("_No check-ins flagged this week._")
    parts.append("")

    parts.append("## Stale PRs")
    parts.append("")
    if snap.stale_prs:
        for item in snap.stale_prs:
            parts.append(
                f"- {item.title} "
                f"({item.context}, {item.age_days} days, {item.state})"
            )
    else:
        parts.append("_No stale PRs._")
    parts.append("")

    parts.append("## Stale tickets")
    parts.append("")
    if snap.stale_tickets:
        for item in snap.stale_tickets:
            parts.append(
                f"- {item.title} "
                f"({item.context}, {item.age_days} days, status: {item.state})"
            )
    else:
        parts.append("_No stale tickets._")
    parts.append("")

    parts.append("---")
    parts.append("")
    parts.append("_Cycle time / weekly trends will surface once ≥ 2 weeks of "
                 "snapshots accumulate._")
    return "\n".join(parts)
