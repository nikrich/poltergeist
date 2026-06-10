"""Helpers and file operations for manual jot notes.

Pure helpers in this module (id/slug/tag/title generation) are kept side-effect
free so they can be unit-tested without touching the filesystem. The file-I/O
helpers (write_jot, list_jots, ...) are appended below the pure helpers.
"""
from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

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


# ---------------------------------------------------------------------------
# File I/O helpers
# ---------------------------------------------------------------------------

import frontmatter  # noqa: E402 — placed after pure helpers deliberately

from ghostbrain.paths import vault_path  # noqa: E402

log = logging.getLogger("ghostbrain.api.repo.notes_manual")

INBOX_REL = "00-inbox/raw/manual"
CONTEXT_NOTES_TEMPLATE = "20-contexts/{context}/notes"
PROJECT_NOTES_TEMPLATE = "20-contexts/{context}/projects/{project}"


class JotNotFound(Exception):
    pass


class JotIdConflict(Exception):
    pass


def _random_suffix() -> str:
    return secrets.token_hex(2)  # 4 hex chars


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _vault() -> Path:
    return vault_path().resolve()


def _safe_component(raw: str) -> str:
    """Validate a single path component (jot id, context name).

    These values arrive from URL params, so treat them as hostile. Rejects
    empty values, path separators, traversal segments, and NUL bytes.
    Raises ValueError; callers that look up by jot id translate to JotNotFound.
    """
    if not raw or any(s in raw for s in ("/", "\\", "..", "\x00")):
        raise ValueError(f"unsafe path component: {raw!r}")
    return raw


def _guard_inside_vault(path: Path) -> Path:
    """Post-resolution check that `path` stays under the vault root."""
    resolved = path.resolve()
    try:
        resolved.relative_to(_vault())
    except ValueError:
        raise ValueError(f"path escapes the vault root: {path}")
    return resolved


def _inbox_dir() -> Path:
    p = _guard_inside_vault(_vault() / INBOX_REL)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _context_dir(context: str) -> Path:
    _safe_component(context)
    p = _guard_inside_vault(_vault() / CONTEXT_NOTES_TEMPLATE.format(context=context))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _find_file(jot_id: str) -> Path:
    """Locate a jot by id, regardless of where the router moved it."""
    try:
        _safe_component(jot_id)
    except ValueError:
        raise JotNotFound(jot_id)
    vault = _vault()
    # Check inbox first (cheap, most common during pending state).
    candidate = _guard_inside_vault(_inbox_dir() / f"{jot_id}.md")
    if candidate.exists():
        return candidate
    # Walk every routed context folder.
    contexts_root = vault / "20-contexts"
    if contexts_root.exists():
        for ctx_dir in contexts_root.iterdir():
            notes_dir = ctx_dir / "notes"
            if notes_dir.is_dir():
                candidate = _guard_inside_vault(notes_dir / f"{jot_id}.md")
                if candidate.exists():
                    return candidate
            # Also scan project folders under this context.
            projects_dir = ctx_dir / "projects"
            if projects_dir.is_dir():
                for proj_dir in projects_dir.iterdir():
                    if not proj_dir.is_dir():
                        continue
                    candidate = _guard_inside_vault(proj_dir / f"{jot_id}.md")
                    if candidate.exists():
                        return candidate
    raise JotNotFound(jot_id)


def _vault_rel(path: Path) -> str:
    return str(path.resolve().relative_to(_vault()))


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def write_inbox_jot(body: str, *, captured_at: "datetime | None" = None, extra: dict | None = None) -> dict:
    """Write a new jot to the inbox folder. Returns {id, path}."""
    captured_at = captured_at or datetime.now(timezone.utc)
    first_line = title_from_body(body)
    jot_id = make_jot_id(first_line, when=captured_at)
    target = _inbox_dir() / f"{jot_id}.md"
    if target.exists():
        jot_id = f"{jot_id}-{_random_suffix()}"
        target = _inbox_dir() / f"{jot_id}.md"
        if target.exists():
            raise JotIdConflict(jot_id)
    post = frontmatter.Post(
        body,
        id=jot_id,
        type="note",
        source="manual",
        context=None,
        created=captured_at.isoformat(),
        updated=captured_at.isoformat(),
        ingestedAt=_now_iso(),
        routingStatus="pending",
        routingConfidence=None,
        routingMethod=None,
        routingReasoning=None,
        tags=extract_tags(body),
    )
    if extra:
        for k, v in extra.items():
            post[k] = v
    target.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    log.info("wrote inbox jot id=%s", jot_id)
    return {"id": jot_id, "path": _vault_rel(target)}


def read_jot(jot_id: str) -> dict:
    path = _find_file(jot_id)
    post = frontmatter.load(path)
    fm = {str(k): _jsonable(v) for k, v in post.metadata.items()}
    return {
        "path": _vault_rel(path),
        "title": title_from_body(post.content or fm.get("id") or ""),
        "body": post.content or "",
        "frontmatter": fm,
    }


