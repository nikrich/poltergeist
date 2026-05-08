"""Weekly digest generator. See SPEC §13 (pyramid synthesis).

Where the daily digest answers "what happened yesterday", the weekly
answers "what's drifting, what's recurring, what needs unblocking" —
patterns that only appear when you look at a 7-day window.

Reads:
- The past 7 days of daily digests (``10-daily/YYYY-MM-DD.md``).
- Transcript-derived artifacts (decisions, action items, unresolved,
  specs) under ``20-contexts/<ctx>/calendar/artifacts/<type>/``.
- Check-in suggestions + stale items from the metrics layer.
- Audit log totals (event volume by source).

Writes ``vault/10-daily/weekly/YYYY-Www.md`` (ISO week numbering).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import frontmatter
import yaml

from ghostbrain.llm import client as llm
from ghostbrain.paths import audit_dir, vault_path
from ghostbrain.worker.audit import audit_log
from ghostbrain.worker.digest import (
    _shorten_for_display,
    _wikilink_for_path,
)

log = logging.getLogger("ghostbrain.worker.weekly_digest")

KNOWN_CONTEXTS: tuple[str, ...] = (
    "sanlam", "codeship", "reducedrecipes", "personal", "needs_review",
)

# Threshold below which a context is flagged as "quiet" — fewer than
# this many events across the entire week.
QUIET_THRESHOLD = 2


@dataclasses.dataclass
class WeeklyArtifact:
    """One transcript-derived artifact carried through the weekly."""

    context: str
    artifact_type: str       # decision | action_item | unresolved | spec
    title: str
    artifact_path: str
    parent_transcript_path: str | None
    created: str             # ISO date


@dataclasses.dataclass
class WeeklyDailyEntry:
    """A single daily digest summarised into the weekly input."""

    digest_date: str
    summary_path: str        # absolute path to the daily digest file
    contexts_with_activity: list[str]
    note_count: int
    glance_text: str         # body of the daily digest's "## Yesterday at a glance"


@dataclasses.dataclass
class WeeklyDigestInput:
    """Structured payload handed to the weekly LLM."""

    week_start: str          # YYYY-MM-DD (Monday)
    week_end: str            # YYYY-MM-DD (Sunday)
    iso_week_label: str      # "2026-W19"
    days: list[WeeklyDailyEntry]
    artifacts: list[WeeklyArtifact]
    stale_items: list[Any] = dataclasses.field(default_factory=list)
    checkins: list[Any] = dataclasses.field(default_factory=list)
    quiet_contexts: list[str] = dataclasses.field(default_factory=list)
    activity_by_context: dict[str, int] = dataclasses.field(default_factory=dict)
    activity_by_source: dict[str, int] = dataclasses.field(default_factory=dict)
    total_events: int = 0


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def build_weekly_input(week_end_date: date) -> WeeklyDigestInput:
    """Aggregate the 7 days ending on ``week_end_date`` (inclusive).

    ``week_end_date`` defaults to the most recent Sunday. The returned
    input spans ``[week_end - 6, week_end]``.
    """
    week_start = week_end_date - timedelta(days=6)
    iso_year, iso_week, _ = week_end_date.isocalendar()
    iso_label = f"{iso_year}-W{iso_week:02d}"

    days = list(_load_daily_digests(week_start, week_end_date))
    artifacts = list(_load_weekly_artifacts(week_start, week_end_date))
    activity_by_context, activity_by_source, total = _audit_totals(
        week_start, week_end_date,
    )
    quiet = _quiet_contexts(activity_by_context)
    stale_items, checkins = _load_metrics()

    return WeeklyDigestInput(
        week_start=week_start.isoformat(),
        week_end=week_end_date.isoformat(),
        iso_week_label=iso_label,
        days=days,
        artifacts=artifacts,
        stale_items=stale_items,
        checkins=checkins,
        quiet_contexts=quiet,
        activity_by_context=activity_by_context,
        activity_by_source=activity_by_source,
        total_events=total,
    )


def _load_daily_digests(
    start: date, end: date,
) -> Iterable[WeeklyDailyEntry]:
    """Walk daily digest files written by the daily digest worker."""
    daily_dir = vault_path() / "10-daily"
    if not daily_dir.exists():
        return []
    out: list[WeeklyDailyEntry] = []
    cur = start
    while cur <= end:
        path = daily_dir / f"{cur.isoformat()}.md"
        if path.exists():
            try:
                note = frontmatter.load(path)
            except Exception:  # noqa: BLE001
                cur += timedelta(days=1)
                continue
            meta = note.metadata
            out.append(WeeklyDailyEntry(
                digest_date=str(meta.get("date") or cur.isoformat()),
                summary_path=str(path),
                contexts_with_activity=list(meta.get("contexts") or []),
                note_count=int(meta.get("noteCount") or 0),
                glance_text=_extract_glance_section(note.content),
            ))
        cur += timedelta(days=1)
    return out


def _extract_glance_section(body: str) -> str:
    """Pull the "## Yesterday at a glance" body — the daily's TL;DR."""
    lines = (body or "").splitlines()
    capturing = False
    captured: list[str] = []
    for line in lines:
        if line.strip().startswith("## "):
            if capturing:
                break
            if "at a glance" in line.lower():
                capturing = True
                continue
        if capturing:
            captured.append(line)
    return "\n".join(captured).strip()


