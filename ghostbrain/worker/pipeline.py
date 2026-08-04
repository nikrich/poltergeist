"""End-to-end event processing. Replaces the Phase 1 stub in main.py.

Pipeline (SPEC §5.3):
1. Parse — for claude-code events, read the transcript JSONL.
2. Route — path-first, LLM fallback.
3. Generate note — frontmatter + body, written to inbox + (when allowed)
   the routed context location.
4. Extract artifacts — claude-code only; LLM call. Best-effort.
5. Propose profile diffs — claude-code only; LLM call. Best-effort.
6. Audit — caller (run_loop) writes the success/fail line.

Backlinking is deferred to a later phase.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from ghostbrain.connectors.claude_code.parser import (
    SessionDigest,
    parse_transcript,
)
from ghostbrain.paths import vault_path
from ghostbrain.profile import diff as profile_diff
from ghostbrain.worker import extractor as artifact_extractor
from ghostbrain.worker.note_generator import NoteWriteResult, write_note
from ghostbrain.worker.router import RoutingDecision, route_event

log = logging.getLogger("ghostbrain.worker.pipeline")

CLAUDE_SOURCES = {"claude-code", "claude-desktop"}


def process_event(event: dict) -> dict:
    """Run the event through the full pipeline.

    Returns a summary dict with what was written and how it was routed.
    Raises on unrecoverable errors so the run_loop can move the file to
    ``failed/``.
    """
    config = _load_config()
    routing = _load_routing()
    routing_mode = (config.get("worker") or {}).get("routing_mode", "review_only")
    write_to_context = routing_mode == "live"

    excerpt: str | None = None
    body = event.get("body") or ""
    digest: SessionDigest | None = None

    if event.get("source") in CLAUDE_SOURCES:
        digest = _load_session(event)
        if digest is None:
            # Subagent sessions fire SessionEnd just like primary sessions, but
            # Claude Code rotates/deletes their JSONL before the worker reads
            # the queue file. Writing a stub note with just the title produces
            # dozens of useless "Claude Code session XXXX" inbox entries every
            # day. Drop them.
            log.info("claude-code event=%s has no readable transcript; skipping",
                     event.get("id"))
            return {
                "status": "skipped",
                "reason": "missing_transcript",
                "event_id": event.get("id"),
            }
        excerpt = digest.as_excerpt()
        body = _build_session_body(event, digest, excerpt)
        event.setdefault("metadata", {})
        if digest.cwd:
            event["metadata"].setdefault("projectPath", digest.cwd)

    decision = route_event(
        event,
        content_excerpt=excerpt,
        routing=routing,
        config=config,
    )
    log.info(
        "routed event=%s ctx=%s conf=%.2f method=%s mode=%s",
        event.get("id"), decision.context, decision.confidence,
        decision.method, routing_mode,
    )

    note = write_note(
        event,
        decision,
        body=body or _fallback_body(event),
        write_to_context=write_to_context,
    )

    artifact_paths: list[Path] = []
    profile_proposals_count = 0
    if (event.get("source") in CLAUDE_SOURCES
            and excerpt
            and decision.context not in ("needs_review", "")
            and write_to_context):
        artifact_paths = artifact_extractor.extract(
            excerpt,
            context=decision.context,
            parent_note_id=event.get("id", ""),
            parent_note_path=note.context_path or note.inbox_path,
            config=config,
        )
        # Profile diff proposal — best-effort, errors are logged inside.
        proposals = profile_diff.propose_for_session(
            excerpt=excerpt,
            parent_event_id=event.get("id", ""),
            parent_session_id=(digest.session_id if digest else None),
            parent_note_path=note.context_path or note.inbox_path,
            config=config,
        )
        profile_proposals_count = len(proposals)

    return {
        "context": decision.context,
        "confidence": decision.confidence,
        "method": decision.method,
        "routing_mode": routing_mode,
        "inbox_path": str(note.inbox_path),
        "context_path": str(note.context_path) if note.context_path else None,
        "artifact_count": len(artifact_paths),
        "profile_proposals": profile_proposals_count,
    }


def _load_session(event: dict) -> SessionDigest | None:
    """Locate the transcript file for a claude-code event and parse it."""
    metadata = event.get("metadata") or {}
    raw_data = event.get("rawData") or {}
    transcript = (
        metadata.get("transcriptPath")
        or raw_data.get("transcript_path")
        or raw_data.get("sessionFile")
    )
    if not transcript:
        log.info("no transcript path on event=%s; skipping session parse",
                 event.get("id"))
        return None
    path = Path(transcript)
    if not path.exists():
        log.warning("transcript missing for event=%s: %s", event.get("id"), path)
        return None
    digest = parse_transcript(path)
    digest.cwd = metadata.get("projectPath") or raw_data.get("cwd") or digest.cwd
    return digest


def _build_session_body(event: dict, digest: SessionDigest, excerpt: str) -> str:
    header = [
        f"# Claude Code session — {event.get('title') or digest.session_id}",
        "",
        f"**Session ID:** `{digest.session_id}`  ",
        f"**Working dir:** `{digest.cwd or 'unknown'}`  ",
        f"**Turns:** {digest.user_turn_count} user / {digest.assistant_turn_count} assistant  ",
        f"**Started:** {digest.started_at or '?'}  ",
        f"**Ended:** {digest.ended_at or '?'}  ",
        f"**Transcript:** `{digest.transcript_path}`",
        "",
        "## Excerpt",
        "",
        excerpt,
    ]
    return "\n".join(header)


def _fallback_body(event: dict) -> str:
    bits = [f"# {event.get('title') or event.get('id') or 'Note'}"]
    if event.get("source"):
        bits.append(f"\n**Source:** {event['source']}")
    if event.get("body"):
        bits.append(f"\n{event['body']}")
    return "\n".join(bits)


def _load_yaml(name: str) -> dict:
    f = vault_path() / "90-meta" / name
    if not f.exists():
        return {}
    return yaml.safe_load(f.read_text(encoding="utf-8")) or {}


def _load_config() -> dict:
    return _load_yaml("config.yaml")


def _load_routing() -> dict:
    return _load_yaml("routing.yaml")
