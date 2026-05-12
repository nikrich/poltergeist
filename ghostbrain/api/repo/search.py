"""Semantic search backed by the embedding index at ~/ghostbrain/semantic/.

Lazy-loads the SentenceTransformer model and the index on first call so the
sidecar boots fast — the ~80 MB model only gets pulled in if/when the user
runs a search.

The index file is rewritten by the semantic-refresh cron every 15 min. We
hot-reload on file mtime change so the sidecar surfaces new notes without
needing a restart.
"""
from __future__ import annotations

import threading
from pathlib import Path

import frontmatter

from ghostbrain.paths import vault_path
from ghostbrain.semantic.index import Index, load as load_index, metadata_path

_lock = threading.Lock()
_state: dict = {"index": None, "embedder": None, "index_mtime": 0.0}


def _get_index() -> Index:
    """Return the embedding index, reloading from disk if it was refreshed."""
    try:
        disk_mtime = metadata_path().stat().st_mtime
    except FileNotFoundError:
        disk_mtime = 0.0
    if _state["index"] is None or disk_mtime > _state["index_mtime"]:
        _state["index"] = load_index()
        _state["index_mtime"] = disk_mtime
    return _state["index"]


def _get_embedder(model_name: str):
    if _state["embedder"] is None:
        from sentence_transformers import SentenceTransformer

        _state["embedder"] = SentenceTransformer(model_name)
    return _state["embedder"]


def _snippet(body: str, limit: int = 200) -> str:
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "---", "===")):
            continue
        return line.lstrip("*-> ")[:limit]
    return ""


def _hit_for(rel_path: str, score: float) -> dict | None:
    path = vault_path() / rel_path
    if not path.exists():
        return None
    try:
        post = frontmatter.load(path)
    except Exception:
        return None
    title = str(post.metadata.get("title") or path.stem)
    return {
        "path": rel_path,
        "title": title,
        "snippet": _snippet(post.content or ""),
        "score": float(score),
    }


def search(q: str, limit: int = 10) -> dict:
    """Top-K cosine matches for `q` against the embedding index."""
    import numpy as np

    with _lock:
        index = _get_index()
        if index.vectors is None or not index.entries:
            return {"query": q, "total": 0, "items": []}
        embedder = _get_embedder(index.model_name)
        query_vec = np.asarray(embedder.encode([q])[0], dtype="float32")

    # Cosine on L2-normalized rows. Normalize defensively in case the
    # index wasn't built with normalization on.
    vectors = index.vectors
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    matrix = vectors / norms
    qnorm = np.linalg.norm(query_vec)
    if qnorm == 0:
        return {"query": q, "total": 0, "items": []}
    query_vec = query_vec / qnorm
    scores = matrix @ query_vec

    # row → path map (entries dict isn't necessarily ordered by row).
    by_row: dict[int, str] = {entry.row: rel for rel, entry in index.entries.items()}
    take = min(limit * 3, scores.shape[0])  # over-fetch in case some files are gone
    top = np.argpartition(-scores, take - 1)[:take]
    top = top[np.argsort(-scores[top])]

    hits: list[dict] = []
    for row in top:
        rel = by_row.get(int(row))
        if rel is None:
            continue
        hit = _hit_for(rel, scores[row])
        if hit is None:
            continue
        hits.append(hit)
        if len(hits) >= limit:
            break

    return {"query": q, "total": len(hits), "items": hits}
