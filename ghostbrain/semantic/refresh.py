"""Refresh the embedding index + write ``related:`` frontmatter.

Walks ``vault/20-contexts/`` for every ``.md`` note. For each:
- Skip transcripts and similar long-form notes (configurable).
- Embed if the note is new or changed since last index build.
- After all embeddings, compute pairwise cosine similarities and set the
  top-K (excluding the note itself, optionally cross-context) into the
  note's ``related:`` frontmatter.

``related:`` is written through the vault write path as
``worker:semantic-refresh`` (spec B, slice B4): only that key's lines change,
``updated:`` is untouched, and the previous version lands in page history. The
job is unlisted on the Changes screen (bulk derived metadata, like ingest).
"""

from __future__ import annotations

import dataclasses
import logging
import re
from pathlib import Path
from typing import Iterable

import frontmatter

from ghostbrain.paths import vault_path
from ghostbrain.semantic.index import (
    Index,
    IndexEntry,
    load as load_index,
    save as save_index,
    text_hash,
    DEFAULT_MODEL_NAME,
)
from ghostbrain.semantic.projection import build_layout, load_layout, save_layout
from ghostbrain.vault_write import HistoryUnavailable, VaultWriteError, worker_actor
from ghostbrain.vault_write.jobs import update_fields

log = logging.getLogger("ghostbrain.semantic.refresh")

DEFAULT_TOP_K = 5
DEFAULT_MIN_SIMILARITY = 0.45
# Body text gets capped in _extract_text_and_context, so transcripts no
# longer dominate; we index them so meeting content participates in
# cross-context linking. Audio files and other non-markdown live elsewhere.
SKIP_DIR_PARTS: tuple[str, ...] = ()

SEMANTIC_ACTOR = worker_actor("semantic-refresh")


def _refresh_layout(index: Index, embedded: int) -> None:
    """Recompute + persist the 2-D layout. Never fails the refresh.

    Skipped when nothing was embedded this run AND the on-disk layout
    already covers exactly the same set of notes — recomputing the
    projection is expensive (UMAP) and every 15-minute scheduler tick
    would otherwise reshuffle the whole constellation for no reason.
    """
    try:
        if embedded == 0:
            existing = load_layout()
            if existing is not None and set(existing.positions.keys()) == set(index.entries.keys()):
                log.debug("layout unchanged (no new embeddings); skipping recompute")
                return
        save_layout(build_layout(index))
    except Exception as e:  # noqa: BLE001
        log.warning("layout projection failed: %s", e)


@dataclasses.dataclass
class RefreshResult:
    embedded: int      # notes embedded this run
    reused: int        # notes whose embedding was still fresh
    linked: int        # notes whose related: was updated
    skipped: int       # notes excluded by SKIP rules
    total: int         # total notes scanned


