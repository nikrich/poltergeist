"""Find stale PRs, tickets, and pages by walking vault frontmatter.

"Stale" thresholds are tunable via ``config.yaml`` ``metrics`` block.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import frontmatter

from ghostbrain.paths import vault_path

DEFAULT_STALE_PR_DAYS = 3
DEFAULT_STALE_TICKET_DAYS = 7


@dataclasses.dataclass
class StaleItem:
    kind: str          # "pr" | "ticket"
    context: str
    title: str
    note_path: str
    age_days: float
    last_activity: str  # ISO
    state: str          # OPEN / In Progress / etc.
    extra: dict         # provider-specific fields (key, repo, number, assignee)


def find_stale_items(
    *,
    now: datetime | None = None,
    stale_pr_days: int = DEFAULT_STALE_PR_DAYS,
    stale_ticket_days: int = DEFAULT_STALE_TICKET_DAYS,
) -> list[StaleItem]:
    """Walk every ``20-contexts/*/`` and return items that haven't been
    updated within their freshness window."""
    now = now or datetime.now(timezone.utc)
    out: list[StaleItem] = []

    contexts_root = vault_path() / "20-contexts"
    if not contexts_root.exists():
        return out

    for ctx_dir in sorted(contexts_root.iterdir()):
        if not ctx_dir.is_dir():
            continue
        ctx = ctx_dir.name

        out.extend(_scan_prs(ctx_dir, ctx, now, stale_pr_days))
        out.extend(_scan_tickets(ctx_dir, ctx, now, stale_ticket_days))

    out.sort(key=lambda i: i.age_days, reverse=True)
    return out


def _scan_prs(
    ctx_dir: Path,
    ctx: str,
    now: datetime,
    stale_days: int,
) -> Iterable[StaleItem]:
    pr_dir = ctx_dir / "github" / "prs"
    if not pr_dir.exists():
        return
    for note in pr_dir.glob("*.md"):
        meta = _safe_load(note)
        if meta is None:
            continue
        if str(meta.get("state") or "").upper() in ("CLOSED", "MERGED"):
            continue

        last = _last_activity(meta)
        if last is None:
            continue
        age_days = (now - last).total_seconds() / 86400
        if age_days < stale_days:
            continue

        yield StaleItem(
            kind="pr",
            context=ctx,
            title=str(meta.get("title") or note.stem),
            note_path=str(note),
            age_days=round(age_days, 1),
            last_activity=last.isoformat(),
            state=str(meta.get("state") or "OPEN"),
            extra={
                "repo": str(meta.get("repo") or ""),
                "number": meta.get("number"),
                "author": (
                    (meta.get("rawData") or {}).get("author", {}) or {}
                ).get("login")
                or "",
            },
        )


def _scan_tickets(
    ctx_dir: Path,
    ctx: str,
    now: datetime,
    stale_days: int,
) -> Iterable[StaleItem]:
    tk_dir = ctx_dir / "jira" / "tickets"
    if not tk_dir.exists():
        return
    for note in tk_dir.glob("*.md"):
        meta = _safe_load(note)
        if meta is None:
            continue

        status = str(meta.get("status") or "").lower()
        # Skip terminal states.
        if status in ("done", "closed", "resolved", "cancelled"):
            continue

        last = _last_activity(meta)
        if last is None:
            continue
        age_days = (now - last).total_seconds() / 86400
        if age_days < stale_days:
            continue

        yield StaleItem(
            kind="ticket",
            context=ctx,
            title=str(meta.get("title") or note.stem),
            note_path=str(note),
            age_days=round(age_days, 1),
            last_activity=last.isoformat(),
            state=str(meta.get("status") or ""),
            extra={
                "key": str(meta.get("key") or ""),
                "project": str(meta.get("project") or ""),
                "assignee": ((meta.get("rawData") or {}).get("fields", {}) or {}).get(
                    "assignee", {}
                ).get("displayName") or "",
            },
        )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _safe_load(path: Path) -> dict | None:
    try:
        return frontmatter.load(path).metadata
    except Exception:  # noqa: BLE001
        return None


def _last_activity(meta: dict) -> datetime | None:
    """Pick the best signal of "last touched" from the frontmatter.

    Order: ``updated`` > ``ingestedAt`` > ``created``.
    """
    for key in ("updated", "ingestedAt", "created"):
        raw = meta.get(key)
        if not raw:
            continue
        dt = _parse_iso(str(raw))
        if dt is not None:
            return dt
    return None


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        if "T" in value:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
                timezone.utc
            )
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
