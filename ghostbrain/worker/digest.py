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
import re
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
class TranscriptItem:
    context: str
    title: str          # parent meeting title (e.g. "TrustFlow Deep Dive")
    transcript_path: str
    parent_path: str | None
    started: str
    duration_minutes: float


@dataclasses.dataclass
class TranscriptArtifact:
    """Decision/action_item/unresolved/spec extracted from a transcript."""

    context: str
    artifact_type: str      # "decision", "action_item", "unresolved", "spec"
    title: str
    artifact_path: str
    parent_transcript_path: str | None
    created: str


@dataclasses.dataclass
class ReviewItem:
    event_id: str
    inbox_path: str | None
    source: str
    confidence: float


@dataclasses.dataclass
class DigestInput:
    """Structured payload handed to the LLM."""

    digest_date: str  # YYYY-MM-DD
    day_name: str  # "Friday"
    notes: list[CapturedNote]
    by_context: dict[str, list[CapturedNote]]
    health: dict[str, Any]
    review_queue: list[ReviewItem]
    today_calendar: list[CalendarItem] = dataclasses.field(default_factory=list)
    stale_items: list[Any] = dataclasses.field(default_factory=list)  # StaleItem
    checkins: list[Any] = dataclasses.field(default_factory=list)     # CheckinSuggestion
    transcripts: list[TranscriptItem] = dataclasses.field(default_factory=list)
    transcript_artifacts: list[TranscriptArtifact] = dataclasses.field(
        default_factory=list,
    )
    anticipations: list[Any] = dataclasses.field(default_factory=list)  # Anticipation

    @property
    def review_queue_ids(self) -> list[str]:
        """Backwards-compat for callers (and the per-context render path)
        that just want the IDs without paths."""
        return [r.event_id for r in self.review_queue]


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
    review_queue = [
        ReviewItem(
            event_id=str(e.get("event_id") or ""),
            inbox_path=str(e.get("inbox_path") or "") or None,
            source=str(e.get("source") or ""),
            confidence=float(e.get("confidence") or 0.0),
        )
        for e in audit_events
        if e.get("context") == "needs_review" and e.get("event_id")
    ]

    today_calendar = list(_load_today_calendar(target_date))
    stale_items, checkins = _load_metrics()
    transcripts = list(_load_recent_transcripts(summary_day))
    transcript_artifacts = list(_load_recent_transcript_artifacts(summary_day))
    anticipations = _load_anticipations(target_date)

    return DigestInput(
        digest_date=target_date.isoformat(),
        day_name=target_date.strftime("%A"),
        notes=notes,
        by_context=dict(by_context),
        health=health,
        review_queue=review_queue,
        today_calendar=today_calendar,
        stale_items=stale_items,
        checkins=checkins,
        transcripts=transcripts,
        transcript_artifacts=transcript_artifacts,
        anticipations=anticipations,
    )


def _load_anticipations(target_date: date) -> list[Any]:
    try:
        from ghostbrain.metrics.anticipation import detect_anticipations
    except ImportError:
        return []
    try:
        return detect_anticipations(today=target_date)
    except Exception:  # noqa: BLE001
        return []


def _load_recent_transcript_artifacts(
    summary_day: date,
) -> Iterable[TranscriptArtifact]:
    """Walk ``20-contexts/*/calendar/artifacts/<type>/*.md`` for artifacts
    extracted from transcripts on ``summary_day``."""
    contexts_root = vault_path() / "20-contexts"
    if not contexts_root.exists():
        return []

    target = summary_day.isoformat()
    out: list[TranscriptArtifact] = []

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
                created = str(meta.get("created") or "")
                if not created.startswith(target):
                    continue
                title = (
                    str(meta.get("title") or "")
                    or _title_from_body(note.content)
                    or path.stem
                )
                parent = str(meta.get("parent") or "").strip("[]") or None
                out.append(TranscriptArtifact(
                    context=str(meta.get("context") or ctx_dir.name),
                    artifact_type=str(meta.get("artifactType") or type_dir.name),
                    title=title,
                    artifact_path=str(path),
                    parent_transcript_path=parent,
                    created=created,
                ))

    out.sort(key=lambda a: (a.context, a.artifact_type, a.created))
    return out


