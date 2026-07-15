"""Anticipation prompts — surface "you usually work on X today, but
calendar/activity has nothing for X" nudges in the daily digest.

Builds a (weekday, context) histogram from the last N days of audit
events, then compares today's expected pattern against:
- Today's calendar events (per context)
- Today's actually-processed events so far (per context)

If a context is typically active on this weekday but today shows
nothing, emit an ``Anticipation`` row. The daily digest renders these
under "Anticipated" so the user can decide whether to block time.

The detection is intentionally simple: median > activity_floor for the
weekday vs. today's count = 0. We don't predict workload — we just
flag conspicuous absences.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Iterable

import frontmatter

from ghostbrain import routing_config
from ghostbrain.paths import audit_dir, vault_path

log = logging.getLogger("ghostbrain.metrics.anticipation")

DEFAULT_LOOKBACK_DAYS = 30
DEFAULT_ACTIVITY_FLOOR = 3   # context must avg ≥3 events on this weekday


@dataclasses.dataclass
class Anticipation:
    """One nudge: 'context X is usually active on <weekday> but today
    has nothing.'"""

    context: str
    weekday: str           # "Monday"
    typical_count: float   # median events on this weekday in the lookback
    today_count: int       # events captured so far today
    today_calendar: int    # calendar events for this context today
    reason: str


def detect_anticipations(
    *,
    today: date | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    activity_floor: int = DEFAULT_ACTIVITY_FLOOR,
) -> list[Anticipation]:
    """Compare today's per-context activity against the weekday's typical
    activity over the past ``lookback_days``."""
    today = today or _local_today()
    weekday_name = today.strftime("%A")

    known = routing_config.contexts()

    # For each (weekday, context) collect daily counts over the lookback.
    by_weekday_ctx: dict[tuple[int, str], list[int]] = defaultdict(list)
    cur = today - timedelta(days=lookback_days)
    while cur < today:
        per_ctx = _events_per_context_for_day(cur)
        for ctx in known:
            by_weekday_ctx[(cur.weekday(), ctx)].append(per_ctx.get(ctx, 0))
        cur += timedelta(days=1)

    today_per_ctx = _events_per_context_for_day(today)
    today_calendar = _calendar_events_per_context_for_day(today)

    out: list[Anticipation] = []
    for ctx in known:
        counts = by_weekday_ctx.get((today.weekday(), ctx), [])
        if not counts:
            continue
        typical = median(counts)
        if typical < activity_floor:
            continue
        today_count = today_per_ctx.get(ctx, 0)
        cal_today = today_calendar.get(ctx, 0)
        if today_count > 0 or cal_today > 0:
            # Activity already happening today → no anticipation needed.
            continue
        reason = (
            f"{ctx} usually has ~{typical:.0f} events on {weekday_name}s "
            f"(over the last {lookback_days} days) but today shows none."
        )
        out.append(Anticipation(
            context=ctx,
            weekday=weekday_name,
            typical_count=typical,
            today_count=today_count,
            today_calendar=cal_today,
            reason=reason,
        ))
    out.sort(key=lambda a: -a.typical_count)
    return out


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _events_per_context_for_day(day: date) -> dict[str, int]:
    """Tally event_processed audit events per context for a single day."""
    f = audit_dir() / f"{day.isoformat()}.jsonl"
    if not f.exists():
        return {}
    counts: dict[str, int] = defaultdict(int)
    with f.open("r", encoding="utf-8") as h:
        for line in h:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("event_type") != "event_processed":
                continue
            if e.get("status") != "success":
                continue
            ctx = str(e.get("context") or "")
            if not ctx:
                continue
            counts[ctx] += 1
    return dict(counts)


def _calendar_events_per_context_for_day(day: date) -> dict[str, int]:
    """Walk vault/20-contexts/<ctx>/calendar/*.md and count events on day."""
    contexts_root = vault_path() / "20-contexts"
    if not contexts_root.exists():
        return {}
    counts: dict[str, int] = defaultdict(int)
    today_str = day.isoformat()
    for ctx_dir in sorted(contexts_root.iterdir()):
        if not ctx_dir.is_dir():
            continue
        cal_dir = ctx_dir / "calendar"
        if not cal_dir.exists():
            continue
        for path in cal_dir.glob("*.md"):
            try:
                note = frontmatter.load(path)
            except Exception:  # noqa: BLE001
                continue
            start = str(note.metadata.get("start") or "")
            if start.startswith(today_str):
                counts[ctx_dir.name] += 1
    return dict(counts)


def _local_today() -> date:
    return datetime.now().date()