def _load_weekly_artifacts(
    start: date, end: date,
) -> Iterable[WeeklyArtifact]:
    """Walk transcript artifacts created within the window."""
    contexts_root = vault_path() / "20-contexts"
    if not contexts_root.exists():
        return []
    out: list[WeeklyArtifact] = []
    start_iso = start.isoformat()
    end_iso = (end + timedelta(days=1)).isoformat()  # exclusive upper

    for ctx_dir in sorted(contexts_root.iterdir()):
        if not ctx_dir.is_dir():
            continue
        artifacts_root = ctx_dir / "calendar" / "artifacts"
        if not artifacts_root.exists():
            continue
        for type_dir in sorted(artifacts_root.iterdir()):
            if not type_dir.is_dir():
                continue
            for path in sorted(type_dir.glob("*.md")):
                try:
                    note = frontmatter.load(path)
                except Exception:  # noqa: BLE001
                    continue
                meta = note.metadata
                created = str(meta.get("created") or "")[:10]
                if not created or not (start_iso <= created < end_iso):
                    continue
                title = (
                    str(meta.get("title") or "")
                    or _title_from_body(note.content)
                    or path.stem
                )
                parent = str(meta.get("parent") or "").strip("[]") or None
                out.append(WeeklyArtifact(
                    context=str(meta.get("context") or ctx_dir.name),
                    artifact_type=str(meta.get("artifactType") or type_dir.name),
                    title=title,
                    artifact_path=str(path),
                    parent_transcript_path=parent,
                    created=created,
                ))
    out.sort(key=lambda a: (a.created, a.context, a.artifact_type))
    return out


def _audit_totals(
    start: date, end: date,
) -> tuple[dict[str, int], dict[str, int], int]:
    """Tally event_processed events by context + source across the week."""
    by_ctx: Counter[str] = Counter()
    by_src: Counter[str] = Counter()
    total = 0
    cur = start
    while cur <= end:
        f = audit_dir() / f"{cur.isoformat()}.jsonl"
        if f.exists():
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
                    total += 1
                    by_ctx[str(e.get("context") or "?")] += 1
                    by_src[str(e.get("source") or "?")] += 1
        cur += timedelta(days=1)
    return dict(by_ctx), dict(by_src), total


def _quiet_contexts(activity_by_context: dict[str, int]) -> list[str]:
    """Known contexts with fewer than QUIET_THRESHOLD events all week."""
    out: list[str] = []
    for ctx in KNOWN_CONTEXTS:
        if ctx in ("needs_review",):
            continue
        if activity_by_context.get(ctx, 0) < QUIET_THRESHOLD:
            out.append(ctx)
    return out


def _load_metrics() -> tuple[list[Any], list[Any]]:
    try:
        from ghostbrain.metrics.checkins import suggest_checkins
        from ghostbrain.metrics.staleness import find_stale_items
    except ImportError:
        return [], []
    try:
        return find_stale_items(), suggest_checkins()
    except Exception:  # noqa: BLE001
        return [], []


def _title_from_body(body: str) -> str:
    for line in (body or "").splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return ""


# ---------------------------------------------------------------------------
# Render → prompt
# ---------------------------------------------------------------------------


