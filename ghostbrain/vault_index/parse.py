"""Parse one vault note into a link-index entry. Pure: no filesystem access.

The link vocabulary (kind/weight) matches what graph.py has always emitted:
frontmatter ``related`` items are "related" edges (0.7), ``parent`` is a
"wikilink" edge (1.0), body wikilinks are "wikilink" edges (0.5).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

import yaml

_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)  # C loader: ~10x faster cold builds
_OPEN_RE = re.compile(r"\A---[ \t]*\r?\n")
_CLOSE_RE = re.compile(r"^---[ \t]*\r?$", re.MULTILINE)

# [[target]], [[target|alias]], [[target#heading|alias]] — but not ![[embeds]].
WIKILINK_RE = re.compile(r"(?<!!)\[\[([^\[\]|#\n]*)(?:#[^\[\]|\n]*)?(?:\|[^\[\]\n]*)?\]\]")
# Same pattern as notes_manual._TAG_RE (a test asserts they stay identical).
# Duplicated so this module doesn't import notes_manual's LLM/worker deps.
HASHTAG_RE = re.compile(r"(?:^|\s)#([a-z0-9](?:[a-z0-9-]*[a-z0-9])?)", re.IGNORECASE)

_ATTACHMENT_SUFFIXES = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".pdf",
    ".mp3", ".m4a", ".wav", ".mp4", ".mov", ".webm",
    ".canvas", ".excalidraw", ".csv", ".zip",
})
SNIPPET_MAX = 200


@dataclass(frozen=True)
class OutLink:
    target: str
    kind: str
    weight: float
    snippet: str


@dataclass(frozen=True)
class NoteEntry:
    path: str
    title: str
    context: str
    type: str | None
    artifact_type: str | None
    source: str | None
    status: str | None
    tags: tuple[str, ...]
    hashtags: tuple[str, ...]
    created: str | None
    updated: str | None
    mtime_ns: int
    size: int
    links: tuple[OutLink, ...]


def normalize_target(raw: str) -> str | None:
    """Wikilink target -> vault-relative ``.md`` key; None for attachments/empty."""
    t = raw.strip().replace("\\", "/").lstrip("/")
    if not t:
        return None
    if t.lower().endswith(".md"):
        return t
    if PurePosixPath(t).suffix.lower() in _ATTACHMENT_SUFFIXES:
        return None
    return f"{t}.md"


def split_frontmatter(text: str) -> tuple[dict, str]:
    """Return (metadata, body). Bad or non-mapping YAML yields {} — never raises."""
    opening = _OPEN_RE.match(text)
    if not opening:
        return {}, text
    closing = _CLOSE_RE.search(text, opening.end())
    if not closing:
        return {}, text
    raw = text[opening.end():closing.start()]
    body = text[closing.end():]
    if body.startswith("\r\n"):
        body = body[2:]
    elif body.startswith("\n"):
        body = body[1:]
    try:
        meta = yaml.load(raw, Loader=_LOADER) if raw.strip() else {}
    except Exception:  # noqa: BLE001 — a broken header must not abort indexing
        meta = {}
    return (meta if isinstance(meta, dict) else {}), body


def _opt_str(value: Any) -> str | None:
    return None if value is None or value == "" else str(value)


def _context_of(rel: str, meta: dict) -> str:
    parts = PurePosixPath(rel).parts
    if len(parts) >= 3 and parts[0] == "20-contexts":
        return parts[1]
    ctx = meta.get("context")
    return ctx if isinstance(ctx, str) else ""


def _first_target(value: Any) -> str | None:
    m = WIKILINK_RE.search(str(value))
    return normalize_target(m.group(1)) if m else None


def _frontmatter_links(meta: dict) -> list[OutLink]:
    out: list[OutLink] = []
    related = meta.get("related")
    if isinstance(related, list):
        for item in related:
            target = _first_target(item)
            if target:
                out.append(OutLink(target, "related", 0.7, ""))
    parent = meta.get("parent")
    if parent:
        target = _first_target(parent)
        if target:
            out.append(OutLink(target, "wikilink", 1.0, ""))
    return out


def _body_links(body: str) -> list[OutLink]:
    out: list[OutLink] = []
    for line in body.splitlines():
        if "[[" not in line:
            continue
        snippet = line.strip()[:SNIPPET_MAX]
        for m in WIKILINK_RE.finditer(line):
            target = normalize_target(m.group(1))
            if target:
                out.append(OutLink(target, "wikilink", 0.5, snippet))
    return out


def _hashtags(body: str) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for m in HASHTAG_RE.finditer(body):
        seen.setdefault(m.group(1).lower(), None)
    return tuple(seen)


def parse_note(rel: str, text: str, *, mtime_ns: int, size: int) -> NoteEntry:
    meta, body = split_frontmatter(text)
    raw_tags = meta.get("tags")
    tags = tuple(str(t) for t in raw_tags) if isinstance(raw_tags, list) else ()
    return NoteEntry(
        path=rel,
        title=str(meta.get("title") or PurePosixPath(rel).stem),
        context=_context_of(rel, meta),
        type=_opt_str(meta.get("type")),
        artifact_type=_opt_str(meta.get("artifactType")),
        source=_opt_str(meta.get("source")),
        status=_opt_str(meta.get("status")),
        tags=tags,
        hashtags=_hashtags(body),
        created=_opt_str(meta.get("created")),
        updated=_opt_str(meta.get("updated")),
        mtime_ns=mtime_ns,
        size=size,
        links=tuple(_frontmatter_links(meta) + _body_links(body)),
    )
