"""Capture inbox from <vault>/00-inbox/raw/<source>/*.md."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import frontmatter

from ghostbrain.paths import vault_path


def _inbox_root() -> Path:
    return vault_path() / "00-inbox" / "raw"


def _is_recent(iso: str, hours: int = 6) -> bool:
    try:
        when = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - when) < timedelta(hours=hours)


def _format_from(context: str | None, captured_at: str) -> str:
    time_part = ""
    if captured_at:
        try:
            when = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            time_part = when.astimezone().strftime("%-I:%M%p").lower()
        except ValueError:
            time_part = ""
    if context and time_part:
        return f"{context} · {time_part}"
    return context or time_part or ""


def _snippet_from_body(body: str, limit: int = 200) -> str:
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        # Strip light markdown formatting.
        line = line.lstrip("*-> ")
        if line:
            return line[:limit]
    return ""


def _parse_inbox_file(path: Path) -> tuple[dict, dict] | None:
    """Returns (summary_record, full_post) or None on error."""
    try:
        post = frontmatter.load(path)
    except Exception:
        return None
    fm = post.metadata
    capture_id = str(fm.get("id", path.stem))
    source = str(fm.get("source", ""))
    if not source:
        return None
    captured_at = str(fm.get("ingestedAt") or fm.get("created") or "")
    title = str(fm.get("title", path.stem))
    context = fm.get("context")
    context_str = str(context) if isinstance(context, str) else None
    summary = {
        "id": capture_id,
        "source": source,
        "title": title,
        "snippet": _snippet_from_body(post.content),
        "from": _format_from(context_str, captured_at),
        "tags": [str(fm["type"])] if "type" in fm else [],
        "unread": _is_recent(captured_at) if captured_at else False,
        "capturedAt": captured_at,
    }
    return summary, {"content": post.content, "metadata": fm}


def _walk_inbox() -> list[tuple[dict, dict]]:
    root = _inbox_root()
    if not root.exists():
        return []
    out: list[tuple[dict, dict]] = []
    for path in root.glob("*/*.md"):
        parsed = _parse_inbox_file(path)
        if parsed is not None:
            out.append(parsed)
    return out


def list_captures(
    limit: int = 50, offset: int = 0, source: str | None = None
) -> dict:
    """Returns CapturesPage shape."""
    everything = [s for s, _ in _walk_inbox()]
    if source:
        everything = [r for r in everything if r["source"] == source]
    everything.sort(key=lambda r: r["capturedAt"], reverse=True)
    total = len(everything)
    items = everything[offset : offset + limit]
    return {"total": total, "items": items}


def get_capture(capture_id: str) -> dict | None:
    """Returns the full Capture (summary + body + extracted) or None."""
    for summary, raw in _walk_inbox():
        if summary["id"] == capture_id:
            return {**summary, "body": raw["content"], "extracted": None}
    return None
