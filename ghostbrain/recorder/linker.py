"""Link a transcript .txt to the matching calendar event note in the vault."""

from __future__ import annotations

import dataclasses
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import frontmatter
import yaml

from ghostbrain.paths import vault_path

log = logging.getLogger("ghostbrain.recorder.linker")

MATCH_TOLERANCE = timedelta(minutes=15)


@dataclasses.dataclass
class LinkResult:
    transcript_note: Path
    parent_event_path: Path | None
    matched_title: str | None


def link_transcript(
    transcript_txt: Path,
    *,
    started_at: datetime,
    duration_s: float | None = None,
    audio_path: Path | None = None,
) -> LinkResult:
    """Find the calendar event note whose start matches ``started_at``,
    write a transcript artifact note under
    ``<ctx>/calendar/transcripts/<title>-<uid>.md`` with frontmatter
    pointing at the parent.

    Returns where things landed. If no matching event is found, the
    transcript is written under ``cross/calendar/transcripts/`` with a
    generic title.
    """
    if not transcript_txt.exists():
        raise FileNotFoundError(transcript_txt)
    body = transcript_txt.read_text(encoding="utf-8").strip()
    if not body:
        raise RuntimeError(f"transcript empty: {transcript_txt}")

    parent = _find_matching_event(started_at)

    if parent is not None:
        ctx = _context_from_path(parent.path) or "cross"
        parent_meta = parent.metadata
        title = str(parent_meta.get("title") or parent.path.stem)
    else:
        ctx = "cross"
        title = "untitled-meeting"

    target_dir = vault_path() / "20-contexts" / ctx / "calendar" / "transcripts"
    target_dir.mkdir(parents=True, exist_ok=True)

    artifact_id = str(uuid.uuid4())
    front: dict = {
        "id": artifact_id,
        "context": ctx,
        "type": "artifact",
        "artifactType": "transcript",
        "source": "recorder",
        "created": datetime.now(timezone.utc).isoformat(),
        "started": started_at.astimezone(timezone.utc).isoformat(),
        "title": f"Transcript: {title}",
    }
    if duration_s is not None:
        front["durationSeconds"] = round(duration_s, 1)
    if audio_path is not None:
        front["audioPath"] = str(audio_path)
    if parent is not None:
        front["parent"] = _wikilink_for(parent.path)

    yaml_block = yaml.safe_dump(front, sort_keys=False, allow_unicode=True).rstrip()
    rendered = (
        f"---\n{yaml_block}\n---\n\n"
        f"# Transcript — {title}\n\n"
        f"_Started: {started_at.astimezone().strftime('%Y-%m-%d %H:%M %Z')}_\n\n"
        f"{body}\n"
    )

    slug = _slugify(title)[:60] or "transcript"
    filename = f"{slug}-{artifact_id[:8]}.md"
    out_path = target_dir / filename
    out_path.write_text(rendered, encoding="utf-8")

    if parent is not None:
        _patch_parent_with_transcript(parent.path, out_path)

    log.info("transcript linked: %s → parent=%s",
             out_path, parent.path if parent else "(no match)")
    return LinkResult(
        transcript_note=out_path,
        parent_event_path=parent.path if parent else None,
        matched_title=title if parent else None,
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class _ParentEvent:
    path: Path
    metadata: dict
    start_dt: datetime


def _find_matching_event(started_at: datetime) -> _ParentEvent | None:
    """Walk all calendar notes; pick the one whose start is closest to
    ``started_at``, within MATCH_TOLERANCE."""
    contexts_root = vault_path() / "20-contexts"
    if not contexts_root.exists():
        return None

    target = started_at.astimezone(timezone.utc)
    best: tuple[timedelta, _ParentEvent] | None = None

    for ctx_dir in contexts_root.iterdir():
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
            start_str = note.metadata.get("start")
            if not start_str:
                continue
            try:
                ev_start = _parse_iso(str(start_str))
            except ValueError:
                continue
            if ev_start is None:
                continue
            delta = abs(ev_start - target)
            if delta <= MATCH_TOLERANCE:
                if best is None or delta < best[0]:
                    best = (delta, _ParentEvent(
                        path=path, metadata=note.metadata, start_dt=ev_start,
                    ))
    return best[1] if best else None


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        if "T" in value:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
                timezone.utc
            )
        # All-day events: parse as midnight UTC.
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _context_from_path(path: Path) -> str | None:
    parts = path.parts
    try:
        i = parts.index("20-contexts")
    except ValueError:
        return None
    return parts[i + 1] if i + 1 < len(parts) else None


def _slugify(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9\-_ ]", "", text).strip().lower()
    return re.sub(r"\s+", "-", text)


def _wikilink_for(path: Path) -> str:
    try:
        rel = path.relative_to(vault_path())
        return f"[[{rel.with_suffix('').as_posix()}]]"
    except ValueError:
        return f"[[{path.stem}]]"


def _patch_parent_with_transcript(parent: Path, transcript: Path) -> None:
    """Update the parent event's frontmatter to reference the transcript path."""
    try:
        note = frontmatter.load(parent)
    except Exception:  # noqa: BLE001
        log.warning("could not load parent frontmatter at %s", parent)
        return
    rel = ""
    try:
        rel = str(transcript.relative_to(vault_path()))
    except ValueError:
        rel = str(transcript)
    note.metadata["transcriptPath"] = rel
    parent.write_text(frontmatter.dumps(note), encoding="utf-8")
