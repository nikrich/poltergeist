"""Build the vault graph: nodes positioned by embedding, edges from links."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import frontmatter

from ghostbrain.paths import vault_path
from ghostbrain.semantic.projection import load_layout
from ghostbrain.semantic.regions import region_color, region_label

_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)")


def _context_of(rel: str) -> str:
    parts = Path(rel).parts
    return parts[1] if len(parts) >= 2 and parts[0] == "20-contexts" else ""


def _fallback_xy(rel: str) -> tuple[float, float]:
    """Deterministic position for notes without a projection yet."""
    h = int(hashlib.sha1(rel.encode("utf-8")).hexdigest(), 16)
    return ((h % 2000) - 1000) * 1.0, ((h // 2000 % 2000) - 1000) * 1.0


def _target_rel(link: str) -> str:
    """Normalise a wikilink target to a vault-relative .md path."""
    inner = link.strip().lstrip("[").rstrip("]").split("|")[0].strip()
    return inner if inner.endswith(".md") else f"{inner}.md"


def _links_from(meta: dict, body: str) -> list[tuple[str, str, float]]:
    """Return (target_rel, kind, weight) triples from one note's metadata/body."""
    out: list[tuple[str, str, float]] = []
    for item in meta.get("related") or []:
        m = _WIKILINK_RE.search(str(item))
        if m:
            out.append((_target_rel(m.group(1)), "related", 0.7))
    parent = meta.get("parent")
    if parent:
        m = _WIKILINK_RE.search(str(parent))
        if m:
            out.append((_target_rel(m.group(1)), "wikilink", 1.0))
    for m in _WIKILINK_RE.finditer(body or ""):
        out.append((_target_rel(m.group(1)), "wikilink", 0.5))
    return out


def build_graph() -> dict:
    root = vault_path() / "20-contexts"
    if not root.exists():
        return {"nodes": [], "edges": [], "regions": []}

    layout = load_layout()
    positions = layout.positions if layout else {}

    nodes: dict[str, dict] = {}
    raw_links: list[tuple[str, str, str, float]] = []  # (src, dst, kind, weight)

    for path in sorted(root.rglob("*.md")):
        rel = str(path.relative_to(vault_path()))
        try:
            note = frontmatter.load(path)
        except Exception:  # noqa: BLE001
            continue
        meta = note.metadata or {}
        xy = positions.get(rel)
        x, y = (xy[0], xy[1]) if xy else _fallback_xy(rel)
        ctx = _context_of(rel)
        tags = meta.get("tags") or []
        nodes[rel] = {
            "path": rel,
            "title": str(meta.get("title") or path.stem),
            "context": ctx,
            "tags": [str(t) for t in tags] if isinstance(tags, list) else [],
            "x": float(x),
            "y": float(y),
            "degree": 0,
            "updated": str(meta.get("updated")) if meta.get("updated") else None,
        }
        for dst, kind, weight in _links_from(meta, note.content or ""):
            raw_links.append((rel, dst, kind, weight))

    # Keep only edges whose endpoints both exist; dedup undirected pairs.
    seen: set[tuple[str, str, str]] = set()
    edges: list[dict] = []
    for src, dst, kind, weight in raw_links:
        if src == dst or dst not in nodes or src not in nodes:
            continue
        key = (*sorted((src, dst)), kind)
        if key in seen:
            continue
        seen.add(key)
        edges.append({"source": src, "target": dst, "weight": weight, "kind": kind})
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
