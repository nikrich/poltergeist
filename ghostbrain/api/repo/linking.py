"""Suggest + backlinks over the shared link index (ghostbrain.vault_index)."""
from __future__ import annotations

import heapq
import re
from pathlib import PurePosixPath
from typing import Iterable, Iterator, TypeVar

from ghostbrain.vault_index.links import PEOPLE_DIR, LinkIndex, get_link_index
from ghostbrain.vault_index.parse import NoteEntry, normalize_target

T = TypeVar("T")

# Only tags the editor can write back as `#tag` and extract_tags() reads.
_HASHTAG_SAFE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
_TAG_CACHE: dict[int, tuple[int, list[tuple[str, int, int]]]] = {}


def _rank(rows: Iterable[tuple[str, int, T]], q: str, limit: int) -> list[T]:
    """Top ``limit`` matches: prefix before substring, newest first, then label.

    Rows carry a lightweight payload; only winners are turned into response
    items. ``nsmallest`` with an insertion counter as the last key is
    equivalent to a stable sort truncated to ``limit``, without sorting (or
    building items for) every match of a 30k-note vault.
    """
    if limit <= 0:
        return []
    ql = q.lower()

    def scored() -> Iterator[tuple[int, int, str, int, T]]:
        for seq, (text, recency, item) in enumerate(rows):
            low = text.lower()
            if not ql or low.startswith(ql):
                yield (0, -recency, low, seq, item)
            elif ql in low:
                yield (1, -recency, low, seq, item)

    return [s[4] for s in heapq.nsmallest(limit, scored())]


def _humanize(stem: str) -> str:
    return " ".join(w.capitalize() for w in re.split(r"[-_\s]+", stem) if w) or stem


def _page_item(e: NoteEntry, kind: str, label: str) -> dict:
    return {
        "kind": kind,
        "label": label,
        "path": e.path,
        "context": e.context,
        "detail": e.path[:-3] if e.path.endswith(".md") else e.path,
        "count": None,
    }


def _tag_table(index: LinkIndex) -> list[tuple[str, int, int]]:
    """(tag, note count, newest mtime_ns); cached per index generation."""
    generation = index.generation  # read BEFORE entries(): a racing change only forces a recompute
    cached = _TAG_CACHE.get(id(index))
    if cached is not None and cached[0] == generation:
        return cached[1]
    stats: dict[str, list[int]] = {}
    for e in index.entries():
        for tag in {t.lower().lstrip("#") for t in (*e.tags, *e.hashtags)}:
            if not _HASHTAG_SAFE.match(tag):
                continue
            row = stats.setdefault(tag, [0, 0])
            row[0] += 1
            row[1] = max(row[1], e.mtime_ns)
    table = [(tag, count, newest) for tag, (count, newest) in stats.items()]
    _TAG_CACHE[id(index)] = (generation, table)
    return table


def suggest(kind: str, q: str, limit: int, *, index: LinkIndex | None = None) -> dict:
    index = index or get_link_index()
    if not index.ensure_fresh(wait=0.1):
        return {"items": [], "indexing": True}
    query = q.strip()
    if kind == "tag":
        query = query.lstrip("#")
        top = _rank(((tag, newest, (tag, count)) for tag, count, newest in _tag_table(index)), query, limit)
        items = [
            {
                "kind": "tag",
                "label": tag,
                "path": None,
                "context": "",
                "detail": f"{count} note" + ("" if count == 1 else "s"),
                "count": count,
            }
            for tag, count in top
        ]
    elif kind == "person":
        query = query.lstrip("@")

        def people() -> Iterator[tuple[str, int, tuple[str, NoteEntry]]]:
            for e in index.entries():
                if not e.path.startswith(PEOPLE_DIR + "/"):
                    continue
                stem = PurePosixPath(e.path).stem
                label = _humanize(stem) if e.title == stem else e.title
                yield (label, e.mtime_ns, (label, e))

        items = [_page_item(e, "person", label) for label, e in _rank(people(), query, limit)]
    else:
        top = _rank(((e.title, e.mtime_ns, e) for e in index.entries()), query, limit)
        items = [_page_item(e, "page", e.title) for e in top]
    return {"items": items, "indexing": False}


class InvalidLinkPath(ValueError):
    pass


def normalize_note_path(raw: str) -> str:
    """Vault-relative note path with `.md`; rejects absolute / `..` / NUL."""
    p = raw.strip().replace("\\", "/")
    if not p or p.startswith("/") or "\x00" in p:
        raise InvalidLinkPath("path must be vault-relative")
    if ".." in PurePosixPath(p).parts:
        raise InvalidLinkPath("path must not contain '..'")
    return p if p.lower().endswith(".md") else f"{p}.md"


def backlinks(path: str, limit: int = 100, *, index: LinkIndex | None = None) -> dict:
    target = normalize_note_path(path)
    index = index or get_link_index()
    if not index.ensure_fresh(wait=0.1):
        return {"items": [], "indexing": True}
    best: dict[str, str] = {}  # source -> snippet (body line preferred over frontmatter "")
    for edge in index.backlinks(target):
        if edge.source not in best or (not best[edge.source] and edge.snippet):
            best[edge.source] = edge.snippet
    rows: list[tuple[int, dict]] = []
    for source, snippet in best.items():
        entry = index.get(source)
        if entry is None:
            continue
        rows.append((entry.mtime_ns, {
            "path": source,
            "title": entry.title,
            "context": entry.context,
            "snippet": snippet,
        }))
    rows.sort(key=lambda r: (-r[0], r[1]["path"]))
    return {"items": [row for _, row in rows[:limit]], "indexing": False}


def resolve_link(raw: str, *, index: LinkIndex | None = None) -> dict:
    """A wikilink target as written -> the note a click should open. Bare names
    resolve case-insensitively when unique. ``exists: False`` is an unwritten
    (or ambiguous) page; ``indexing: True`` means the index is still cold."""
    target = normalize_target(raw)
    if target is None:
        raise InvalidLinkPath("not a note link")
    target = normalize_note_path(target)
    index = index or get_link_index()
    if not index.ensure_fresh(wait=0.1):
        return {"path": target, "exists": False, "indexing": True}
    path = index.resolve(target)
    return {"path": path, "exists": index.exists(path), "indexing": False}