def render_weekly_input_for_prompt(d: WeeklyDigestInput) -> str:
    parts: list[str] = [
        f"Week: {d.iso_week_label}  ({d.week_start} → {d.week_end})",
        f"Total events: {d.total_events}",
        "",
    ]

    if d.days:
        parts.append(f"Daily digests captured ({len(d.days)}):")
        for day in d.days:
            link = _wikilink_for_path(day.summary_path)
            ctxs = ", ".join(day.contexts_with_activity) or "—"
            parts.append(
                f"  {day.digest_date} ({day.note_count} note(s), {ctxs}) → {link}"
            )
        parts.append("")

    if d.artifacts:
        parts.append(
            f"Transcript-derived artifacts this week ({len(d.artifacts)}):"
        )
        # Group by type so the LLM sees decisions vs action items vs risks
        # cleanly. Sort within group by date.
        groups: dict[str, list[WeeklyArtifact]] = defaultdict(list)
        for a in d.artifacts:
            groups[a.artifact_type].append(a)
        for type_name in ("decision", "action_item", "unresolved", "spec",
                           "code", "prompt"):
            items = groups.get(type_name) or []
            if not items:
                continue
            parts.append(f"  {type_name}s ({len(items)}):")
            for a in items:
                link = _wikilink_for_path(a.artifact_path)
                parts.append(
                    f"    [{a.context}] {a.created}: {a.title} → {link}"
                )
        parts.append("")

    if d.checkins:
        parts.append(f"Check-in suggestions ({len(d.checkins)}):")
        for s in d.checkins:
            parts.append(
                f"  - {s.person} — {s.reason} (last activity "
                f"{s.last_activity[:10]})"
            )
        parts.append("")

    if d.stale_items:
        parts.append(f"Stale items still open ({len(d.stale_items)}):")
        for item in d.stale_items[:15]:
            link = _wikilink_for_path(getattr(item, "note_path", "") or "")
            link_part = f" → {link}" if link else ""
            parts.append(
                f"  [{item.kind}/{item.context}] {item.title} "
                f"({item.age_days}d, {item.state}){link_part}"
            )
        parts.append("")

    if d.activity_by_context:
        parts.append("Activity by context (event_processed counts):")
        ordered = _ordered_contexts(d.activity_by_context)
        for ctx in ordered:
            parts.append(f"  {ctx}: {d.activity_by_context[ctx]}")
        parts.append("")

    if d.quiet_contexts:
        parts.append(
            f"Quiet contexts (< {QUIET_THRESHOLD} events all week): "
            f"{', '.join(d.quiet_contexts)}"
        )
        parts.append("")

    if d.activity_by_source:
        parts.append("Activity by source:")
        for src, n in sorted(d.activity_by_source.items(),
                              key=lambda kv: -kv[1]):
            parts.append(f"  {src}: {n}")
        parts.append("")

    return "\n".join(parts)


def _ordered_contexts(activity: dict[str, int]) -> list[str]:
    seen = set(activity.keys())
    out: list[str] = []
    for ctx in KNOWN_CONTEXTS:
        if ctx in seen:
            out.append(ctx)
            seen.discard(ctx)
    out.extend(sorted(seen))
    return out


# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------


def generate_weekly_digest(week_end_date: date | None = None) -> Path:
    target = week_end_date or _most_recent_sunday(_local_today())
    inp = build_weekly_input(target)
    config = _load_config()

    prompt = _build_prompt(inp)
    model = (config.get("llm") or {}).get("digest_model", "sonnet")

    if inp.total_events == 0 and not inp.days and not inp.artifacts:
        body = _empty_week_body(inp)
    else:
        try:
            result = llm.run(prompt, model=model, budget_usd=1.5)
            body = result.text.strip() or _fallback_body(inp)
        except llm.LLMError as e:
            log.warning("weekly LLM failed for %s: %s", target, e)
            body = _fallback_body(inp)

    out = _write_weekly(inp, body)
    audit_log(
        "weekly_digest_generated",
        target.isoformat(),
        path=str(out),
        days_aggregated=len(inp.days),
        artifacts=len(inp.artifacts),
        total_events=inp.total_events,
    )
    return out