def refresh(
    *,
    top_k: int = DEFAULT_TOP_K,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
    cross_context_only: bool = False,
    model_name: str = DEFAULT_MODEL_NAME,
    embedder=None,
) -> RefreshResult:
    """Walk the vault, refresh the index, write ``related:`` frontmatter.

    ``embedder`` is for tests — pass an object with ``encode(list[str])``.
    Production path lazy-loads SentenceTransformer.
    """
    contexts_root = vault_path() / "20-contexts"
    if not contexts_root.exists():
        log.info("vault/20-contexts/ missing, nothing to do")
        return RefreshResult(0, 0, 0, 0, 0)

    index = load_index()
    if index.model_name != model_name:
        log.info("model changed (%s → %s); rebuilding index from scratch",
                 index.model_name, model_name)
        index = Index(model_name=model_name)

    candidates = list(_iter_notes(contexts_root))
    # Drop rows for notes that no longer exist (moved by a project rename,
    # deleted, …) so related: never links to a dead path.
    _prune_missing(index, {str(p.relative_to(vault_path())) for p in candidates})

    # Determine what needs (re-)embedding.
    to_embed_paths: list[Path] = []
    to_embed_texts: list[str] = []
    skipped = 0

    note_texts: dict[str, str] = {}
    note_contexts: dict[str, str] = {}

    for path in candidates:
        rel = str(path.relative_to(vault_path()))
        if _should_skip(path):
            skipped += 1
            continue

        text, ctx = _extract_text_and_context(path)
        if not text:
            skipped += 1
            continue

        note_texts[rel] = text
        note_contexts[rel] = ctx

        existing = index.get(rel)
        new_hash = text_hash(text)
        new_mtime = path.stat().st_mtime

        if (
            existing is not None
            and existing.content_hash == new_hash
            and abs(existing.mtime - new_mtime) < 1.0
        ):
            continue
        to_embed_paths.append(path)
        to_embed_texts.append(text)

    embedded = 0
    if to_embed_texts:
        if embedder is None:
            embedder = _load_embedder(model_name)
        embeddings = embedder.encode(to_embed_texts, show_progress_bar=False)
        for path, vec in zip(to_embed_paths, embeddings):
            rel = str(path.relative_to(vault_path()))
            text = note_texts[rel]
            _set_index_row(index, rel, vec, path.stat().st_mtime, text_hash(text))
            embedded += 1

    reused = len(note_texts) - embedded

    # Compute similarities + write frontmatter.
    paths_to_score = list(note_texts.keys())
    if not paths_to_score or index.vectors is None:
        save_index(index)
        _refresh_layout(index, embedded)
        return RefreshResult(
            embedded=embedded,
            reused=reused,
            linked=0,
            skipped=skipped,
            total=len(candidates),
        )

    linked = _write_related_frontmatter(
        index=index,
        paths=paths_to_score,
        contexts=note_contexts,
        top_k=top_k,
        min_similarity=min_similarity,
        cross_context_only=cross_context_only,
    )

    save_index(index)
    _refresh_layout(index, embedded)

    return RefreshResult(
        embedded=embedded,
        reused=reused,
        linked=linked,
        skipped=skipped,
        total=len(candidates),
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _iter_notes(root: Path) -> Iterable[Path]:
    yield from sorted(root.rglob("*.md"))


def _should_skip(path: Path) -> bool:
    parts = set(path.parts)
    return any(p in parts for p in SKIP_DIR_PARTS)


def _extract_text_and_context(path: Path) -> tuple[str, str]:
    try:
        note = frontmatter.load(path)
    except Exception:  # noqa: BLE001
        return "", ""
    title = str(note.metadata.get("title") or path.stem)
    body = (note.content or "")[:8000]   # cap to keep embedding cost predictable
    text = f"{title}\n\n{body}".strip()
    ctx = str(note.metadata.get("context") or "")
    return text, ctx


def _prune_missing(index: Index, keep: set[str]) -> int:
    """Remove entries whose path is not in ``keep`` and compact the vector
    matrix so rows stay contiguous. Returns the number of entries removed."""
    n_rows = index.vectors.shape[0] if index.vectors is not None else 0
    stale = [
        rel for rel, e in index.entries.items()
        if rel not in keep or not 0 <= e.row < n_rows
    ]
    if not stale:
        return 0
    for rel in stale:
        del index.entries[rel]
    if not index.entries:
        index.vectors = None
        return len(stale)
    import numpy as np

    kept = sorted(index.entries.items(), key=lambda kv: kv[1].row)
    index.vectors = np.ascontiguousarray(index.vectors[[e.row for _, e in kept]])
    for new_row, (_, e) in enumerate(kept):
        e.row = new_row
    log.info("pruned %d index entries for notes that no longer exist", len(stale))
    return len(stale)


def _set_index_row(
    index: Index,
    rel_path: str,
    vector,  # numpy array
    mtime: float,
    content_hash: str,
) -> None:
    import numpy as np

    if index.vectors is None or len(index.entries) == 0:
        index.vectors = np.asarray(vector, dtype="float32").reshape(1, -1)
        index.entries[rel_path] = IndexEntry(row=0, mtime=mtime, content_hash=content_hash)
        return

    existing = index.entries.get(rel_path)
    if existing is not None:
        index.vectors[existing.row] = np.asarray(vector, dtype="float32")
        existing.mtime = mtime
        existing.content_hash = content_hash
        return

    index.vectors = np.vstack([index.vectors, np.asarray(vector, dtype="float32")])
    index.entries[rel_path] = IndexEntry(
        row=index.vectors.shape[0] - 1,
        mtime=mtime,
        content_hash=content_hash,
    )


def _write_related_frontmatter(
    *,
    index: Index,
    paths: list[str],
    contexts: dict[str, str],
    top_k: int,
    min_similarity: float,
    cross_context_only: bool,
) -> int:
    import numpy as np

    if index.vectors is None or len(index.entries) < 2:
        return 0

    # L2-normalize all rows once; cosine = dot product after normalization.
    norms = np.linalg.norm(index.vectors, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    normed = index.vectors / norms

    written = 0
    rel_to_row = {p: e.row for p, e in index.entries.items()}

    for rel in paths:
        if rel not in rel_to_row:
            continue
        my_row = rel_to_row[rel]
        sims = normed @ normed[my_row]   # 1-D array, length = n_notes
        # Suppress self-similarity.
        sims[my_row] = -1.0

        # Optional cross-context filter.
        my_ctx = contexts.get(rel, "")
        candidate_indices = np.argsort(sims)[::-1]

        related: list[tuple[str, float]] = []
        for idx in candidate_indices:
            if len(related) >= top_k:
                break
            score = float(sims[idx])
            if score < min_similarity:
                break
            other_rel = _row_to_path(index, idx)
            if not other_rel:
                continue
            if cross_context_only:
                other_ctx = contexts.get(other_rel) or _ctx_from_rel(other_rel)
                if other_ctx == my_ctx:
                    continue
            related.append((other_rel, score))

        if not related:
            continue

        wikilinks = [_wikilink_for(p) for p, _ in related]
        if _apply_related(rel, wikilinks):
            written += 1

    return written


def _apply_related(rel: str, wikilinks: list[str]) -> bool:
    """Set ``related:`` on one note through the write path (slice B4).

    True only when the note was written. Never raises: a missing, malformed
    or unwritable note is logged and skipped, so one bad note can't stop a
    refresh that runs every 15 minutes."""
    rel_posix = Path(rel).as_posix()

    def compute(meta: dict) -> dict:
        return {} if meta.get("related") == wikilinks else {"related": wikilinks}

    try:
        res = update_fields(
            rel_posix, compute, actor=SEMANTIC_ACTOR, reason="updated related notes",
            bump_updated=False,
        )
    except (VaultWriteError, HistoryUnavailable, OSError) as e:
        log.warning("could not update related: on %s: %s", rel_posix, e)
        return False
    return res is not None and res.status == "applied"


def _row_to_path(index: Index, row: int) -> str | None:
    for rel, entry in index.entries.items():
        if entry.row == row:
            return rel
    return None


def _ctx_from_rel(rel: str) -> str:
    parts = Path(rel).parts
    if len(parts) >= 2 and parts[0] == "20-contexts":
        return parts[1]
    return ""


_WIKILINK_TARGET_RE = re.compile(r"\.md$")


def _wikilink_for(rel: str) -> str:
    return f"[[{_WIKILINK_TARGET_RE.sub('', rel)}]]"


def _load_embedder(model_name: str):
    """Lazy-load SentenceTransformer to avoid the import cost when unused."""
    from sentence_transformers import SentenceTransformer
    log.info("loading embedding model %s (~80MB on first run)", model_name)
    return SentenceTransformer(model_name)
