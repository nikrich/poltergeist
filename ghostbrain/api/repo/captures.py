"""Capture inbox from <vault>/00-inbox/raw/<source>/*.md."""
from __future__ import annotations

import re
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


_SLACK_USER_MENTION = re.compile(r"<@[A-Z0-9]+\|([^>]+)>")
_SLACK_CHAN_MENTION = re.compile(r"<#[A-Z0-9]+\|([^>]+)>")
_SLACK_LINK = re.compile(r"<(https?://[^|>]+)\|([^>]+)>")
# Bold key-value header like `**Source:** claude-code` or `**Key**: value`
# that some connectors prepend before (or instead of) real body content.
# Allows the colon either inside the bold span or just after it.
_BOLD_KV_LINE = re.compile(r"^\s*\*\*[\w\s]{1,30}:?\*\*\s*:?\s")


def _clean_slack_text(text: str) -> str:
    """Replace slack mention/link wire-syntax with readable forms."""
    text = _SLACK_USER_MENTION.sub(r"@\1", text)
    text = _SLACK_CHAN_MENTION.sub(r"#\1", text)
    text = _SLACK_LINK.sub(r"\2", text)
    return text


def _snippet_from_body(body: str, limit: int = 200) -> str:
    """First non-trivial prose line from the body.

    Skips: empty lines, markdown headings, horizontal rules, and bold
    key-value header lines like `**Source:** x` that several connectors
    prepend before the real content.
    """
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        if line.startswith("---") or line.startswith("==="):
            continue
        if _BOLD_KV_LINE.match(line):
            continue
        cleaned = line.lstrip("*-> ")
        if cleaned:
            return cleaned[:limit]
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
    title = str(fm.get("title") or path.stem)
    snippet = _snippet_from_body(post.content)

    # Source-specific cosmetic fixes. Stored files are untouched; this is
    # render-time cleanup so the inbox UI shows readable text instead of
    # raw connector wire-syntax.
    if source == "slack":
        title = _clean_slack_text(title)
        snippet = _clean_slack_text(snippet)
    elif source == "claude-code" and not snippet:
        project_path = fm.get("projectPath")
        if isinstance(project_path, str) and project_path:
            snippet = Path(project_path).name

    context = fm.get("context")
    context_str = str(context) if isinstance(context, str) else None
    summary = {
        "id": capture_id,
        "source": source,
        "title": title,
        "snippet": snippet,
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
            source_url = raw["metadata"].get("sourceUrl")
            return {
                **summary,
                "body": raw["content"],
                "extracted": None,
                "sourceUrl": str(source_url) if isinstance(source_url, str) else None,
            }
    return None
