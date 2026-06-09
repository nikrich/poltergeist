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
            if not notes_dir.is_dir():
                continue
            candidate = _guard_inside_vault(notes_dir / f"{jot_id}.md")
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


def write_inbox_jot(body: str, *, captured_at: "datetime | None" = None) -> dict:
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
    confidence: float,
    method: str,
    reasoning: str,
) -> dict:
    src = _find_file(jot_id)
    dst = _guard_inside_vault(_context_dir(to_context) / f"{jot_id}.md")
    if src.resolve() == dst:
        return {"id": jot_id, "path": _vault_rel(dst), "context": to_context}
    post = frontmatter.load(src)
    post["context"] = to_context
    post["routingStatus"] = "routed"
    post["routingConfidence"] = confidence
    post["routingMethod"] = method
    post["routingReasoning"] = reasoning
    post["updated"] = _now_iso()
    dst.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    # Logged before unlink so a crash between dst write and src unlink
    # leaves a trace of the duplicate pair.
    log.info("moving jot id=%s: wrote %s, removing %s", jot_id, dst, src)
    src.unlink()
    log.info("moved jot id=%s -> %s", jot_id, to_context)
    return {"id": jot_id, "path": _vault_rel(dst), "context": to_context}


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
) -> dict:
    """Walk inbox + every context folder, filter to source=manual."""
    items: list[dict] = []
    for path in _iter_manual_files():
        try:
            post = frontmatter.load(path)
        except Exception as exc:
            log.warning("skipping malformed jot %s: %s", path, exc)
            continue
        if post.get("source") != "manual":
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
        }
        if context is not None and item["context"] != context:
            continue
        if tag is not None and tag not in item["tags"]:
            continue
        if q is not None:
            needle = q.lower()
            if needle not in item["title"].lower() and needle not in body.lower():
                continue
        items.append(item)
    items.sort(key=lambda r: r["created"], reverse=True)
    total = len(items)
    return {"items": items[offset : offset + limit], "total": total}


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
