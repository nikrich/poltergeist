"""Meeting markdown reader.

Reads recorder transcripts at <vault>/20-contexts/*/calendar/transcripts/*.md
(the actual on-disk layout) plus any future hand-authored notes at
<vault>/20-contexts/*/meetings/*.md.
"""
from __future__ import annotations

from datetime import date as dt_date, datetime
from pathlib import Path

import frontmatter

from ghostbrain.paths import vault_path


def _walk_meeting_files() -> list[Path]:
    vault = vault_path()
    if not vault.exists():
        return []
    transcripts = vault.glob("20-contexts/*/calendar/transcripts/*.md")
    meetings = vault.glob("20-contexts/*/meetings/*.md")
    seen: set[Path] = set()
    out: list[Path] = []
    for path in list(transcripts) + list(meetings):
        if path not in seen:
            seen.add(path)
            out.append(path)
    return out


def _parse_started(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    minutes = int(seconds // 60)
    if minutes < 60:
        secs = int(seconds % 60)
        return f"{minutes}m" if secs == 0 else f"{minutes}m{secs:02d}s"
    hours = minutes // 60
    rem = minutes % 60
    return f"{hours}h" if rem == 0 else f"{hours}h{rem:02d}m"


def _started_from(fm: dict) -> datetime | None:
    """Full start instant (local tz) when the note carries one."""
    started = _parse_started(fm.get("started") or fm.get("created"))
    return started.astimezone() if started is not None else None


def _date_from(fm: dict, path: Path) -> str:
    started = _started_from(fm)
    if started is not None:
        return started.strftime("%Y-%m-%d")
    raw = fm.get("date")
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dt_date):
        return raw.isoformat()
    return ""


def _dur_from(fm: dict) -> str:
    if "dur" in fm:
        return str(fm["dur"])
    secs = fm.get("durationSeconds")
    if isinstance(secs, (int, float)):
        return _format_duration(float(secs))
    return ""


def _parse(path: Path) -> dict | None:
    try:
        post = frontmatter.load(path)
    except Exception:
        return None
    fm = post.metadata
    if "title" not in fm:
        return None
    date = _date_from(fm, path)
    started = _started_from(fm)
    dur = _dur_from(fm)
    if not date and not dur:
        return None
    tags_raw = fm.get("tags") or []
    tags = list(tags_raw) if isinstance(tags_raw, list) else []
    try:
        rel_path = str(path.resolve().relative_to(vault_path().resolve()))
    except ValueError:
        rel_path = None
    return {
        "id": path.stem,
        "title": str(fm["title"]),
        "date": date,
        # Full instant + local clock time so the list can order and label
        # same-day meetings; None for notes that only carry a date.
        "startedAt": started.isoformat() if started is not None else None,
        "time": started.strftime("%H:%M") if started is not None else None,
        "dur": dur,
        "speakers": int(fm["speakers"]) if isinstance(fm.get("speakers"), int) else 0,
        "tags": [str(t) for t in tags],
        "path": rel_path,
    }


def list_meetings(limit: int = 50, offset: int = 0) -> dict:
    items = [m for m in (_parse(p) for p in _walk_meeting_files()) if m is not None]
    # Newest first by full start time; date-only notes sort as the start of
    # their day (so a timed meeting on the same day lands above them).
    items.sort(key=lambda m: m["startedAt"] or f"{m['date']}T00:00:00", reverse=True)
    total = len(items)
    return {"total": total, "items": items[offset : offset + limit]}
