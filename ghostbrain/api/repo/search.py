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

# See the boost block in `search()`. Tuned against the live vault — a workshop
# transcript with raw cosine 0.376 (rank #5 for "yesterday's workshop") moves
# to 0.456 with this boost, comfortably top-3 ahead of content-light calendar
# stubs and irrelevant Slack DMs about other "yesterdays".
TRANSCRIPT_PATH_BOOST = 0.08


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

    # Path-prefix boost for meeting transcripts. Pure semantic ranking
    # tends to put a content-light calendar event note above the actual
    # transcript that has the meeting content — and on phrasings like
    # "yesterday's workshop" the transcripts can fall out of top-K
    # entirely because "yesterday" lexically anchors to other notes that
    # literally say "yesterday". +0.08 is enough to bring the transcript
    # to the top of the cluster without overpowering a query that's
    # actually about something else.
    boosts = np.zeros_like(scores)
    for row, rel in by_row.items():
        if "/transcripts/" in rel:
            boosts[row] = TRANSCRIPT_PATH_BOOST
    scores = scores + boosts
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


# ── Index status + manual reindex ───────────────────────────────────────────
# The semantic-refresh scheduler job rebuilds the index every 15 min while the
# app runs. These give the UI visibility into when that last happened and a way
# to force it (so a freshly-imported note becomes searchable without waiting).

import json  # noqa: E402 — kept beside the status helpers that use it
import logging  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

from ghostbrain.semantic.index import metadata_path  # noqa: E402

log = logging.getLogger("ghostbrain.api.repo.search")

_reindex_lock = threading.Lock()
_reindex_state: dict = {"running": False, "last_error": None}


def is_reindex_running() -> bool:
    return bool(_reindex_state["running"])


def index_status() -> dict:
    """Lightweight index metadata — reads index.json only, never loads the
    (multi-MB) vectors archive or the embedding model."""
    p = metadata_path()
    if not p.exists():
        return {
            "lastIndexedAt": None,
            "noteCount": 0,
            "model": None,
            "running": is_reindex_running(),
        }
    try:
        meta = json.loads(p.read_text(encoding="utf-8"))
        entries = meta.get("entries") or {}
        model = meta.get("model_name")
    except (OSError, ValueError) as e:
        log.warning("index metadata unreadable: %s", e)
        entries, model = {}, None
    return {
        "lastIndexedAt": datetime.fromtimestamp(
            p.stat().st_mtime, tz=timezone.utc
        ).isoformat(),
        "noteCount": len(entries),
        "model": model,
        "running": is_reindex_running(),
    }


def _do_refresh() -> None:
    """Indirection over the heavy semantic refresh so callers (and tests) don't
    drag torch/sentence-transformers into import time. Patch THIS in tests."""
    from ghostbrain.semantic.refresh import refresh

    refresh()


def _reindex_worker() -> None:
    try:
        _do_refresh()
    except Exception as e:  # noqa: BLE001 — never let a refresh crash the thread
        _reindex_state["last_error"] = str(e)
        log.exception("manual reindex failed")
    finally:
        _reindex_state["running"] = False


def start_reindex() -> dict:
    """Kick a semantic refresh on a background thread. Returns immediately;
    callers poll ``index_status().running``. At most one runs at a time."""
    with _reindex_lock:
        if _reindex_state["running"]:
            return {"started": False, "alreadyRunning": True}
        _reindex_state["running"] = True
        _reindex_state["last_error"] = None
    threading.Thread(target=_reindex_worker, daemon=True, name="reindex").start()
    return {"started": True, "alreadyRunning": False}