def _load_recent_transcripts(summary_day: date) -> Iterable[TranscriptItem]:
    """Walk ``20-contexts/*/calendar/transcripts/*.md`` and surface
    transcripts whose ``created`` lands on ``summary_day`` (the day the
    digest is summarizing)."""
    contexts_root = vault_path() / "20-contexts"
    if not contexts_root.exists():
        return []

    out: list[TranscriptItem] = []
    target = summary_day.isoformat()

    for ctx_dir in sorted(contexts_root.iterdir()):
        if not ctx_dir.is_dir():
            continue
        tx_dir = ctx_dir / "calendar" / "transcripts"
        if not tx_dir.exists():
            continue
        for path in tx_dir.glob("*.md"):
            try:
                note = frontmatter.load(path)
            except Exception:  # noqa: BLE001
                continue
            meta = note.metadata
            created = str(meta.get("created") or "")
            if not created.startswith(target):
                continue

            # Title in transcript artifacts is "Transcript: <parent-title>";
            # strip the prefix to surface just the meeting name.
            raw_title = str(meta.get("title") or path.stem)
            meeting_title = raw_title.removeprefix("Transcript: ").strip()

            duration_s = meta.get("durationSeconds")
            try:
                minutes = round(float(duration_s) / 60.0, 1) if duration_s else 0.0
            except (TypeError, ValueError):
                minutes = 0.0

            parent = str(meta.get("parent") or "").strip("[]")

            out.append(TranscriptItem(
                context=str(meta.get("context") or ctx_dir.name),
                title=meeting_title,
                transcript_path=str(path),
                parent_path=parent or None,
                started=str(meta.get("started") or created),
                duration_minutes=minutes,
            ))

    out.sort(key=lambda t: t.started)
    return out


def _load_metrics() -> tuple[list[Any], list[Any]]:
    """Best-effort metrics load. Failures (missing module, vault state)
    don't block the digest."""
    try:
        from ghostbrain.metrics.checkins import suggest_checkins
        from ghostbrain.metrics.staleness import find_stale_items
    except ImportError:
        return [], []
    try:
        return find_stale_items(), suggest_checkins()
    except Exception:  # noqa: BLE001
        return [], []


