"""Build the vault graph: nodes positioned by embedding, edges from links.

Notes and links come from the shared link index (ghostbrain.vault_index),
so the graph and the editor's backlinks/suggestions agree on what links
where. Nodes are the 20-contexts notes, as before.
"""
from __future__ import annotations

import hashlib

from ghostbrain.paths import vault_path
from ghostbrain.semantic.projection import load_layout
from ghostbrain.semantic.regions import region_color, region_label
from ghostbrain.vault_index.kinds import note_kind
from ghostbrain.vault_index.links import get_link_index

_GRAPH_ROOT = "20-contexts/"


def _fallback_xy(rel: str) -> tuple[float, float]:
    """Deterministic position for notes without a projection yet."""
    h = int(hashlib.sha1(rel.encode("utf-8")).hexdigest(), 16)
    return ((h % 2000) - 1000) * 1.0, ((h // 2000 % 2000) - 1000) * 1.0


def build_graph() -> dict:
    if not (vault_path() / "20-contexts").exists():
        return {"nodes": [], "edges": [], "regions": []}

    index = get_link_index()
    index.refresh()  # graph is a slow, explicit view: always fully fresh

    layout = load_layout()
    # Layout keys come from str(Path.relative_to(...)), so they are
    # backslash-separated on Windows; index paths are always posix.
    positions = (
        {k.replace("\\", "/"): v for k, v in layout.positions.items()} if layout else {}
    )

    entries = sorted(
        (e for e in index.entries() if e.path.startswith(_GRAPH_ROOT)),
        key=lambda e: e.path,
    )
    nodes: dict[str, dict] = {}
    for e in entries:
        xy = positions.get(e.path)
        x, y = (xy[0], xy[1]) if xy else _fallback_xy(e.path)
        nodes[e.path] = {
            "path": e.path,
            "title": e.title,
            "context": e.context,
            "tags": list(e.tags),
            "x": float(x),
            "y": float(y),
            "degree": 0,
            "updated": e.updated,
            "kind": note_kind(e),
        }

    # Keep only edges whose endpoints both exist; dedup undirected pairs.
    seen: set[tuple[str, str, str]] = set()
    edges: list[dict] = []
    for e in entries:
        for link in index.outgoing(e.path):
            src, dst = link.source, link.target
            if src == dst or dst not in nodes:
                continue
            key = (*sorted((src, dst)), link.kind)
            if key in seen:
                continue
            seen.add(key)
            edges.append({"source": src, "target": dst, "weight": link.weight, "kind": link.kind})
            nodes[src]["degree"] += 1
            nodes[dst]["degree"] += 1

    region_counts: dict[str, int] = {}
    for n in nodes.values():
        region_counts[n["context"]] = region_counts.get(n["context"], 0) + 1
    regions = [
        {"id": ctx, "label": region_label(ctx), "color": region_color(ctx), "count": count}
        for ctx, count in sorted(region_counts.items())
    ]

    return {"nodes": list(nodes.values()), "edges": edges, "regions": regions}
