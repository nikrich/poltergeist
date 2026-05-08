"""Embedding-index lifecycle.

The index lives at ``~/ghostbrain/semantic/`` and is split for safety:
- ``vectors.npz`` — numpy archive of the embedding matrix (compressed).
- ``index.json`` — metadata per note: ``{path: {mtime, hash, row}}``.

Splitting avoids pickle (no arbitrary-code-execution surface on load) and
keeps the metadata human-readable for debugging.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger("ghostbrain.semantic.index")

DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def index_dir() -> Path:
    raw = os.environ.get("GHOSTBRAIN_SEMANTIC_INDEX_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / "ghostbrain" / "semantic").resolve()


def vectors_path() -> Path:
    return index_dir() / "vectors.npz"


def metadata_path() -> Path:
    return index_dir() / "index.json"


@dataclasses.dataclass
class IndexEntry:
    """Per-note metadata: where to find the row + freshness markers."""

    row: int        # row index into the vectors matrix
    mtime: float
    content_hash: str


@dataclasses.dataclass
class Index:
    entries: dict[str, IndexEntry] = dataclasses.field(default_factory=dict)
    vectors: Any = None  # numpy array (n_notes × dim) or None when empty
    model_name: str = DEFAULT_MODEL_NAME

    def get(self, key: str) -> IndexEntry | None:
        return self.entries.get(key)

    def keys(self) -> Iterable[str]:
        return self.entries.keys()


def load() -> Index:
    """Load the index from disk. Empty Index when no files exist."""
    meta_p = metadata_path()
    vec_p = vectors_path()
    if not meta_p.exists():
        return Index()

    try:
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.warning("index metadata unreadable, starting fresh: %s", e)
        return Index()

    entries = {
        path: IndexEntry(
            row=int(rec["row"]),
            mtime=float(rec.get("mtime", 0.0)),
            content_hash=str(rec.get("hash", "")),
        )
        for path, rec in (meta.get("entries") or {}).items()
    }
    model_name = str(meta.get("model_name") or DEFAULT_MODEL_NAME)

    vectors = None
    if vec_p.exists():
        # Lazy-import numpy so non-semantic code paths don't pay the import.
        import numpy as np
        try:
            with np.load(vec_p) as data:
                vectors = data["vectors"]
        except Exception as e:  # noqa: BLE001
            log.warning("vectors archive unreadable: %s — starting fresh", e)
            entries = {}
            vectors = None

    return Index(entries=entries, vectors=vectors, model_name=model_name)


def save(index: Index) -> None:
    import numpy as np

    target_dir = index_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    # Vectors → .npz. ``np.savez_compressed`` auto-appends ``.npz`` to its
    # filename argument, so we use BytesIO + atomic file-replace instead of
    # writing directly. (This also keeps tests deterministic.)
    if index.vectors is not None and len(index.entries):
        import io
        buf = io.BytesIO()
        np.savez_compressed(buf, vectors=index.vectors)
        target_dir.mkdir(parents=True, exist_ok=True)
        tmp_vec = vectors_path().with_name(vectors_path().name + ".tmp")
        tmp_vec.write_bytes(buf.getvalue())
        os.replace(tmp_vec, vectors_path())
        os.chmod(vectors_path(), 0o600)

    # Metadata → JSON.
    payload = {
        "model_name": index.model_name,
        "entries": {
            path: {
                "row": e.row,
                "mtime": e.mtime,
                "hash": e.content_hash,
            }
            for path, e in index.entries.items()
        },
    }
    tmp_meta = metadata_path().with_suffix(".json.tmp")
    tmp_meta.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp_meta, metadata_path())
    os.chmod(metadata_path(), 0o600)


def text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:12]