def render_input_for_prompt(d: DigestInput) -> str:
    """Render the structured input as plain text the LLM digests.

    Every item that has a corresponding vault note is rendered with a
    trailing ``[[wikilink]]`` so the LLM can — and is instructed to —
    preserve those links in its bullets. The user clicks them in
    Obsidian to jump to the source.
    """
    if not d.notes and not d.review_queue and not d.today_calendar:
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

    if d.transcripts:
        parts.append(f"Meeting transcripts captured ({len(d.transcripts)}):")
        for t in d.transcripts:
            duration = (
                f", {t.duration_minutes:.0f} min" if t.duration_minutes else ""
            )
            link = _wikilink_for_path(t.transcript_path, display=t.title)
            parent_link = (
                f" (parent: [[{t.parent_path}]])"
                if t.parent_path
                else ""
            )
            parts.append(
                f"  [{t.context}] {t.title}{duration} → {link}{parent_link}"
            )
        parts.append("")

    if d.anticipations:
        parts.append(f"Anticipated absences ({len(d.anticipations)}):")
        for a in d.anticipations:
            parts.append(f"  - {a.reason}")
        parts.append("")

    if d.transcript_artifacts:
        parts.append(
            f"Transcript-derived artifacts ({len(d.transcript_artifacts)}):"
        )
        for a in d.transcript_artifacts:
            link = _wikilink_for_path(a.artifact_path, display=a.title)
            parts.append(
                f"  [{a.context}/{a.artifact_type}] {a.title} → {link}"
            )
        parts.append("")

    if d.checkins:
        parts.append(f"Check-in suggestions ({len(d.checkins)} item(s)):")
        for s in d.checkins:
            parts.append(
                f"  - {s.person} — {s.reason} (last activity "
                f"{s.last_activity[:10]})"
            )
        parts.append("")

    if d.stale_items:
        prs = [i for i in d.stale_items if i.kind == "pr"]
        tickets = [i for i in d.stale_items if i.kind == "ticket"]
        parts.append(f"Stale items ({len(prs)} PR, {len(tickets)} ticket):")
        for item in d.stale_items[:12]:
            note_path = getattr(item, "note_path", "") or ""
            # StaleItem.title is the frontmatter title when present, else
            # the filename stem — pre-humanize when it's clearly the stem.
            display = (
                item.title
                if item.title and not _looks_like_slug(item.title)
                else _humanize_slug(item.title or "")
            )
            link = _wikilink_for_path(note_path, display=display)
            link_part = f" → {link}" if link else ""
            parts.append(
                f"  [{item.kind}/{item.context}] {display} "
                f"({item.age_days}d, {item.state}){link_part}"
            )
        parts.append("")

    if d.review_queue:
        parts.append(f"Needs review (count {len(d.review_queue)}):")
        for r in d.review_queue:
            # Inbox files don't always have a frontmatter title; humanize
            # the path stem so review-queue bullets are at least readable.
            link = (
                _wikilink_for_path(
                    r.inbox_path,
                    display=_humanize_slug(Path(r.inbox_path).stem),
                )
                if r.inbox_path else ""
            )
            link_part = f" → {link}" if link else ""
            src = f" [{r.source}]" if r.source else ""
            parts.append(f"  - {r.event_id}{src}{link_part}")
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
            display = (
                n.title
                if n.title and not _looks_like_slug(n.title)
                else _humanize_slug(n.title or "")
            )
            link = (
                _wikilink_for_path(n.note_path, display=display)
                if n.note_path else ""
            )
            link_part = f" → {link}" if link else ""
            parts.append(
                f"  - [{n.source}] {display}{artifact_note}"
                f" (routed via {n.routing_method}){link_part}"
            )
        parts.append("")

    parts.append("System health:")
    for k, v in d.health.items():
        parts.append(f"  {k}: {v}")

    return "\n".join(parts)


_TIMESTAMP_PREFIX_RE = re.compile(r"^\d{8}T\d{6}Z?-")
_DISPLAY_MAX_CHARS = 80
# Common connector suffixes appended to slugs at ingest time. Stripping these
# turns "fix-redact-sensitive-data-from-log-statements-github:p" into
# "fix-redact-sensitive-data-from-log-statements" — the actual subject the
# user recognizes.
_CONNECTOR_SUFFIX_RE = re.compile(
    r"-(?:github:?p?[a-z]*|"
    r"gmailthread\d*|"
    r"slackmsg[a-z0-9:]*|"
    r"confluencesf?\w*|"
    r"jiraissue\w*|"
    r"calendareven?t\w*|"
    r"claudecode[a-z0-9-]*"
    r")$",
)


def _wikilink_for_path(absolute_or_rel: str, *, display: str | None = None) -> str:
    """Return ``[[vault/path|alias]]`` for a path inside the vault.

    The alias is what Obsidian renders to the user — slugged filenames
    leak as the visible bullet text otherwise. Callers should pass
    ``display`` (the real frontmatter title or upstream object title)
    whenever they have one; we fall back to a humanized version of the
    filename slug so the visible text is always at least readable.
    """
    if not absolute_or_rel:
        return ""
    p = Path(absolute_or_rel)
    try:
        rel = p.relative_to(vault_path())
    except ValueError:
        if p.is_absolute():
            return ""
        rel = p
    target = rel.with_suffix("").as_posix()
    alias = _shorten_for_display(display) if display else _humanize_slug(rel.stem)
    return f"[[{target}|{alias}]]"