def update_jot_body(jot_id: str, new_body: str) -> dict:
    path = _find_file(jot_id)
    post = frontmatter.load(path)
    post.content = new_body
    post["updated"] = _now_iso()
    post["tags"] = extract_tags(new_body)
    path.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    return {"id": jot_id, "path": _vault_rel(path), "updated": post["updated"]}


def move_jot(
    jot_id: str,
    *,
    to_context: str,
    to_project: str | None = None,
    confidence: float,
    method: str,
    reasoning: str,
) -> dict:
    src = _find_file(jot_id)
    if to_project:
        _safe_component(to_project)
        dst_dir = _guard_inside_vault(
            _vault() / PROJECT_NOTES_TEMPLATE.format(context=to_context, project=to_project)
        )
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / f"{jot_id}.md"
    else:
        dst = _guard_inside_vault(_context_dir(to_context) / f"{jot_id}.md")
    if src.resolve() == dst:
        return {"id": jot_id, "path": _vault_rel(dst), "context": to_context, "project": to_project}
    post = frontmatter.load(src)
    post["context"] = to_context
    post["routingStatus"] = "routed"
    post["routingConfidence"] = confidence
    post["routingMethod"] = method
    post["routingReasoning"] = reasoning
    post["updated"] = _now_iso()
    if to_project:
        post["project"] = to_project
    elif "project" in post.metadata:
        del post.metadata["project"]
    dst.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    # Logged before unlink so a crash between dst write and src unlink
    # leaves a trace of the duplicate pair.
    log.info("moving jot id=%s: wrote %s, removing %s", jot_id, dst, src)
    src.unlink()
    log.info("moved jot id=%s -> %s (project=%s)", jot_id, to_context, to_project)
    return {"id": jot_id, "path": _vault_rel(dst), "context": to_context, "project": to_project}


def mark_manual_review(jot_id: str, reasoning: str) -> dict:
    """Keep the file at inbox path; set routingStatus=manual_review."""
    path = _find_file(jot_id)
    post = frontmatter.load(path)
    post["routingStatus"] = "manual_review"
    post["routingReasoning"] = reasoning
    post["updated"] = _now_iso()
    path.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    return {"id": jot_id, "path": _vault_rel(path), "routingStatus": "manual_review"}


def delete_jot(jot_id: str) -> None:
    path = _find_file(jot_id)
    path.unlink()


def list_jots(
    *,
    limit: int = 100,
    offset: int = 0,
    q: str | None = None,
    context: str | None = None,
    tag: str | None = None,
    project: str | None = None,
) -> dict:
    """Walk inbox + every context folder, filter to source=manual or chat-summary."""
    items: list[dict] = []
    for path in _iter_manual_files():
        try:
            post = frontmatter.load(path)
        except Exception as exc:
            log.warning("skipping malformed jot %s: %s", path, exc)
            continue
        if post.get("source") not in ("manual", "chat-summary"):
            continue
        body = post.content or ""
        item = {
            "id": post.get("id") or path.stem,
            "path": _vault_rel(path),
            "title": title_from_body(body),
            "excerpt": (body[:120] + "…") if len(body) > 120 else body,
            "context": post.get("context"),
            "routingStatus": post.get("routingStatus") or "pending",
            "tags": list(post.get("tags") or []),
            "created": post.get("created") or "",
            "updated": post.get("updated") or "",
            "project": post.get("project"),
        }
        if context is not None and item["context"] != context:
            continue
        if tag is not None and tag not in item["tags"]:
            continue
        if project is not None and item["project"] != project:
            continue
        if q is not None:
            needle = q.lower()
            if needle not in item["title"].lower() and needle not in body.lower():
                continue
        items.append(item)
    items.sort(key=lambda r: r["created"], reverse=True)
    total = len(items)
    return {"items": items[offset : offset + limit], "total": total}


# ---------------------------------------------------------------------------
# Orchestration: create + route in one call
# ---------------------------------------------------------------------------

from ghostbrain.worker.audit import audit_log  # noqa: E402
from ghostbrain.worker.router import route_event  # noqa: E402

REJECT_BELOW = 0.5  # below this confidence, jot falls back to manual_review


def _audit_safe(event_type: str, **fields: Any) -> None:
    """audit_log that never raises — an unwritable audit dir (OSError) must
    not break the never-raise contract of create_and_route_jot."""
    try:
        audit_log(event_type, **fields)
    except Exception as exc:
        log.warning("audit_log failed event_type=%s: %s", event_type, exc)


def _mark_review_safe(jot_id: str, reasoning: str) -> None:
    """mark_manual_review that never raises — the file may have vanished
    (vault is watched/synced) between the inbox write and this update."""
    try:
        mark_manual_review(jot_id, reasoning=reasoning)
    except Exception:
        log.exception("mark_manual_review failed id=%s", jot_id)


