"""Inverse search — find notes where you (or watched names) are mentioned
unexpectedly.

The daily digest tells you what *you* did. The weekly digest now answers
the inverse: where did your name (or your watched people's names) show
up that you didn't author? Useful for catching:

- A confluence page mentioning you in a context you don't usually work
  in (someone tagged you for review, you didn't notice).
- A jira ticket where someone @-mentioned a teammate you watch.
- A PR description quoting an old decision in a different context.

Configured via ``vault/90-meta/config.yaml:inverse_search``::

    inverse_search:
      watched_names:
        jannik811: ["jannik", "jannik richter", "jr"]
        julia: ["julia", "julia v"]
      lookback_days: 7
      # Contexts where each name is "expected" (so cross-context surfacings
      # surface as `unexpected`). Defaults to all when not specified.
      expected_contexts:
        jannik811: ["acme", "your-context", "personal"]
        julia: ["acme"]

Output is a list of ``UnexpectedReference`` for the weekly digest.
"""

from __future__ import annotations

import dataclasses
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import frontmatter
import yaml

from ghostbrain.paths import vault_path

log = logging.getLogger("ghostbrain.metrics.inverse_search")

DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_BODY_CAP_CHARS = 2000


@dataclasses.dataclass
class UnexpectedReference:
    """A single hit: name X showed up in note Y in context Z."""

    name_key: str             # config key (e.g. "julia")
    matched_phrase: str       # the actual phrase that hit (for display)
    note_path: str            # absolute path to the note
    note_title: str
    note_context: str
    note_source: str          # connector source (jira, confluence, ...)
    note_created: str         # ISO timestamp
    actor_id: str             # who authored — used to filter "I am the actor"
    excerpt: str              # short snippet around the match
    is_cross_context: bool    # True if note's context isn't an "expected" one


def find_unexpected_references(
    *,
    lookback_days: int | None = None,
    config: dict | None = None,
) -> list[UnexpectedReference]:
    """Walk vault notes from the last N days; return unexpected mentions.

    "Unexpected" means: the name appears in the note body, the note's
    actorId is not that person, and (optionally) the note's context
    isn't in the watched name's expected_contexts list.
    """
    config = config or _load_config()
    cfg = (config.get("inverse_search") or {})
    watched = cfg.get("watched_names") or {}
    if not watched:
        return []

    lookback = lookback_days or int(cfg.get("lookback_days") or DEFAULT_LOOKBACK_DAYS)
    expected = cfg.get("expected_contexts") or {}

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback)

    name_patterns: dict[str, re.Pattern[str]] = {}
    for name_key, phrases in watched.items():
        if not phrases:
            continue
        # Word-boundary OR of all phrases (case-insensitive).
        alts = "|".join(re.escape(p.strip()) for p in phrases if p.strip())
        if not alts:
            continue
        name_patterns[name_key] = re.compile(
            rf"(?<![A-Za-z0-9_])({alts})(?![A-Za-z0-9_])",
            flags=re.IGNORECASE,
        )

    if not name_patterns:
        return []

    out: list[UnexpectedReference] = []
    for path, note in _walk_recent_notes(cutoff):
        meta = note.metadata
        ctx = str(meta.get("context") or "")
        actor = str(meta.get("actorId") or "")
        body = (note.content or "")[:DEFAULT_BODY_CAP_CHARS]
        if not body.strip():
            continue

        for name_key, pattern in name_patterns.items():
            if _actor_matches_name(actor, name_key):
                # The watched person IS the actor — that's expected, skip.
                continue

            m = pattern.search(body)
            if not m:
                continue

            phrase = m.group(0)
            excerpt = _excerpt_around(body, m.start(), m.end())
            expected_ctxs = [c.lower() for c in (expected.get(name_key) or [])]
            is_cross = bool(expected_ctxs) and ctx.lower() not in expected_ctxs

            out.append(UnexpectedReference(
                name_key=name_key,
                matched_phrase=phrase,
                note_path=str(path),
                note_title=str(meta.get("title") or path.stem),
                note_context=ctx,
                note_source=str(meta.get("source") or ""),
                note_created=str(meta.get("created") or ""),
                actor_id=actor,
                excerpt=excerpt,
                is_cross_context=is_cross,
            ))

    out.sort(key=lambda r: (r.name_key, r.note_created), reverse=True)
    return out


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _walk_recent_notes(cutoff: datetime) -> Iterable[tuple[Path, frontmatter.Post]]:
    """Yield (path, parsed_note) for every .md note under vault/20-contexts
    whose ``created`` is on or after ``cutoff``."""
    contexts_root = vault_path() / "20-contexts"
    if not contexts_root.exists():
        return
    for path in sorted(contexts_root.rglob("*.md")):
        try:
            note = frontmatter.load(path)
        except Exception:  # noqa: BLE001
            continue
        created = str(note.metadata.get("created") or "")
        if not created:
            continue
        try:
            created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except ValueError:
            continue
        if created_dt.tzinfo is None:
            created_dt = created_dt.replace(tzinfo=timezone.utc)
        if created_dt < cutoff:
            continue
        yield path, note


def _actor_matches_name(actor_id: str, name_key: str) -> bool:
    """Does the actorId look like the watched name?

    actorId is connector-specific (e.g. ``slack:U123``, ``gmail:alex@x.com``,
    ``github:alex``). Lowercase substring match is good enough — false
    positives here just suppress a real mention which is acceptable.
    """
    if not actor_id:
        return False
    return name_key.lower() in actor_id.lower()


def _excerpt_around(body: str, start: int, end: int, *, window: int = 80) -> str:
    """Return ``body[start-window : end+window]`` with ``...`` markers."""
    lo = max(0, start - window)
    hi = min(len(body), end + window)
    pre = "…" if lo > 0 else ""
    post = "…" if hi < len(body) else ""
    return (pre + body[lo:hi] + post).replace("\n", " ").strip()


def _load_config() -> dict:
    f = vault_path() / "90-meta" / "config.yaml"
    if not f.exists():
        return {}
    return yaml.safe_load(f.read_text(encoding="utf-8")) or {}
