"""Helpers and file operations for manual jot notes.

Pure helpers in this module (id/slug/tag/title generation) are kept side-effect
free so they can be unit-tested without touching the filesystem. The file-I/O
helpers (write_jot, list_jots, ...) come in later tasks.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

_SLUG_MAX = 32
_TITLE_MAX = 80
_TAG_RE = re.compile(r"(?:^|\s)#([a-z0-9](?:[a-z0-9-]*[a-z0-9])?)", re.IGNORECASE)


def make_slug(text: str) -> str:
    """Lowercase, collapse non-alnum to '-', strip, truncate."""
    s = re.sub(r"[^a-z0-9]+", "-", text.lower())
    s = s.strip("-")
    if not s:
        return "untitled"
    return s[:_SLUG_MAX].rstrip("-") or "untitled"


def make_jot_id(first_line: str, *, when: datetime | None = None) -> str:
    """Produce `manual-{YYYYMMDDTHHMMSS}-{slug}`."""
    if when is not None and when.tzinfo is None:
        raise ValueError("when must be timezone-aware")
    when = when or datetime.now(timezone.utc)
    ts = when.strftime("%Y%m%dT%H%M%S")
    return f"manual-{ts}-{make_slug(first_line)}"


def extract_tags(body: str) -> list[str]:
    """Find whitespace-preceded `#tag` hashtags; dedupe; preserve order; lowercase."""
    seen: dict[str, None] = {}
    for match in _TAG_RE.finditer(body):
        tag = match.group(1).lower()
        if tag not in seen:
            seen[tag] = None
    return list(seen.keys())


def title_from_body(body: str) -> str:
    """First non-empty line, markdown header strip, truncate to 80 chars."""
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^#{1,6}\s*", "", line)
        return line[:_TITLE_MAX]
    return "untitled"
