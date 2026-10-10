# ghostbrain/api/repo/doc_library/search.py
"""Fuzzy doc search over title and folder path. Feeds ⌘P and the /docs picker."""
from __future__ import annotations

import re

from ghostbrain.api.repo.doc_library import index

_TOKEN = re.compile(r"[a-z]+|[0-9]+")  # letter runs and digit runs


def _initials(text: str) -> str:
    return "".join(tok[0] for tok in _TOKEN.findall(text.lower()))


def _subsequence(needle: str, hay: str) -> bool:
    it = iter(hay)
    return all(ch in it for ch in needle)


def search(q: str, project: str | None = None, limit: int = 20) -> list[dict]:
    needle = q.strip().lower()
    if not needle:
        return []
    compact = needle.replace(" ", "")
    scored: list[tuple[int, str, dict]] = []
    for e in index.all_docs().values():
        s = index.summary(e)
        title = s["title"].lower()
        path = "/".join(part for part in (s["folder"], s["original"]) if part).lower()
        if title.startswith(needle):
            score = 4
        elif needle in title:
            score = 3
        elif needle in path:
            score = 2
        elif _subsequence(compact, _initials(title)):  # acronym-style: "rcq4" -> "Rate card Q4"
            score = 1
        else:
            continue
        if project and e.project and f"{e.context}/{e.project}" == project:
            score += 5
        scored.append((-score, title, s))
    scored.sort(key=lambda t: (t[0], t[1]))
    return [s for _, _, s in scored[:limit]]
