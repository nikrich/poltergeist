"""Calendar agenda reader."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import frontmatter

from ghostbrain.paths import vault_path


def _walk_calendar(date: str) -> list[Path]:
    """Return calendar notes for `date` (YYYY-MM-DD).

    Matches both the connector's compact `YYYYMMDDTHHMMSS-…` filename and
    the test fixtures' dashed `YYYY-MM-DD-…` format.
    """
    vault = vault_path()
    if not vault.exists():
        return []
    compact = date.replace("-", "")
    seen: set[Path] = set()
    out: list[Path] = []
    for pattern in (f"20-contexts/*/calendar/{date}*.md", f"20-contexts/*/calendar/{compact}*.md"):
        for path in vault.glob(pattern):
            if path not in seen:
                seen.add(path)
                out.append(path)
    return out


def _meeting_titles_on(date: str) -> set[str]:
    vault = vault_path()
    if not vault.exists():
        return set()
    out: set[str] = set()
    for path in vault.glob("20-contexts/*/meetings/*.md"):
        try:
            post = frontmatter.load(path)
        except Exception:
            continue
        if str(post.metadata.get("date", "")) == date:
            out.add(str(post.metadata.get("title", "")))
    return out


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    # Python's fromisoformat handles `+00:00` but not the trailing `Z`.
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _derive_time_and_duration(fm: dict) -> tuple[str, str] | None:
    """Build (time, duration) from `start`/`end` ISO timestamps.

    Connectors write `start`/`end` in UTC (the macOS calendar connector
    emits Z-suffixed ISO strings); we format the display time in the
    machine's local timezone so an 11:00 SAST meeting doesn't read as
    09:00 in the UI.
    """
    start = _parse_iso(fm.get("start"))
    end = _parse_iso(fm.get("end"))
    if start is None:
        return None
    time_str = start.astimezone().strftime("%H:%M")
    if end is None or end <= start:
        return time_str, ""
    minutes = int((end - start).total_seconds() // 60)
    if minutes >= 60 and minutes % 60 == 0:
        duration = f"{minutes // 60}h"
    elif minutes >= 60:
        duration = f"{minutes // 60}h{minutes % 60}m"
    else:
        duration = f"{minutes}m"
    return time_str, duration


def _parse_event(path: Path, recorded_titles: set[str]) -> dict | None:
    try:
        post = frontmatter.load(path)
    except Exception:
        return None
    fm = post.metadata
    if "title" not in fm:
        return None
    if "time" in fm and "duration" in fm:
        time_str, duration = str(fm["time"]), str(fm["duration"])
    else:
        derived = _derive_time_and_duration(fm)
        if derived is None:
            return None
        time_str, duration = derived
    title = str(fm["title"])
    status = "recorded" if title in recorded_titles else "upcoming"
    return {
        "id": path.stem,
        "time": time_str,
        "duration": duration,
        "title": title,
        "with": list(fm.get("with") or []),
        "status": status,
    }


def list_agenda(date: str) -> list[dict]:
    recorded = _meeting_titles_on(date)
    items = [
        e for e in (_parse_event(p, recorded) for p in _walk_calendar(date)) if e is not None
    ]
    items.sort(key=lambda e: e["time"])
    return items