def _looks_like_slug(text: str) -> bool:
    """Heuristic: is this string a filename stem, not a real title?

    Real titles contain spaces; filename stems use hyphens or underscores
    as separators. A string with a timestamp prefix or a long unbroken
    kebab run is almost certainly a stem.
    """
    if not text:
        return False
    if _TIMESTAMP_PREFIX_RE.match(text):
        return True
    if " " in text:
        return False
    # 4+ hyphens with no spaces → very likely kebab-case slug
    return text.count("-") >= 4


def _humanize_slug(stem: str) -> str:
    """Turn a kebab-case filename stem into a readable display title.

    Pipeline:
      strip ``YYYYMMDDTHHMMSS[Z]-`` timestamp prefix added by ingest
      strip trailing connector suffix (``-github:p``, ``-gmailthread1``, ...)
      hyphens/underscores → spaces
      collapse runs of whitespace
      sentence-case the result

    Falls back to the original stem if cleaning empties it out, so a
    weird filename still renders as something rather than nothing.
    """
    cleaned = _TIMESTAMP_PREFIX_RE.sub("", stem or "")
    # Strip connector suffixes repeatedly — some slugs have two stacked
    # (e.g. "...-githubprsanl-github:p").
    while True:
        new = _CONNECTOR_SUFFIX_RE.sub("", cleaned)
        if new == cleaned:
            break
        cleaned = new
    text = cleaned.replace("-", " ").replace("_", " ").strip()
    text = " ".join(text.split())  # collapse whitespace
    if not text:
        return stem
    if len(text) > _DISPLAY_MAX_CHARS:
        text = text[: _DISPLAY_MAX_CHARS - 1].rstrip(" -_") + "…"
    return text[0].upper() + text[1:] if len(text) > 1 else text.upper()


def _shorten_for_display(text: str) -> str:
    """Trim a real (human-provided) title to the display cap."""
    text = text.strip()
    if len(text) > _DISPLAY_MAX_CHARS:
        text = text[: _DISPLAY_MAX_CHARS - 1].rstrip(" -_") + "…"
    return text


def _short_time(iso: str) -> str:
    """Trim an ISO datetime to local-time HH:MM for digest display.

    Apple Calendar / Google emit UTC ISO strings; we want the user's
    actual wall time in the digest. ``astimezone()`` with no argument
    converts to the local timezone. Plain date strings pass through.
    """
    if not iso or "T" not in iso:
        return iso
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        local = dt.astimezone()
        return local.strftime("%H:%M")
    except ValueError:
        # Couldn't parse — fall back to the lexical hour:minute slice.
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
    parser.add_argument(
        "--backfill", type=int, metavar="N",
        help="Regenerate the last N days of digests (overwrites existing files). "
             "Useful after format/template changes — pass --backfill 7 to refresh "
             "the last week.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.backfill is not None:
        if args.backfill < 1:
            parser.error("--backfill N requires N >= 1")
        if args.date:
            parser.error("--backfill and --date are mutually exclusive")
        today = _local_today()
        for offset in range(args.backfill):
            target = today - timedelta(days=offset)
            try:
                out = generate_digest(target)
                print(f"Wrote {out}")
            except Exception as e:  # noqa: BLE001
                # Don't let one bad day take out the rest of the backfill —
                # log and keep going. The user can re-run for the failed
                # date manually with --date once we know what broke.
                log.exception("backfill failed for %s; continuing", target)
                print(f"Skipped {target}: {type(e).__name__}: {e}")
        return

    target = (
        date.fromisoformat(args.date) if args.date else _local_today()
    )
    out = generate_digest(target)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
