"""Convert a routed event into an Obsidian markdown note.

Frontmatter follows SPEC §3.2. The note is always written to
``00-inbox/raw/<source>/`` (the durable inbox). When ``write_to_context`` is
true, a second copy lands at the routed location under
``20-contexts/<ctx>/<source>/...``.
"""

from __future__ import annotations

import dataclasses
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ghostbrain.paths import vault_path
from ghostbrain.worker.router import RoutingDecision

log = logging.getLogger("ghostbrain.worker.note_generator")


@dataclasses.dataclass
class NoteWriteResult:
    inbox_path: Path
    context_path: Path | None  # None when in review-only mode


def write_note(
    event: dict,
    decision: RoutingDecision,
    *,
    body: str,
    write_to_context: bool,
) -> NoteWriteResult:
    """Render frontmatter + body and write to the inbox (always) and the
    routed context location (when allowed)."""
    note_id = event.get("id") or str(uuid.uuid4())
    source = event.get("source") or "unknown"
    type_ = event.get("type") or "note"

    front = _build_frontmatter(event, decision, note_id=note_id)
    rendered = _render(front, body)

    inbox_dir = vault_path() / "00-inbox" / "raw" / source
    inbox_path = _safe_write(inbox_dir, _filename_for(event, note_id), rendered)

    context_path: Path | None = None
    if write_to_context and decision.context not in ("needs_review", "", None):
        ctx_dir = _context_target_dir(decision.context, source, type_)
        context_path = _safe_write(ctx_dir, _filename_for(event, note_id), rendered)

    return NoteWriteResult(inbox_path=inbox_path, context_path=context_path)


def _build_frontmatter(
    event: dict,
    decision: RoutingDecision,
    *,
    note_id: str,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    md = event.get("metadata") or {}

    front: dict[str, Any] = {
        "id": note_id,
        "context": decision.context,
        "type": event.get("type") or "note",
        "source": event.get("source") or "unknown",
        "sourceId": event.get("sourceId") or event.get("id"),
        "created": event.get("timestamp") or now,
        "updated": event.get("timestamp") or now,
        "ingestedAt": now,
        "routingConfidence": round(decision.confidence, 4),
        "routingMethod": decision.method,
        "routingReasoning": decision.reasoning,
    }
    if event.get("sourceUrl"):
        front["sourceUrl"] = event["sourceUrl"]
    if event.get("title"):
        front["title"] = event["title"]
    if md.get("projectPath"):
        front["projectPath"] = md["projectPath"]
    if decision.secondary_contexts:
        front["secondaryContexts"] = decision.secondary_contexts

    # Per-source useful metadata bubbled to top-level frontmatter so Dataview
    # queries and the digest's _load_today_calendar can reach them without
    # walking the nested rawData.
    source = event.get("source")
    if source == "calendar":
        for key in ("start", "end", "isAllDay", "location", "organizer",
                    "provider", "account"):
            if md.get(key) is not None:
                front[key] = md[key]
    elif source == "jira":
        for key in ("key", "status", "priority", "project"):
            if md.get(key):
                front[key] = md[key]
    elif source == "github":
        for key in ("repo", "number", "state"):
            if md.get(key) is not None:
                front[key] = md[key]
    elif source == "confluence":
        for key in ("space", "version"):
            if md.get(key) is not None:
                front[key] = md[key]

    return front


def _render(front: dict[str, Any], body: str) -> str:
    yaml_block = yaml.safe_dump(front, sort_keys=False, allow_unicode=True).rstrip()
    return f"---\n{yaml_block}\n---\n\n{body.rstrip()}\n"


def _filename_for(event: dict, note_id: str) -> str:
    ts = event.get("timestamp") or datetime.now(timezone.utc).isoformat()
    ts_slug = re.sub(r"[^0-9TZ]", "", ts)[:15]  # 20260507T103000
    title = event.get("title") or note_id
    title_slug = _slugify(title)[:60] or "note"
    # Note ids may include `:` and `/` (e.g. `github:pr:owner/repo#42`).
    # Slugify before truncating so the suffix is filesystem-safe.
    id_suffix = _slugify(note_id)[:12] or "id"
    return f"{ts_slug}-{title_slug}-{id_suffix}.md"


def _slugify(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9\-_ ]", "", text).strip().lower()
    text = re.sub(r"\s+", "-", text)
    return text


def _context_target_dir(context: str, source: str, type_: str) -> Path:
    """Mirror the substructure created by bootstrap.py."""
    base = vault_path() / "20-contexts" / context
    if source in ("claude-code", "claude-desktop"):
        return base / "claude" / "sessions"
    if source == "github":
        if type_ == "pr":
            return base / "github" / "prs"
        if type_ == "issue":
            return base / "github" / "issues"
        return base / "github" / "repos"
    if source == "jira":
        return base / "jira" / "tickets"
    if source == "confluence":
        return base / "confluence"
    if source == "slack":
        return base / "slack"
    if source == "gmail":
        return base / "gmail"
    if source == "calendar":
        return base / "calendar"
    return base / source


def _safe_write(dir_: Path, filename: str, content: str) -> Path:
    dir_.mkdir(parents=True, exist_ok=True)
    path = dir_ / filename
    path.write_text(content, encoding="utf-8")
    return path
