"""Project the embedding matrix to stable 2-D coordinates.

UMAP when available (nicer clusters); numpy-SVD PCA otherwise (zero extra
deps). Output is normalised into a fixed [-1000, 1000] box on both axes so
the renderer receives stable, framing-friendly coordinates.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from ghostbrain.semantic.index import Index, index_dir

if TYPE_CHECKING:
    import numpy as np

log = logging.getLogger("ghostbrain.semantic.projection")

_COORD_RANGE = 1000.0
_last_method = "pca"


def last_method() -> str:
    return _last_method


def _normalise(coords: np.ndarray) -> np.ndarray:
    """Scale each axis into [-_COORD_RANGE, _COORD_RANGE], centred."""
    import numpy as np

    out = np.asarray(coords, dtype="float64")
    if out.shape[0] < 2:
        return np.zeros((out.shape[0], 2), dtype="float64")
    mins = out.min(axis=0)
    maxs = out.max(axis=0)
    span = np.where(maxs - mins == 0, 1.0, maxs - mins)
    scaled = (out - mins) / span            # 0..1
    return (scaled * 2.0 - 1.0) * _COORD_RANGE


def _pca_2d(vectors: np.ndarray) -> np.ndarray:
    import numpy as np  # noqa: F401 — np.linalg below

    centred = vectors - vectors.mean(axis=0, keepdims=True)
    # Economy SVD; first two right-singular vectors are the top components.
    _, _, vt = np.linalg.svd(centred, full_matrices=False)
    return centred @ vt[:2].T


def project(vectors: np.ndarray) -> np.ndarray:
    # numpy comes from the optional [semantic] extra; import lazily so the API
    # (which only reads layout.json via load_layout) never requires it.
    import numpy as np

    global _last_method
    vectors = np.asarray(vectors, dtype="float32")
    n = vectors.shape[0]
    if n < 2:
        _last_method = "pca"
        return np.zeros((n, 2), dtype="float64")
    try:
        import umap  # type: ignore
        reducer = umap.UMAP(
            n_components=2, n_neighbors=min(15, n - 1), metric="cosine", random_state=42
        )
        coords = reducer.fit_transform(vectors)
        _last_method = "umap"
    except Exception as e:  # noqa: BLE001 — any UMAP failure → PCA
        if not isinstance(e, ImportError):
            log.warning("UMAP failed (%s); falling back to PCA", e)
        coords = _pca_2d(vectors)
        _last_method = "pca"
    return _normalise(coords)


@dataclasses.dataclass
class Layout:
    model_name: str
    method: str
    positions: dict[str, list[float]]


def layout_path() -> Path:
    return index_dir() / "layout.json"


def build_layout(index: Index) -> Layout:
    if index.vectors is None or len(index.entries) == 0:
        return Layout(model_name=index.model_name, method="pca", positions={})
    coords = project(index.vectors)
    positions = {
        rel: [round(float(coords[entry.row, 0]), 2), round(float(coords[entry.row, 1]), 2)]
        for rel, entry in index.entries.items()
        if entry.row < coords.shape[0]
    }
    return Layout(model_name=index.model_name, method=last_method(), positions=positions)


def save_layout(layout: Layout) -> None:
    target = layout_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"model_name": layout.model_name, "method": layout.method, "positions": layout.positions}
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, target)
    os.chmod(target, 0o600)


def load_layout() -> Layout | None:
    p = layout_path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.warning("layout.json unreadable: %s", e)
        return None

    if not isinstance(data, dict):
        log.warning("layout.json malformed: expected an object, got %s", type(data).__name__)
        return None

    raw_positions = data.get("positions") or {}
    if not isinstance(raw_positions, dict):
        log.warning(
            "layout.json malformed: 'positions' expected an object, got %s",
            type(raw_positions).__name__,
        )
        return None

    positions: dict[str, list[float]] = {}
    for k, v in raw_positions.items():
        try:
            if not isinstance(v, (list, tuple)) or len(v) != 2:
                raise ValueError("entry is not a 2-item [x, y] list")
            positions[k] = [float(v[0]), float(v[1])]
        except (TypeError, ValueError) as e:
            log.warning("layout.json malformed: skipping entry %r (%s)", k, e)
            continue

    return Layout(
        model_name=str(data.get("model_name", "")),
        method=str(data.get("method", "pca")),
        positions=positions,
    )
