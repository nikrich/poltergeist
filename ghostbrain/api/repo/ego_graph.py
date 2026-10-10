"""Ego graph for the Graph tab: a BFS over the shared link index around one page.

Nodes are notes in any indexed root (people, dailies, jots, contexts), real
files outside the roots that something links to, and *ghosts*: link targets
with no file ("linked but not written yet"). Only indexed notes and the focus
are expanded; ghosts and unindexed files are leaves, so a much-linked
placeholder like [[TODO]] cannot pull in half the vault. Each BFS layer is
ranked by link strength, then path, and the walk stops at ``cap`` nodes,
nearest first. ``truncated`` says that nodes were left out.
"""
from __future__ import annotations

from pathlib import PurePosixPath

from ghostbrain.api.repo.linking import normalize_note_path
from ghostbrain.vault_index.kinds import note_kind
from ghostbrain.vault_index.links import LinkIndex, get_link_index, link_key

EGO_NODE_CAP = 300
MAX_DEPTH = 3


class FocusNotFound(LookupError):
    pass


class _Walk:
    def __init__(self, index: LinkIndex) -> None:
        self.index = index
        self.ghost_titles: dict[str, str] = {}  # ghost id -> title as first written
        self._neighbours: dict[str, dict[str, tuple[str, float]]] = {}

    def node_id(self, target: str, exists: bool) -> str:
        if exists:
            return target
        key = link_key(target)
        self.ghost_titles.setdefault(key, PurePosixPath(target).stem)
        return key

    def expandable(self, node: str) -> bool:
        return self.index.get(node) is not None

    def neighbours(self, node: str) -> dict[str, tuple[str, float]]:
        """Neighbour id -> (edge kind, weight) of the strongest link either way."""
        cached = self._neighbours.get(node)
        if cached is not None:
            return cached
        out: dict[str, tuple[str, float]] = {}

        def add(other: str, kind: str, weight: float) -> None:
            if other == node:
                return
            current = out.get(other)
            if current is None or weight > current[1]:
                out[other] = (kind, weight)

        if node in self.ghost_titles:
            for edge in self.index.inbound(node):
                add(edge.source, edge.kind, edge.weight)
        else:
            for edge in self.index.outgoing(node):
                add(self.node_id(edge.target, edge.exists), edge.kind, edge.weight)
            for edge in self.index.backlinks(node):
                add(edge.source, edge.kind, edge.weight)
        self._neighbours[node] = out
        return out

    def node(self, path: str, hop: int) -> dict:
        degree = len(self.neighbours(path))
        entry = self.index.get(path)
        if entry is not None:
            return {
                "path": path, "title": entry.title, "context": entry.context,
                "kind": note_kind(entry), "degree": degree, "ghost": False, "hop": hop,
            }
        ghost = path in self.ghost_titles
        title = self.ghost_titles[path] if ghost else PurePosixPath(path).stem
        return {
            "path": path, "title": title, "context": "",
            "kind": "note", "degree": degree, "ghost": ghost, "hop": hop,
        }


def _root(walk: _Walk, target: str) -> str:
    focus = walk.index.resolve(target)
    if walk.index.exists(focus):
        return focus
    key = link_key(focus)
    inbound = walk.index.inbound(key)
    if not inbound:
        raise FocusNotFound(focus)
    # The UI recentres with the lower-cased key; the title keeps the case of
    # the first inbound link's written target.
    entry = walk.index.get(inbound[0].source)
    links = entry.links if entry is not None else ()
    written = next((link.target for link in links if link_key(link.target) == key), focus)
    walk.ghost_titles[key] = PurePosixPath(written).stem
    return key


def ego_graph(
    focus: str,
    depth: int = 2,
    *,
    cap: int = EGO_NODE_CAP,
    index: LinkIndex | None = None,
) -> dict:
    depth = max(1, min(MAX_DEPTH, depth))
    target = normalize_note_path(focus)  # raises InvalidLinkPath before any index work
    index = index or get_link_index()
    if not index.ensure_fresh(wait=0.1):
        return {"focus": target, "depth": depth, "nodes": [], "edges": [],
                "truncated": False, "indexing": True}

    walk = _Walk(index)
    root = _root(walk, target)
    hops: dict[str, int] = {root: 0}
    frontier = [root]
    truncated = False
    for hop in range(1, depth + 1):
        best: dict[str, float] = {}
        for node in frontier:
            if node != root and not walk.expandable(node):
                continue
            for other, (_kind, weight) in walk.neighbours(node).items():
                if other not in hops and weight > best.get(other, -1.0):
                    best[other] = weight
        if not best:
            break
        ranked = sorted(best, key=lambda p: (-best[p], p))
        room = cap - len(hops)
        if len(ranked) > room:
            ranked, truncated = ranked[:room], True
        for p in ranked:
            hops[p] = hop
        frontier = ranked
        if truncated:
            break

    nodes = [walk.node(p, h) for p, h in hops.items()]
    nodes.sort(key=lambda n: (n["hop"], -n["degree"], n["path"]))
    pairs: dict[tuple[str, str], dict] = {}
    for p in hops:
        for other, (kind, weight) in walk.neighbours(p).items():
            if other not in hops:
                continue
            a, b = sorted((p, other))
            current = pairs.get((a, b))
            if current is None or weight > current["weight"]:
                pairs[(a, b)] = {"source": a, "target": b, "kind": kind, "weight": weight}
    edges = [pairs[k] for k in sorted(pairs)]
    return {"focus": root, "depth": depth, "nodes": nodes, "edges": edges,
            "truncated": truncated, "indexing": False}