def _route_jot_core(jot_id: str, body: str, *, path_hint: str) -> dict:
    """Shared routing logic for an already-written jot.

    Runs route_event on ``body``, moves the file on success, or marks
    manual_review on low confidence / exception.  ``path_hint`` is used in
    the response when the file hasn't moved (inbox path at creation time or
    read time).

    Does NOT emit create-specific audit events — callers are responsible for
    any additional auditing (create vs. route-auto have the same decision
    semantics but different error event names are intentionally separate so
    existing auditors / tests keep working).
    """
    try:
        decision = route_event({"source": "manual", "id": jot_id, "body": body})
    except Exception as exc:
        log.exception("jot routing failed id=%s", jot_id)
        _mark_review_safe(jot_id, reasoning=f"router error: {exc}")
        return {"exc": exc}  # sentinel — callers inspect this key

    if decision.context == "needs_review" or decision.confidence < REJECT_BELOW:
        _mark_review_safe(jot_id, reasoning=decision.reasoning)
        _audit_safe(
            "manual_jot_routed",
            event_id=jot_id,
            status="manual_review",
            confidence=decision.confidence,
            reasoning=decision.reasoning,
        )
        return {
            "id": jot_id,
            "path": path_hint,
            "routingStatus": "manual_review",
        }

    try:
        moved = move_jot(
            jot_id,
            to_context=decision.context,
            to_project=decision.project,
            confidence=decision.confidence,
            method=decision.method,
            reasoning=decision.reasoning,
        )
    except Exception as exc:
        log.exception("move_jot failed context=%r id=%s", decision.context, jot_id)
        _mark_review_safe(jot_id, reasoning=f"move failed: {exc}")
        return {"move_exc": exc, "context": decision.context}  # sentinel

    _audit_safe(
        "manual_jot_routed",
        event_id=jot_id,
        status="routed",
        context=decision.context,
        confidence=decision.confidence,
        reasoning=decision.reasoning,
    )
    return {
        "id": jot_id,
        "path": moved["path"],
        "routingStatus": "routed",
        "context": decision.context,
        "project": decision.project,
    }


def route_existing_jot(jot_id: str) -> dict:
    """Re-route an existing jot by reading its CURRENT body from disk.

    Semantics identical to the routing half of create_and_route_jot:
    - confident decision → moves to context folder, returns {id, path, routingStatus:"routed", context}
    - low confidence / needs_review → marks manual_review, returns {id, path, routingStatus:"manual_review"}
    - router / move exception → marks manual_review (never raises to caller)

    Raises JotNotFound for unknown ids (route layer maps this to 404).
    """
    data = read_jot(jot_id)  # raises JotNotFound for unknown ids
    body = data["body"]
    path_hint = data["path"]

    result = _route_jot_core(jot_id, body, path_hint=path_hint)

    if "exc" in result:
        exc = result["exc"]
        _audit_safe("manual_jot_route_failed", event_id=jot_id, error=str(exc))
        return {
            "id": jot_id,
            "path": path_hint,
            "routingStatus": "manual_review",
        }
    if "move_exc" in result:
        exc = result["move_exc"]
        _audit_safe(
            "manual_jot_route_failed",
            event_id=jot_id,
            error=f"move failed: {exc}",
        )
        return {
            "id": jot_id,
            "path": path_hint,
            "routingStatus": "manual_review",
        }
    return result


def create_and_route_jot(
    body: str, *, captured_at: "datetime | None" = None
) -> dict:
    """Write a jot to the inbox, classify it, and (on success) move it to a
    context folder. Returns the public response payload.

    Routing errors and low-confidence results both leave the file in the inbox
    with routingStatus="manual_review" — never raises to the caller. The hotkey
    overlay is fire-and-forget, so callers need a stable contract.
    """
    record = write_inbox_jot(body, captured_at=captured_at)
    jot_id = record["id"]

    result = _route_jot_core(jot_id, body, path_hint=record["path"])

    if "exc" in result:
        exc = result["exc"]
        _audit_safe("manual_jot_route_failed", event_id=jot_id, error=str(exc))
        return {
            "id": jot_id,
            "path": record["path"],
            "routingStatus": "manual_review",
        }
    if "move_exc" in result:
        exc = result["move_exc"]
        _audit_safe(
            "manual_jot_route_failed",
            event_id=jot_id,
            error=f"move failed: {exc}",
        )
        return {
            "id": jot_id,
            "path": record["path"],
            "routingStatus": "manual_review",
        }
    # Strip internal "context" key from create response to match original contract
    return {
        "id": result["id"],
        "path": result["path"],
        "routingStatus": result["routingStatus"],
    }


def _iter_manual_files() -> Iterable[Path]:
    vault = _vault()
    inbox = vault / INBOX_REL
    if inbox.is_dir():
        yield from inbox.glob("manual-*.md")
    contexts_root = vault / "20-contexts"
    if contexts_root.is_dir():
        for ctx_dir in contexts_root.iterdir():
            notes_dir = ctx_dir / "notes"
            if notes_dir.is_dir():
                yield from notes_dir.glob("manual-*.md")
            projects_dir = ctx_dir / "projects"
            if projects_dir.is_dir():
                for proj_dir in projects_dir.iterdir():
                    if proj_dir.is_dir():
                        yield from proj_dir.glob("manual-*.md")