def _build_prompt(d: WeeklyDigestInput) -> str:
    template = _read_prompt("weekly-digest.md")
    rendered = render_weekly_input_for_prompt(d)
    return (
        template
        .replace("{{week_label}}", d.iso_week_label)
        .replace("{{week_start}}", d.week_start)
        .replace("{{week_end}}", d.week_end)
        .replace("{{events}}", rendered)
    )


def _write_weekly(d: WeeklyDigestInput, body: str) -> Path:
    out_dir = vault_path() / "10-daily" / "weekly"
    out_dir.mkdir(parents=True, exist_ok=True)
    front = {
        "id": f"weekly-{d.iso_week_label}",
        "type": "weekly_digest",
        "context": "cross",
        "source": "manual",
        "created": datetime.now(timezone.utc).isoformat(),
        "weekStart": d.week_start,
        "weekEnd": d.week_end,
        "isoWeek": d.iso_week_label,
        "totalEvents": d.total_events,
        "daysAggregated": len(d.days),
        "artifactCount": len(d.artifacts),
    }
    yaml_block = yaml.safe_dump(front, sort_keys=False, allow_unicode=True).rstrip()
    rendered = f"---\n{yaml_block}\n---\n\n{body.rstrip()}\n"
    out = out_dir / f"{d.iso_week_label}.md"
    out.write_text(rendered, encoding="utf-8")
    return out


def _empty_week_body(d: WeeklyDigestInput) -> str:
    return (
        f"# Week {d.iso_week_label} — {d.week_start} → {d.week_end}\n\n"
        f"## At a glance\n\n"
        f"Quiet week. No captured events.\n"
    )


def _fallback_body(d: WeeklyDigestInput) -> str:
    """Used when the LLM call fails. Mechanically formatted, preserves
    every wikilink so the user can still navigate."""
    parts = [
        f"# Week {d.iso_week_label} — {d.week_start} → {d.week_end}",
        "",
        "## At a glance",
        "",
        f"{d.total_events} event(s) processed across {len(d.days)} day(s).",
        "",
    ]

    decisions = [a for a in d.artifacts if a.artifact_type == "decision"]
    actions = [a for a in d.artifacts if a.artifact_type == "action_item"]
    risks = [a for a in d.artifacts if a.artifact_type == "unresolved"]

    if decisions:
        parts.append("## Decisions")
        parts.append("")
        for a in decisions:
            link = _wikilink_for_path(a.artifact_path)
            parts.append(f"- [{a.context}] {a.title} → {link}")
        parts.append("")
    if actions:
        parts.append("## Action items")
        parts.append("")
        for a in actions:
            link = _wikilink_for_path(a.artifact_path)
            parts.append(f"- [{a.context}] {a.title} → {link}")
        parts.append("")
    if risks:
        parts.append("## Open risks")
        parts.append("")
        for a in risks:
            link = _wikilink_for_path(a.artifact_path)
            parts.append(f"- [{a.context}] {a.title} → {link}")
        parts.append("")

    if d.quiet_contexts:
        parts.append(
            f"## Quiet this week\n\n{', '.join(d.quiet_contexts)}\n"
        )

    return "\n".join(parts)


def _read_prompt(name: str) -> str:
    f = vault_path() / "90-meta" / "prompts" / name
    if not f.exists():
        raise FileNotFoundError(
            f"missing prompt {name}; re-run `ghostbrain-bootstrap`"
        )
    return f.read_text(encoding="utf-8")


def _load_config() -> dict:
    f = vault_path() / "90-meta" / "config.yaml"
    if not f.exists():
        return {}
    return yaml.safe_load(f.read_text(encoding="utf-8")) or {}


def _local_today() -> date:
    return datetime.now().date()


def _most_recent_sunday(today: date) -> date:
    """Return the Sunday of the most recently completed week.

    If today is a Sunday, that Sunday is the week's end. Otherwise we
    look back to last Sunday so we summarise a fully-completed week.
    """
    # ISO weekday: Monday=1 ... Sunday=7.
    weekday = today.isoweekday()
    if weekday == 7:
        return today
    return today - timedelta(days=weekday)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the weekly digest.")
    parser.add_argument(
        "--week-end",
        help="ISO date (YYYY-MM-DD) of the Sunday ending the week. "
             "Defaults to the most recent Sunday.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    target = (
        date.fromisoformat(args.week_end) if args.week_end
        else _most_recent_sunday(_local_today())
    )
    out = generate_weekly_digest(target)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
