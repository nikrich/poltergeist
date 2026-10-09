"""Suggest + backlinks over the shared link index (ghostbrain.vault_index)."""
from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Iterable, TypeVar

from ghostbrain.vault_index.links import PEOPLE_DIR, LinkIndex, get_link_index
from ghostbrain.vault_index.parse import NoteEntry

T = TypeVar("T")

# Only tags the editor can write back as `#tag` and extract_tags() reads.
_HASHTAG_SAFE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
_TAG_CACHE: dict[int, tuple[int, list[tuple[str, int, int]]]] = {}


def _rank(rows: Iterable[tuple[str, int, T]], q: str) -> list[T]:
    """Prefix matches before substring matches; newest first within a tier."""
    ql = q.lower()
    scored: list[tuple[int, int, str, T]] = []
    for text, recency, item in rows:
        low = text.lower()
        if not ql or low.startswith(ql):
            tier = 0
        elif ql in low:
            tier = 1
        else:
            continue
        scored.append((tier, -recency, low, item))
    scored.sort(key=lambda s: (s[0], s[1], s[2]))
    return [s[3] for s in scored]


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
    if not index.ensure_fresh():
        return {"items": [], "indexing": True}
    query = q.strip()
    if kind == "tag":
        query = query.lstrip("#")
        rows = [
            (tag, newest, {
                "kind": "tag",
                "label": tag,
                "path": None,
                "context": "",
                "detail": f"{count} note" + ("" if count == 1 else "s"),
                "count": count,
            })
            for tag, count, newest in _tag_table(index)
        ]
    elif kind == "person":
        query = query.lstrip("@")
        rows = []
        for e in index.entries():
            if not e.path.startswith(PEOPLE_DIR + "/"):
                continue
            stem = PurePosixPath(e.path).stem
            label = _humanize(stem) if e.title == stem else e.title
            rows.append((label, e.mtime_ns, _page_item(e, "person", label)))
    else:
        rows = [(e.title, e.mtime_ns, _page_item(e, "page", e.title)) for e in index.entries()]
    return {"items": _rank(rows, query)[:limit], "indexing": False}
