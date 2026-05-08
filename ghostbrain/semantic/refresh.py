"""Refresh the embedding index + write ``related:`` frontmatter.

Walks ``vault/20-contexts/`` for every ``.md`` note. For each:
- Skip transcripts and similar long-form notes (configurable).
- Embed if the note is new or changed since last index build.
- After all embeddings, compute pairwise cosine similarities and set the
  top-K (excluding the note itself, optionally cross-context) into the
  note's ``related:`` frontmatter.
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

log = logging.getLogger("ghostbrain.semantic.refresh")

DEFAULT_TOP_K = 5
DEFAULT_MIN_SIMILARITY = 0.45
SKIP_DIR_PARTS = ("transcripts",)  # don't index — too long, dominate


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

        full_path = vault_path() / rel
        if not full_path.exists():
            continue
        try:
            note = frontmatter.load(full_path)
        except Exception:  # noqa: BLE001
            continue

        wikilinks = [_wikilink_for(p) for p, _ in related]
        if note.metadata.get("related") == wikilinks:
            continue
        note.metadata["related"] = wikilinks
        full_path.write_text(frontmatter.dumps(note), encoding="utf-8")
        written += 1

    return written


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
