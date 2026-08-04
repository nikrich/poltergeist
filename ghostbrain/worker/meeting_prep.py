"""Meeting-prep builder.

Composes a prep payload for a single calendar event by reading its
calendar note, finding related items via the semantic index, and
asking ``claude -p`` for a short brief.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import frontmatter

from ghostbrain.api.models.meeting import EventSnapshot, Prep, RelatedItem
from ghostbrain.api.repo.search import search as _semantic_search
from ghostbrain.llm.client import (
    LLMError,
    LLMTimeout,
    run as _llm_run,
)
from ghostbrain.paths import vault_path

log = logging.getLogger("ghostbrain.worker.meeting_prep")


def resolve_event_path(event_id: str) -> Path | None:
    """Find the calendar note that produced this event id.

    Agenda uses ``path.stem`` as the id, so we reverse-glob over all
    ``20-contexts/*/calendar/*.md`` files. Returns ``None`` if the event
    has been deleted from the vault.
    """
    vault = vault_path()
    if not vault.exists():
        return None
    target = f"{event_id}.md"
    for path in vault.glob("20-contexts/*/calendar/*.md"):
        if path.name == target:
            return path
    return None


def event_hash(fields: dict[str, Any]) -> str:
    """Stable hash over the cache-busting fields."""
    payload = "|".join(
        str(fields.get(k, "")) for k in ("start", "end", "description")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------------------
# build_prep
# ---------------------------------------------------------------------------

LLM_MODEL = "haiku"
LLM_TIMEOUT_S = 30
# Each `claude -p` invocation pays ~$0.06 of cache-creation overhead on
# top of the actual prompt cost (the base system prompt is recomputed every
# call because we run with `--no-session-persistence`). $0.05 was less than
# the floor and every brief silently failed with `error_max_budget_usd`.
LLM_BUDGET_USD = 0.15
RELATED_LIMIT = 8


class UnknownEvent(LookupError):
    """Raised when an event id has no matching calendar note in the vault."""


def _load_event_fields(path: Path) -> dict[str, Any]:
    post = frontmatter.load(path)
    fm = post.metadata or {}
    return {
        "title": str(fm.get("title") or ""),
        "start": str(fm.get("start") or ""),
        "end": str(fm.get("end") or ""),
        "with": [str(x) for x in (fm.get("with") or [])],
        "location": str(fm.get("location") or ""),
        "description": str(fm.get("description") or ""),
    }


def _related_for(fields: dict[str, Any]) -> list[RelatedItem]:
    """Two-query strategy: title + attendees. De-dup and keep top N by score."""
    seen: dict[str, RelatedItem] = {}

    title_q = fields["title"].strip()
    if title_q:
        for hit in _semantic_search(title_q, limit=RELATED_LIMIT).get("items", []):
            key = hit["path"]
            if key not in seen:
                seen[key] = RelatedItem(
                    path=hit["path"],
                    title=hit["title"],
                    source=_source_for(hit["path"]),
                    snippet=hit["snippet"],
                    score=float(hit["score"]),
                )

    attendees = " ".join(fields.get("with") or [])
    if attendees:
        for hit in _semantic_search(attendees, limit=RELATED_LIMIT).get("items", []):
            key = hit["path"]
            if key in seen:
                continue
            seen[key] = RelatedItem(
                path=hit["path"],
                title=hit["title"],
                source=_source_for(hit["path"]),
                snippet=hit["snippet"],
                score=float(hit["score"]),
            )

    # Drop the calendar event itself from its own related list.
    title_lower = fields["title"].lower().strip()
    items = [
        ri for ri in seen.values()
        if "/calendar/" not in ri.path or ri.title.lower().strip() != title_lower
    ]
    items.sort(key=lambda r: r.score, reverse=True)
    return items[:RELATED_LIMIT]


def _source_for(rel_path: str) -> str:
    """Derive a source tag from a vault-relative path."""
    for segment in ("calendar", "meetings", "email", "gmail", "slack", "jira",
                    "confluence", "github", "joplin"):
        if f"/{segment}/" in rel_path:
            return "email" if segment == "gmail" else segment
    return "note"


PROMPT_TEMPLATE = """You are preparing a 1-paragraph brief (max 60 words) for an upcoming meeting.

Meeting:
- Title: {title}
- When: {start} -> {end}
- Attendees: {attendees}
- Location: {location}
- Invite description: {description}

Related context from the user's vault (most relevant first):
{related_block}

Write the brief in plain prose. Focus on what's likely on the table and any unresolved threads from prior context. No filler, no bullet points, no greetings. If there is no useful context, say so in one sentence.
"""


def _build_prompt(fields: dict[str, Any], related: list[RelatedItem]) -> str:
    if related:
        related_block = "\n".join(
            f"- [{r.source}] {r.title} -- {r.snippet}" for r in related
        )
    else:
        related_block = "(no related context found)"
    return PROMPT_TEMPLATE.format(
        title=fields["title"] or "(untitled)",
        start=fields["start"],
        end=fields["end"],
        attendees=", ".join(fields["with"]) or "(none on invite)",
        location=fields["location"] or "(unspecified)",
        description=fields["description"] or "(empty)",
        related_block=related_block,
    )


def build_prep(event_id: str) -> Prep:
    """Compose a Prep payload for ``event_id``.

    Raises ``UnknownEvent`` if the calendar note is gone. LLM failures
    are captured in ``Prep.error`` rather than raised — the caller still
    gets event detail and related items.
    """
    path = resolve_event_path(event_id)
    if path is None:
        raise UnknownEvent(event_id)
    fields = _load_event_fields(path)
    snapshot = EventSnapshot(
        title=fields["title"],
        start=fields["start"],
        end=fields["end"],
        with_=fields["with"],
        location=fields["location"],
        description=fields["description"],
        hash=event_hash(fields),
    )

    related = _related_for(fields)
    brief: str | None = None
    error: str | None = None
    try:
        result = _llm_run(
            _build_prompt(fields, related),
            model=LLM_MODEL,
            timeout_s=LLM_TIMEOUT_S,
            budget_usd=LLM_BUDGET_USD,
        )
        brief = (result.text or "").strip() or None
    except (LLMError, LLMTimeout) as e:
        log.warning("meeting-prep LLM failed for %s: %s", event_id, e)
        error = f"{type(e).__name__}: {e}"

    return Prep(
        event_id=event_id,
        brief=brief,
        related=related,
        event_snapshot=snapshot,
        generated_at=datetime.now(timezone.utc).isoformat(),
        error=error,
    )
