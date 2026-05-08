"""Daily digest generator. See SPEC §8.

Reads yesterday's audit log + frontmatter from captured notes, groups events
by context, asks the LLM to render a markdown digest, writes it to
``vault/10-daily/YYYY-MM-DD.md``. Per-context digests land in
``vault/10-daily/by-context/`` only when activity is non-trivial.
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

log = logging.getLogger("ghostbrain.worker.digest")

# Per-context digest emitted only above one of these thresholds (SPEC §8.3).
PER_CONTEXT_MIN_EVENTS = 5
PER_CONTEXT_MIN_ARTIFACTS = 2

# Match the contexts the bootstrap creates. Used to sort sections deterministically.
KNOWN_CONTEXTS: tuple[str, ...] = (
    "sanlam", "codeship", "reducedrecipes", "personal", "needs_review",
)


@dataclasses.dataclass
class CapturedNote:
    title: str
    context: str
    source: str
    artifact_count: int
    note_path: str | None
    ingested_at: str | None
    routing_method: str
    routing_confidence: float


@dataclasses.dataclass
class CalendarItem:
    """One upcoming calendar event surfaced to the digest."""

    context: str
    title: str
    start: str       # ISO8601 or YYYY-MM-DD (all-day)
    end: str
    is_all_day: bool
    location: str
    organizer: str


@dataclasses.dataclass
class DigestInput:
    """Structured payload handed to the LLM."""

    digest_date: str  # YYYY-MM-DD
    day_name: str  # "Friday"
    notes: list[CapturedNote]
    by_context: dict[str, list[CapturedNote]]
    health: dict[str, Any]
    review_queue_ids: list[str]
    today_calendar: list[CalendarItem] = dataclasses.field(default_factory=list)


def build_digest_input(target_date: date) -> DigestInput:
    """Aggregate yesterday's audit + frontmatter into a structured input.

    ``target_date`` is the *digest date* — the digest is being generated FOR
    this date, summarizing the day before.
    """
    summary_day = target_date - timedelta(days=1)

    audit_events = list(_iter_audit_for_day(summary_day))
    notes = list(_load_captured_notes(audit_events))
    by_context: dict[str, list[CapturedNote]] = defaultdict(list)
    for n in notes:
        by_context[n.context].append(n)

    health = _build_health(audit_events, summary_day)
    review_queue_ids = [
        e.get("event_id", "")
        for e in audit_events
        if e.get("context") == "needs_review"
    ]

    today_calendar = list(_load_today_calendar(target_date))

    return DigestInput(
        digest_date=target_date.isoformat(),
        day_name=target_date.strftime("%A"),
        notes=notes,
        by_context=dict(by_context),
        health=health,
        review_queue_ids=[i for i in review_queue_ids if i],
        today_calendar=today_calendar,
    )


def render_input_for_prompt(d: DigestInput) -> str:
    """Render the structured input as plain text the LLM digests."""
    if not d.notes and not d.review_queue_ids and not d.today_calendar:
        return f"Date: {d.digest_date}\n\nNo events captured.\n"

    parts: list[str] = [
        f"Digest date: {d.day_name}, {d.digest_date}",
        "",
    ]

    if d.today_calendar:
        parts.append(f"Today's calendar ({len(d.today_calendar)} item(s)):")
        for item in d.today_calendar:
            when = (
                f"all-day {item.start}"
                if item.is_all_day
                else f"{_short_time(item.start)}–{_short_time(item.end)}"
            )
            location = f" @ {item.location}" if item.location else ""
            parts.append(
                f"  [{item.context}] {when} {item.title}{location}"
            )
        parts.append("")

    if d.review_queue_ids:
        parts.append(f"Needs review (count {len(d.review_queue_ids)}):")
        for eid in d.review_queue_ids:
            parts.append(f"  - {eid}")
        parts.append("")

    for ctx in _ordered_contexts(d.by_context):
        ctx_notes = d.by_context.get(ctx, [])
        if not ctx_notes:
            continue
        parts.append(f"Context: {ctx}")
        for n in ctx_notes:
            artifact_note = (
                f", {n.artifact_count} artifact(s)"
                if n.artifact_count
                else ""
            )
            parts.append(
                f"  - [{n.source}] {n.title}{artifact_note}"
                f" (routed via {n.routing_method})"
            )
        parts.append("")

    parts.append("System health:")
    for k, v in d.health.items():
        parts.append(f"  {k}: {v}")

    return "\n".join(parts)


def _short_time(iso: str) -> str:
    """Trim an ISO datetime to HH:MM for digest display, leave date strings alone."""
    if not iso or "T" not in iso:
        return iso
    # 2026-05-09T10:00:00+02:00 → 10:00
    return iso.split("T", 1)[1][:5]


def _load_today_calendar(target_date: date) -> list[CalendarItem]:
    """Walk every ``20-contexts/*/calendar/*.md`` and surface events that
    start on ``target_date``."""
    contexts_root = vault_path() / "20-contexts"
    if not contexts_root.exists():
        return []

    today_str = target_date.isoformat()
    items: list[CalendarItem] = []

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
            meta = note.metadata
            start = str(meta.get("start") or "")
            if not start.startswith(today_str):
                continue
            items.append(CalendarItem(
                context=str(meta.get("context") or ctx_dir.name),
                title=str(meta.get("title") or path.stem),
                start=start,
                end=str(meta.get("end") or start),
                is_all_day=bool(meta.get("isAllDay")),
                location=str(meta.get("location") or ""),
                organizer=str(meta.get("organizer") or ""),
            ))

    items.sort(key=lambda i: (not i.is_all_day, i.start))
    return items


def generate_digest(target_date: date | None = None) -> Path:
    """Build the digest input, ask the LLM to render it, write to vault.

    Returns the path written.
    """
    target_date = target_date or _local_today()
    digest_input = build_digest_input(target_date)
    config = _load_config()

    prompt = _build_prompt(digest_input)
    model = (config.get("llm") or {}).get("digest_model", "sonnet")

    if digest_input.notes or digest_input.review_queue_ids:
        try:
            result = llm.run(prompt, model=model, budget_usd=1.0)
            body = result.text.strip() or _fallback_body(digest_input)
        except llm.LLMError as e:
            log.warning("digest LLM failed for %s: %s", target_date, e)
            body = _fallback_body(digest_input)
    else:
        body = _empty_day_body(digest_input)

    out_path = _write_digest(target_date, body, digest_input)
    audit_log(
        "digest_generated",
        target_date.isoformat(),
        path=str(out_path),
        notes_count=len(digest_input.notes),
        contexts=sorted(digest_input.by_context.keys()),
    )

    _write_per_context_digests(target_date, digest_input, model)
    return out_path


def _build_prompt(d: DigestInput) -> str:
    template = _read_prompt("digest.md")
    rendered_input = render_input_for_prompt(d)
    return (
        template
        .replace("{{date}}", d.digest_date)
        .replace("{{day_name}}", d.day_name)
        .replace("{{events}}", rendered_input)
    )


def _build_per_context_prompt(ctx: str, notes: list[CapturedNote], d: DigestInput) -> str:
    bullet_lines = [
        f"- [{n.source}] {n.title}"
        f" ({n.artifact_count} artifact(s))" for n in notes
    ]
    return (
        f"Write a focused 3-5 bullet summary of {ctx} activity for "
        f"{d.day_name}, {d.digest_date}.\n\n"
        f"Tone: terse, direct, no preamble, no emoji. Plain markdown.\n\n"
        f"Notes captured:\n" + "\n".join(bullet_lines)
    )


def _write_digest(target_date: date, body: str, d: DigestInput) -> Path:
    out_dir = vault_path() / "10-daily"
    out_dir.mkdir(parents=True, exist_ok=True)
    front = {
        "id": f"digest-{target_date.isoformat()}",
        "type": "digest",
        "context": "cross",
        "source": "manual",
        "created": datetime.now(timezone.utc).isoformat(),
        "date": target_date.isoformat(),
        "noteCount": len(d.notes),
        "contexts": sorted(d.by_context.keys()),
    }
    yaml_block = yaml.safe_dump(front, sort_keys=False, allow_unicode=True).rstrip()
    rendered = f"---\n{yaml_block}\n---\n\n{body.rstrip()}\n"
    out = out_dir / f"{target_date.isoformat()}.md"
    out.write_text(rendered, encoding="utf-8")
    return out


def _write_per_context_digests(
    target_date: date,
    d: DigestInput,
    model: str,
) -> list[Path]:
    out_paths: list[Path] = []
    by_ctx_dir = vault_path() / "10-daily" / "by-context"
    by_ctx_dir.mkdir(parents=True, exist_ok=True)

    for ctx, notes in d.by_context.items():
        if ctx in ("needs_review", ""):
            continue
        artifact_total = sum(n.artifact_count for n in notes)
        if len(notes) < PER_CONTEXT_MIN_EVENTS and artifact_total < PER_CONTEXT_MIN_ARTIFACTS:
            continue

        prompt = _build_per_context_prompt(ctx, notes, d)
        try:
            result = llm.run(prompt, model=model, budget_usd=0.5)
            body = result.text.strip() or _fallback_per_context_body(ctx, notes)
        except llm.LLMError as e:
            log.warning("per-context digest LLM failed for %s: %s", ctx, e)
            body = _fallback_per_context_body(ctx, notes)

        front = {
            "id": f"digest-{ctx}-{target_date.isoformat()}",
            "type": "digest",
            "context": ctx,
            "date": target_date.isoformat(),
            "noteCount": len(notes),
        }
        yaml_block = yaml.safe_dump(front, sort_keys=False, allow_unicode=True).rstrip()
        rendered = f"---\n{yaml_block}\n---\n\n{body.rstrip()}\n"
        path = by_ctx_dir / f"{ctx}-{target_date.isoformat()}.md"
        path.write_text(rendered, encoding="utf-8")
        out_paths.append(path)

    return out_paths


def _empty_day_body(d: DigestInput) -> str:
    return (
        f"# Digest — {d.day_name}, {d.digest_date}\n\n"
        f"## Yesterday at a glance\n\n"
        f"No events captured.\n\n"
        f"## System health\n\n"
        f"{_format_health_line(d.health)}\n"
    )


def _fallback_body(d: DigestInput) -> str:
    """Used when the LLM call fails. Mechanically formatted, no flourishes."""
    parts = [f"# Digest — {d.day_name}, {d.digest_date}", "", "## Yesterday at a glance", ""]
    if d.notes:
        parts.append(
            f"{len(d.notes)} note(s) captured across "
            f"{len(d.by_context)} context(s)."
        )
        parts.append("")

    for ctx in _ordered_contexts(d.by_context):
        ctx_notes = d.by_context.get(ctx, [])
        if not ctx_notes:
            continue
        parts.append(f"## {ctx.title()}")
        parts.append("")
        for n in ctx_notes[:10]:
            parts.append(f"- {n.title}")
        if len(ctx_notes) > 10:
            parts.append(f"- ...and {len(ctx_notes) - 10} more")
        parts.append("")

    parts.append("## System health")
    parts.append("")
    parts.append(_format_health_line(d.health))
    return "\n".join(parts)


def _fallback_per_context_body(ctx: str, notes: list[CapturedNote]) -> str:
    parts = [f"# {ctx.title()} — captured activity", ""]
    for n in notes[:15]:
        parts.append(f"- {n.title}")
    return "\n".join(parts) + "\n"


def _format_health_line(health: dict[str, Any]) -> str:
    return (
        f"{health.get('processed', 0)} event(s) processed, "
        f"{health.get('failed', 0)} failed. "
        f"Last capture: {health.get('last_capture', 'n/a')}."
    )


def _build_health(audit_events: list[dict], day: date) -> dict[str, Any]:
    counter = Counter(e.get("event_type") for e in audit_events)
    last_capture: str | None = None
    for e in audit_events:
        if e.get("event_type") == "event_processed":
            last_capture = e.get("ts") or last_capture

    sources = Counter(
        e.get("source", "?")
        for e in audit_events
        if e.get("event_type") == "event_processed"
    )

    return {
        "day": day.isoformat(),
        "processed": counter.get("event_processed", 0),
        "failed": counter.get("event_failed", 0),
        "worker_starts": counter.get("worker_started", 0),
        "by_source": dict(sources),
        "last_capture": last_capture or "no captures",
    }


def _iter_audit_for_day(day: date) -> Iterable[dict]:
    f = audit_dir() / f"{day.isoformat()}.jsonl"
    if not f.exists():
        return
    with f.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                log.warning("malformed audit line in %s: %r", f, line[:120])


def _load_captured_notes(audit_events: list[dict]) -> Iterable[CapturedNote]:
    """For each event_processed line, surface a CapturedNote we can render.

    We prefer the routed (context_path) note, falling back to the inbox note.
    Frontmatter is loaded for title/context only — we don't read the body.
    """
    for e in audit_events:
        if e.get("event_type") != "event_processed":
            continue
        if e.get("status") != "success":
            continue

        path_str = e.get("context_path") or e.get("inbox_path")
        if not path_str:
            continue
        path = Path(path_str)
        if not path.exists():
            continue

        try:
            note = frontmatter.load(path)
        except Exception:  # noqa: BLE001
            log.warning("could not parse frontmatter for %s", path)
            continue

        meta = note.metadata
        title = (
            meta.get("title")
            or _title_from_body(note.content)
            or path.stem
        )
        yield CapturedNote(
            title=str(title),
            context=str(meta.get("context") or e.get("context") or ""),
            source=str(meta.get("source") or e.get("source") or ""),
            artifact_count=int(e.get("artifact_count") or 0),
            note_path=str(path),
            ingested_at=str(meta.get("ingestedAt") or ""),
            routing_method=str(meta.get("routingMethod") or e.get("method") or ""),
            routing_confidence=float(meta.get("routingConfidence") or 0.0),
        )


def _title_from_body(body: str) -> str:
    for line in (body or "").splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _ordered_contexts(by_context: dict[str, list]) -> list[str]:
    """Stable ordering: known contexts first, then anything else alphabetically."""
    seen = set(by_context.keys())
    out: list[str] = []
    for ctx in KNOWN_CONTEXTS:
        if ctx in seen:
            out.append(ctx)
            seen.discard(ctx)
    out.extend(sorted(seen))
    return out


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
    """Local-machine 'today'. The digest covers yesterday."""
    return datetime.now().date()


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a daily digest.")
    parser.add_argument("--date", help="ISO date (YYYY-MM-DD). Default: today.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    target = (
        date.fromisoformat(args.date) if args.date else _local_today()
    )
    out = generate_digest(target)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
