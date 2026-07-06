# Brain Constellation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the placeholder `vault` screen with a beautiful, interactive constellation that positions every note by embedding meaning, drawn with glowing synapses, hover-bloom, and click-to-open.

**Architecture:** Python projects the existing embedding index (`vectors.npz`) to stable 2-D coordinates (UMAP, PCA fallback) cached as `layout.json`. A new `GET /v1/vault/graph` endpoint joins those coordinates with vault frontmatter (`related:` + wikilinks) into a nodes/edges/regions payload. The Electron renderer draws it on a Canvas 2-D surface, porting the techniques proven in the committed mockup.

**Tech Stack:** Python 3 (numpy, FastAPI, python-frontmatter, pytest), TypeScript/React (React Query, Canvas 2D, Vitest + React Testing Library).

## Global Constraints

- No new **required** Python dependency. UMAP (`umap-learn`) is an **optional** import; the PCA fallback must use only numpy (already a dependency). Copy verbatim: fallback method label is `"pca"`, UMAP label is `"umap"`.
- No new renderer dependency. The constellation renders on **Canvas 2D** (decision locked; no d3/sigma/three).
- Semantic artifacts live in `index_dir()` (`ghostbrain/semantic/index.py`): `~/ghostbrain/semantic/`, overridable via `GHOSTBRAIN_SEMANTIC_INDEX_DIR`. `layout.json` is written there, atomically, `chmod 0o600` — same pattern as `index.save()`.
- Vault notes live under `vault/20-contexts/<context>/…`; a note's **context** = the path segment after `20-contexts` (reuse `_ctx_from_rel` logic). Coordinates are normalised to a stable box `[-1000, 1000]` on both axes.
- Region colours are the single source of truth in Python and travel in the payload. Base palette (copy verbatim): poltergeist `#6EE7A8`, sanlam `#38BDF8`, personal `#A78BFA`, reducedrecipes `#FBBF24`, codeship `#F472B6`.
- Edge `kind` is exactly `"related"` or `"wikilink"`.
- API models are Pydantic `BaseModel` with `model_config = ConfigDict(populate_by_name=True)`; TypeScript mirrors are maintained by hand in `desktop/src/shared/api-types.ts`.
- All git commits end with the repo's trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- Run Python tests with `pytest` from repo root; renderer tests with `npm test --prefix desktop -- <file>`.

---

## File Structure

**Slice 1 — projection (Python)**
- Create `ghostbrain/semantic/projection.py` — pure projection + `layout.json` load/save/build.
- Modify `ghostbrain/semantic/refresh.py` — recompute the projection when vectors change.
- Create `ghostbrain/semantic/tests/test_projection.py`.

**Slice 2 — graph API (Python)**
- Create `ghostbrain/semantic/regions.py` — deterministic context→colour + label.
- Create `ghostbrain/api/models/graph.py` — `GraphNode`, `GraphEdge`, `GraphRegion`, `GraphResponse`.
- Create `ghostbrain/api/repo/graph.py` — `build_graph()`.
- Modify `ghostbrain/api/routes/vault.py` — add `GET /v1/vault/graph`.
- Create `ghostbrain/api/tests/test_graph_repo.py`, `ghostbrain/api/tests/test_graph_route.py`, `ghostbrain/semantic/tests/test_regions.py`.

**Slice 3 — renderer**
- Modify `desktop/src/shared/api-types.ts` — graph payload types.
- Modify `desktop/src/renderer/lib/api/hooks.ts` — `useVaultGraph()`.
- Create `desktop/src/renderer/lib/constellation-engine.ts` — pure camera/hit-test/model helpers.
- Create `desktop/src/renderer/components/BrainConstellation.tsx` — canvas host (ported from mockup).
- Modify `desktop/src/renderer/screens/vault.tsx` — host the constellation.
- Create `desktop/src/renderer/__tests__/constellation-engine.test.ts`, `useVaultGraph.test.tsx`, `VaultScreen.test.tsx`.

Reference for the port: `docs/superpowers/mockups/brain-constellation.html` (committed).

---

## Slice 1 — Projection

### Task 1: Projection function + layout cache

**Files:**
- Create: `ghostbrain/semantic/projection.py`
- Test: `ghostbrain/semantic/tests/test_projection.py`

**Interfaces:**
- Consumes: `ghostbrain.semantic.index` — `Index` (has `.vectors: np.ndarray | None`, `.entries: dict[str, IndexEntry]` where `IndexEntry.row: int`), `index_dir() -> Path`.
- Produces:
  - `project(vectors: np.ndarray) -> np.ndarray` — returns `(n, 2)` float array, each axis normalised into `[-1000.0, 1000.0]`. Uses UMAP if importable else PCA (numpy SVD).
  - `last_method() -> str` — `"umap"` or `"pca"`, reflecting the most recent `project()` call.
  - `Layout` dataclass: `{ model_name: str, method: str, positions: dict[str, list[float]] }`.
  - `build_layout(index: Index) -> Layout` — projects `index.vectors`, maps each `rel_path` (via its `row`) to `[x, y]`.
  - `layout_path() -> Path` (= `index_dir() / "layout.json"`), `save_layout(layout: Layout) -> None`, `load_layout() -> Layout | None`.

- [ ] **Step 1: Write the failing test for PCA projection shape + normalisation**

```python
# ghostbrain/semantic/tests/test_projection.py
import numpy as np

from ghostbrain.semantic.projection import project, last_method


def test_project_returns_normalised_2d():
    rng = np.random.default_rng(0)
    vecs = rng.standard_normal((20, 8)).astype("float32")
    out = project(vecs)
    assert out.shape == (20, 2)
    assert out.min() >= -1000.0 - 1e-6 and out.max() <= 1000.0 + 1e-6
    # Both axes actually use the range (not collapsed to a point).
    assert out[:, 0].ptp() > 100.0 and out[:, 1].ptp() > 100.0


def test_project_single_vector_is_origin():
    out = project(np.ones((1, 8), dtype="float32"))
    assert out.shape == (1, 2)
    assert np.allclose(out, 0.0)


def test_last_method_is_pca_without_umap(monkeypatch):
    # Force the UMAP import to fail so we exercise the numpy fallback.
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "umap":
            raise ImportError("no umap")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    project(np.random.default_rng(1).standard_normal((10, 8)).astype("float32"))
    assert last_method() == "pca"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest ghostbrain/semantic/tests/test_projection.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ghostbrain.semantic.projection'`

- [ ] **Step 3: Implement `projection.py` (project + normalise + method tracking)**

```python
# ghostbrain/semantic/projection.py
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

import numpy as np

from ghostbrain.semantic.index import Index, index_dir

log = logging.getLogger("ghostbrain.semantic.projection")

_COORD_RANGE = 1000.0
_last_method = "pca"


def last_method() -> str:
    return _last_method


def _normalise(coords: np.ndarray) -> np.ndarray:
    """Scale each axis into [-_COORD_RANGE, _COORD_RANGE], centred."""
    out = np.asarray(coords, dtype="float64")
    if out.shape[0] < 2:
        return np.zeros((out.shape[0], 2), dtype="float64")
    mins = out.min(axis=0)
    maxs = out.max(axis=0)
    span = np.where(maxs - mins == 0, 1.0, maxs - mins)
    scaled = (out - mins) / span            # 0..1
    return (scaled * 2.0 - 1.0) * _COORD_RANGE


def _pca_2d(vectors: np.ndarray) -> np.ndarray:
    centred = vectors - vectors.mean(axis=0, keepdims=True)
    # Economy SVD; first two right-singular vectors are the top components.
    _, _, vt = np.linalg.svd(centred, full_matrices=False)
    return centred @ vt[:2].T


def project(vectors: np.ndarray) -> np.ndarray:
    global _last_method
    vectors = np.asarray(vectors, dtype="float32")
    n = vectors.shape[0]
    if n < 2:
        _last_method = "pca"
        return np.zeros((n, 2), dtype="float64")
    try:
        import umap  # type: ignore
        reducer = umap.UMAP(n_components=2, n_neighbors=min(15, n - 1), metric="cosine")
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
    return Layout(
        model_name=str(data.get("model_name", "")),
        method=str(data.get("method", "pca")),
        positions={k: [float(v[0]), float(v[1])] for k, v in (data.get("positions") or {}).items()},
    )
```

- [ ] **Step 4: Run projection tests to verify they pass**

Run: `pytest ghostbrain/semantic/tests/test_projection.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Write the failing test for build/save/load round-trip**

```python
# append to ghostbrain/semantic/tests/test_projection.py
from ghostbrain.semantic.index import Index, IndexEntry
from ghostbrain.semantic.projection import build_layout, save_layout, load_layout, layout_path


def _index_with(rows: dict[str, int], dim: int = 8) -> Index:
    n = len(rows)
    rng = np.random.default_rng(2)
    vectors = rng.standard_normal((n, dim)).astype("float32")
    entries = {rel: IndexEntry(row=r, mtime=0.0, content_hash="h") for rel, r in rows.items()}
    return Index(entries=entries, vectors=vectors, model_name="m")


def test_build_and_roundtrip_layout(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTBRAIN_SEMANTIC_INDEX_DIR", str(tmp_path))
    idx = _index_with({"20-contexts/a/one.md": 0, "20-contexts/b/two.md": 1, "20-contexts/a/three.md": 2})
    layout = build_layout(idx)
    assert set(layout.positions.keys()) == set(idx.entries.keys())
    assert all(len(xy) == 2 for xy in layout.positions.values())
    save_layout(layout)
    assert layout_path().exists()
    loaded = load_layout()
    assert loaded is not None
    assert loaded.model_name == "m"
    assert set(loaded.positions.keys()) == set(idx.entries.keys())


def test_build_layout_empty_index_is_empty():
    layout = build_layout(Index(model_name="m"))
    assert layout.positions == {}
```

- [ ] **Step 6: Run to verify pass** — Run: `pytest ghostbrain/semantic/tests/test_projection.py -v` — Expected: PASS (5 tests)

- [ ] **Step 7: Commit**

```bash
git add ghostbrain/semantic/projection.py ghostbrain/semantic/tests/test_projection.py
git commit -m "feat(semantic): 2-D projection of the embedding index (UMAP/PCA) + layout cache

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 2: Recompute projection during refresh

**Files:**
- Modify: `ghostbrain/semantic/refresh.py` (the two `return RefreshResult(...)` sites after `save_index`)
- Test: `ghostbrain/semantic/tests/test_projection.py` (add integration-style test)

**Interfaces:**
- Consumes: `build_layout`, `save_layout` from Task 1.
- Produces: after a successful `refresh()` that has vectors, `layout.json` exists and covers the embedded notes. No signature change to `refresh()`.

- [ ] **Step 1: Write the failing test**

```python
# append to ghostbrain/semantic/tests/test_projection.py
def test_refresh_writes_layout(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTBRAIN_SEMANTIC_INDEX_DIR", str(tmp_path / "sem"))
    vault = tmp_path / "vault"
    (vault / "20-contexts" / "a").mkdir(parents=True)
    (vault / "20-contexts" / "b").mkdir(parents=True)
    (vault / "20-contexts" / "a" / "one.md").write_text("---\ntitle: One\n---\napples and oranges")
    (vault / "20-contexts" / "b" / "two.md").write_text("---\ntitle: Two\n---\nfruit basket")
    monkeypatch.setenv("VAULT_PATH", str(vault))

    class FakeEmbedder:
        def encode(self, texts, show_progress_bar=False):
            return np.random.default_rng(3).standard_normal((len(texts), 8)).astype("float32")

    from ghostbrain.semantic.refresh import refresh
    from ghostbrain.semantic.projection import load_layout

    refresh(embedder=FakeEmbedder(), min_similarity=-1.0)
    layout = load_layout()
    assert layout is not None
    assert len(layout.positions) == 2
```

- [ ] **Step 2: Run to verify it fails** — Run: `pytest ghostbrain/semantic/tests/test_projection.py::test_refresh_writes_layout -v` — Expected: FAIL (`load_layout()` returns `None`)

- [ ] **Step 3: Wire projection into `refresh.py`**

At the top of `refresh.py` add the import:

```python
from ghostbrain.semantic.projection import build_layout, save_layout
```

Add a helper near the other internals:

```python
def _refresh_layout(index: Index) -> None:
    """Recompute + persist the 2-D layout. Never fails the refresh."""
    try:
        save_layout(build_layout(index))
    except Exception as e:  # noqa: BLE001
        log.warning("layout projection failed: %s", e)
```

Call it right before **both** `return RefreshResult(...)` statements (the early-return at the `not paths_to_score or index.vectors is None` guard, and the final return). At the early guard, place it after `save_index(index)`:

```python
    if not paths_to_score or index.vectors is None:
        save_index(index)
        _refresh_layout(index)
        return RefreshResult(...)   # unchanged args
```

And after the final `save_index(index)`:

```python
    save_index(index)
    _refresh_layout(index)
    return RefreshResult(...)       # unchanged args
```

- [ ] **Step 4: Run to verify pass** — Run: `pytest ghostbrain/semantic/tests/test_projection.py -v` — Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/semantic/refresh.py ghostbrain/semantic/tests/test_projection.py
git commit -m "feat(semantic): recompute 2-D layout on index refresh

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Slice 2 — Graph API

### Task 3: Region palette

**Files:**
- Create: `ghostbrain/semantic/regions.py`
- Test: `ghostbrain/semantic/tests/test_regions.py`

**Interfaces:**
- Produces:
  - `region_color(context: str) -> str` — hex string. Known contexts map to the base palette; unknown ones get a deterministic colour from an extended ramp (stable per context string).
  - `region_label(context: str) -> str` — human label (`context or "unfiled"`).

- [ ] **Step 1: Write the failing test**

```python
# ghostbrain/semantic/tests/test_regions.py
from ghostbrain.semantic.regions import region_color, region_label


def test_known_contexts_use_base_palette():
    assert region_color("poltergeist") == "#6EE7A8"
    assert region_color("sanlam") == "#38BDF8"
    assert region_color("personal") == "#A78BFA"


def test_unknown_context_is_deterministic_hex():
    a = region_color("reducedrecipes-clone")
    b = region_color("reducedrecipes-clone")
    assert a == b and a.startswith("#") and len(a) == 7


def test_label_falls_back_to_unfiled():
    assert region_label("") == "unfiled"
    assert region_label("sanlam") == "sanlam"
```

- [ ] **Step 2: Run to verify it fails** — Run: `pytest ghostbrain/semantic/tests/test_regions.py -v` — Expected: FAIL (import error)

- [ ] **Step 3: Implement `regions.py`**

```python
# ghostbrain/semantic/regions.py
"""Single source of truth for context → region colour + label."""
from __future__ import annotations

import hashlib

_BASE = {
    "poltergeist": "#6EE7A8",
    "sanlam": "#38BDF8",
    "personal": "#A78BFA",
    "reducedrecipes": "#FBBF24",
    "codeship": "#F472B6",
}

# Extended ramp for unknown contexts: even lightness, varied hue.
_RAMP = ["#5EEAD4", "#818CF8", "#F0ABFC", "#FB7185", "#FCD34D",
         "#4ADE80", "#22D3EE", "#C084FC", "#F87171", "#A3E635"]


def region_color(context: str) -> str:
    if context in _BASE:
        return _BASE[context]
    h = int(hashlib.sha1(context.encode("utf-8")).hexdigest(), 16)
    return _RAMP[h % len(_RAMP)]


def region_label(context: str) -> str:
    return context or "unfiled"
```

- [ ] **Step 4: Run to verify pass** — Run: `pytest ghostbrain/semantic/tests/test_regions.py -v` — Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/semantic/regions.py ghostbrain/semantic/tests/test_regions.py
git commit -m "feat(semantic): deterministic region palette

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 4: Graph builder + models

**Files:**
- Create: `ghostbrain/api/models/graph.py`
- Create: `ghostbrain/api/repo/graph.py`
- Test: `ghostbrain/api/tests/test_graph_repo.py`

**Interfaces:**
- Consumes: `load_layout` (Task 1), `region_color`/`region_label` (Task 3), `vault_path()` (`ghostbrain.paths`), `frontmatter`.
- Produces:
  - Models: `GraphNode(path, title, context, tags, x, y, degree, updated)`, `GraphEdge(source, target, weight, kind)`, `GraphRegion(id, label, color, count)`, `GraphResponse(nodes, edges, regions)`.
  - `build_graph() -> dict` — walks `vault/20-contexts/**/*.md`, joins layout positions, parses `related:` (→ `kind="related"`) and `parent:` + inline `[[…]]` (→ `kind="wikilink"`) into edges, dedups edges, computes degree, groups regions. Notes missing a layout position get a deterministic fallback `(x, y)` and are still included.

- [ ] **Step 1: Write the failing test**

```python
# ghostbrain/api/tests/test_graph_repo.py
from pathlib import Path

from ghostbrain.api.repo.graph import build_graph


def _note(vault: Path, rel: str, body: str = "", **meta) -> None:
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    fm = "".join(f"{k}: {v}\n" for k, v in meta.items())
    p.write_text(f"---\n{fm}---\n{body}", encoding="utf-8")


def test_build_graph_nodes_edges_regions(tmp_vault: Path, monkeypatch, tmp_path):
    monkeypatch.setenv("GHOSTBRAIN_SEMANTIC_INDEX_DIR", str(tmp_path / "sem"))
    _note(tmp_vault, "20-contexts/sanlam/a.md", title="A")
    _note(tmp_vault, "20-contexts/sanlam/b.md", title="B")
    # a relates to b (semantic edge)
    (tmp_vault / "20-contexts/sanlam/a.md").write_text(
        "---\ntitle: A\nrelated:\n- '[[20-contexts/sanlam/b]]'\n---\nbody", encoding="utf-8")

    graph = build_graph()
    paths = {n["path"] for n in graph["nodes"]}
    assert paths == {"20-contexts/sanlam/a.md", "20-contexts/sanlam/b.md"}
    assert all("x" in n and "y" in n for n in graph["nodes"])
    edges = graph["edges"]
    assert any(e["kind"] == "related"
               and {e["source"], e["target"]} == {"20-contexts/sanlam/a.md", "20-contexts/sanlam/b.md"}
               for e in edges)
    regions = {r["id"]: r for r in graph["regions"]}
    assert regions["sanlam"]["count"] == 2
    assert regions["sanlam"]["color"] == "#38BDF8"


def test_build_graph_empty_vault(tmp_vault: Path, monkeypatch, tmp_path):
    monkeypatch.setenv("GHOSTBRAIN_SEMANTIC_INDEX_DIR", str(tmp_path / "sem"))
    graph = build_graph()
    assert graph == {"nodes": [], "edges": [], "regions": []}


def test_wikilink_parent_edge(tmp_vault: Path, monkeypatch, tmp_path):
    monkeypatch.setenv("GHOSTBRAIN_SEMANTIC_INDEX_DIR", str(tmp_path / "sem"))
    _note(tmp_vault, "20-contexts/sanlam/parent.md", title="P")
    (tmp_vault / "20-contexts/sanlam/child.md").write_text(
        "---\ntitle: C\nparent: '[[20-contexts/sanlam/parent]]'\n---\nbody", encoding="utf-8")
    graph = build_graph()
    assert any(e["kind"] == "wikilink" for e in graph["edges"])
```

- [ ] **Step 2: Run to verify it fails** — Run: `pytest ghostbrain/api/tests/test_graph_repo.py -v` — Expected: FAIL (import error)

- [ ] **Step 3: Implement the models**

```python
# ghostbrain/api/models/graph.py
"""Vault graph payload."""
from pydantic import BaseModel, ConfigDict


class GraphNode(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    path: str
    title: str
    context: str
    tags: list[str]
    x: float
    y: float
    degree: int
    updated: str | None


class GraphEdge(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    source: str
    target: str
    weight: float
    kind: str  # "related" | "wikilink"


class GraphRegion(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    label: str
    color: str
    count: int


class GraphResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    regions: list[GraphRegion]
```

- [ ] **Step 4: Implement the builder**

```python
# ghostbrain/api/repo/graph.py
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
```

- [ ] **Step 5: Run to verify pass** — Run: `pytest ghostbrain/api/tests/test_graph_repo.py -v` — Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add ghostbrain/api/models/graph.py ghostbrain/api/repo/graph.py ghostbrain/api/tests/test_graph_repo.py
git commit -m "feat(api): vault graph builder (nodes by embedding, related/wikilink edges)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 5: Graph endpoint

**Files:**
- Modify: `ghostbrain/api/routes/vault.py`
- Test: `ghostbrain/api/tests/test_graph_route.py`

**Interfaces:**
- Consumes: `build_graph` (Task 4), `GraphResponse` (Task 4). The `vault` router already exists with `prefix="/v1/vault"` and is already registered in `ghostbrain/api/main.py` — no `main.py` change needed.
- Produces: `GET /v1/vault/graph` → `GraphResponse`.

- [ ] **Step 1: Write the failing test**

```python
# ghostbrain/api/tests/test_graph_route.py
from pathlib import Path

from fastapi.testclient import TestClient


def test_graph_endpoint_returns_shape(client: TestClient, auth_headers, tmp_vault: Path, monkeypatch, tmp_path):
    monkeypatch.setenv("GHOSTBRAIN_SEMANTIC_INDEX_DIR", str(tmp_path / "sem"))
    d = tmp_vault / "20-contexts" / "sanlam"
    d.mkdir(parents=True)
    (d / "a.md").write_text("---\ntitle: A\n---\nbody", encoding="utf-8")
    resp = client.get("/v1/vault/graph", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert {"nodes", "edges", "regions"} <= data.keys()
    assert data["nodes"][0]["path"] == "20-contexts/sanlam/a.md"


def test_graph_endpoint_empty(client: TestClient, auth_headers, monkeypatch, tmp_path):
    monkeypatch.setenv("GHOSTBRAIN_SEMANTIC_INDEX_DIR", str(tmp_path / "sem"))
    resp = client.get("/v1/vault/graph", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"nodes": [], "edges": [], "regions": []}
```

- [ ] **Step 2: Run to verify it fails** — Run: `pytest ghostbrain/api/tests/test_graph_route.py -v` — Expected: FAIL (404)

- [ ] **Step 3: Add the route** — edit `ghostbrain/api/routes/vault.py`:

```python
from ghostbrain.api.models.graph import GraphResponse
from ghostbrain.api.repo.graph import build_graph
# ... existing imports/router ...


@router.get("/graph", response_model=GraphResponse)
def vault_graph() -> dict:
    return build_graph()
```

- [ ] **Step 4: Run to verify pass** — Run: `pytest ghostbrain/api/tests/test_graph_route.py -v` — Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/routes/vault.py ghostbrain/api/tests/test_graph_route.py
git commit -m "feat(api): GET /v1/vault/graph

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Slice 3 — Renderer

### Task 6: Types + `useVaultGraph` hook

**Files:**
- Modify: `desktop/src/shared/api-types.ts`
- Modify: `desktop/src/renderer/lib/api/hooks.ts`
- Test: `desktop/src/renderer/__tests__/useVaultGraph.test.tsx`

**Interfaces:**
- Produces: TS types `VaultGraphNode`, `VaultGraphEdge`, `VaultGraphRegion`, `VaultGraph`; hook `useVaultGraph()` returning a React Query result of `VaultGraph`.

- [ ] **Step 1: Add types to `api-types.ts`**

```typescript
export interface VaultGraphNode {
  path: string;
  title: string;
  context: string;
  tags: string[];
  x: number;
  y: number;
  degree: number;
  updated: string | null;
}
export interface VaultGraphEdge {
  source: string;
  target: string;
  weight: number;
  kind: 'related' | 'wikilink';
}
export interface VaultGraphRegion { id: string; label: string; color: string; count: number; }
export interface VaultGraph {
  nodes: VaultGraphNode[];
  edges: VaultGraphEdge[];
  regions: VaultGraphRegion[];
}
```

- [ ] **Step 2: Write the failing hook test**

```tsx
// desktop/src/renderer/__tests__/useVaultGraph.test.tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useVaultGraph } from '../lib/api/hooks';

const request = vi.fn();
beforeEach(() => {
  request.mockReset();
  (globalThis as any).window = Object.assign((globalThis as any).window ?? {}, {
    gb: { api: { request } },
  });
});

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe('useVaultGraph', () => {
  it('fetches the vault graph', async () => {
    request.mockResolvedValue({ ok: true, data: { nodes: [], edges: [], regions: [] } });
    const { result } = renderHook(() => useVaultGraph(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(request).toHaveBeenCalledWith('GET', '/v1/vault/graph');
    expect(result.current.data).toEqual({ nodes: [], edges: [], regions: [] });
  });
});
```

- [ ] **Step 3: Run to verify it fails** — Run: `npm test --prefix desktop -- useVaultGraph` — Expected: FAIL (`useVaultGraph` not exported)

- [ ] **Step 4: Add the hook to `hooks.ts`**

Add `VaultGraph` to the existing `import type { … } from` block from `../../shared/api-types`, then:

```typescript
export function useVaultGraph() {
  return useQuery({
    queryKey: ['vault', 'graph'],
    queryFn: () => get<VaultGraph>('/v1/vault/graph'),
    staleTime: 60_000,
  });
}
```

- [ ] **Step 5: Run to verify pass** — Run: `npm test --prefix desktop -- useVaultGraph` — Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add desktop/src/shared/api-types.ts desktop/src/renderer/lib/api/hooks.ts desktop/src/renderer/__tests__/useVaultGraph.test.tsx
git commit -m "feat(desktop): useVaultGraph hook + graph types

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 7: Pure constellation engine

**Files:**
- Create: `desktop/src/renderer/lib/constellation-engine.ts`
- Test: `desktop/src/renderer/__tests__/constellation-engine.test.ts`

**Interfaces:**
- Consumes: `VaultGraph` types (Task 6).
- Produces (pure, no DOM):
  - `type Camera = { x: number; y: number; scale: number }`.
  - `toScreen(cam, w, h, wx, wy): [number, number]` and `toWorld(cam, w, h, sx, sy): [number, number]` (inverses).
  - `fitCamera(nodes, w, h): Camera` — centres + scales to frame all nodes, clamped to `[0.7, 1.5]`.
  - `hitTest(cam, w, h, nodes, sx, sy): number` — index of nearest node within a screen-space threshold, else `-1`.
  - `buildAdjacency(graph): Map<string, string[]>` — path → neighbour paths.

- [ ] **Step 1: Write the failing test**

```typescript
// desktop/src/renderer/__tests__/constellation-engine.test.ts
import { describe, it, expect } from 'vitest';
import { toScreen, toWorld, fitCamera, hitTest, buildAdjacency } from '../lib/constellation-engine';
import type { VaultGraph } from '../../shared/api-types';

const node = (path: string, x: number, y: number) =>
  ({ path, title: path, context: 'a', tags: [], x, y, degree: 0, updated: null });

describe('constellation-engine', () => {
  it('toScreen and toWorld are inverses', () => {
    const cam = { x: 10, y: -5, scale: 0.8 };
    const [sx, sy] = toScreen(cam, 800, 600, 42, 17);
    const [wx, wy] = toWorld(cam, 800, 600, sx, sy);
    expect(wx).toBeCloseTo(42);
    expect(wy).toBeCloseTo(17);
  });

  it('fitCamera centres on the node cloud', () => {
    const cam = fitCamera([node('a', -100, -100), node('b', 100, 100)], 800, 600);
    expect(cam.x).toBeCloseTo(0);
    expect(cam.y).toBeCloseTo(0);
    expect(cam.scale).toBeGreaterThanOrEqual(0.7);
    expect(cam.scale).toBeLessThanOrEqual(1.5);
  });

  it('hitTest finds the node under the cursor', () => {
    const cam = { x: 0, y: 0, scale: 1 };
    const nodes = [node('a', 0, 0), node('b', 500, 0)];
    const [sx, sy] = toScreen(cam, 800, 600, 0, 0);
    expect(hitTest(cam, 800, 600, nodes, sx, sy)).toBe(0);
    expect(hitTest(cam, 800, 600, nodes, 5, 5)).toBe(-1); // empty gap → miss
  });

  it('buildAdjacency maps neighbours both ways', () => {
    const graph: VaultGraph = {
      nodes: [node('a', 0, 0), node('b', 1, 1)],
      edges: [{ source: 'a', target: 'b', weight: 0.7, kind: 'related' }],
      regions: [],
    };
    const adj = buildAdjacency(graph);
    expect(adj.get('a')).toEqual(['b']);
    expect(adj.get('b')).toEqual(['a']);
  });
});
```

- [ ] **Step 2: Run to verify it fails** — Run: `npm test --prefix desktop -- constellation-engine` — Expected: FAIL (module missing)

- [ ] **Step 3: Implement `constellation-engine.ts`**

```typescript
// desktop/src/renderer/lib/constellation-engine.ts
import type { VaultGraph, VaultGraphNode } from '../../shared/api-types';

export type Camera = { x: number; y: number; scale: number };

export function toScreen(cam: Camera, w: number, h: number, wx: number, wy: number): [number, number] {
  return [(wx - cam.x) * cam.scale + w / 2, (wy - cam.y) * cam.scale + h / 2];
}

export function toWorld(cam: Camera, w: number, h: number, sx: number, sy: number): [number, number] {
  return [(sx - w / 2) / cam.scale + cam.x, (sy - h / 2) / cam.scale + cam.y];
}

export function fitCamera(nodes: VaultGraphNode[], w: number, h: number): Camera {
  if (nodes.length === 0) return { x: 0, y: 0, scale: 1 };
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const n of nodes) {
    minX = Math.min(minX, n.x); minY = Math.min(minY, n.y);
    maxX = Math.max(maxX, n.x); maxY = Math.max(maxY, n.y);
  }
  const pad = 70;
  const scale = Math.max(0.7, Math.min(1.5,
    Math.min(w / (maxX - minX + pad * 2), h / (maxY - minY + pad * 2)) * 1.04));
  return { x: (minX + maxX) / 2, y: (minY + maxY) / 2, scale };
}

export function hitTest(cam: Camera, w: number, h: number, nodes: VaultGraphNode[], sx: number, sy: number): number {
  let best = -1, bestD = Infinity;
  for (let i = 0; i < nodes.length; i++) {
    const [x, y] = toScreen(cam, w, h, nodes[i].x, nodes[i].y);
    const d = (x - sx) ** 2 + (y - sy) ** 2;
    const r = Math.max(9, (2.7 + Math.min(nodes[i].degree, 14) * 0.62) * cam.scale + 7);
    if (d < r * r && d < bestD) { bestD = d; best = i; }
  }
  return best;
}

export function buildAdjacency(graph: VaultGraph): Map<string, string[]> {
  const adj = new Map<string, string[]>();
  const push = (a: string, b: string) => {
    const list = adj.get(a) ?? [];
    if (!list.includes(b)) list.push(b);
    adj.set(a, list);
  };
  for (const e of graph.edges) { push(e.source, e.target); push(e.target, e.source); }
  return adj;
}
```

- [ ] **Step 4: Run to verify pass** — Run: `npm test --prefix desktop -- constellation-engine` — Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add desktop/src/renderer/lib/constellation-engine.ts desktop/src/renderer/__tests__/constellation-engine.test.ts
git commit -m "feat(desktop): pure constellation engine (camera, hit-test, adjacency)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 8: BrainConstellation component (port from mockup)

**Files:**
- Create: `desktop/src/renderer/components/BrainConstellation.tsx`
- Reference: `docs/superpowers/mockups/brain-constellation.html` (committed) — the render loop, glow sprites, additive blending, wall-clock animation clock, hover/select dimming, and note-card markup are all there; port them.

**Interfaces:**
- Consumes: `useVaultGraph()` (Task 6); `Camera`, `toScreen`, `toWorld`, `fitCamera`, `hitTest`, `buildAdjacency` (Task 7); `VaultGraph` types; `window.gb.shell.openPath` (already used by `screens/vault.tsx`).
- Produces: `export function BrainConstellation()` — a self-contained canvas + overlays element.

Port rules (translate the mockup's IIFE into a React component):
- Data source: replace the mockup's synthetic `LOBES`/node generation with the `useVaultGraph()` payload. Node positions come straight from `node.x/node.y` (already projected server-side) — **do not** generate positions client-side. Region colour comes from `graph.regions` (build a `Map<contextId, color>`); glow sprites are created per distinct region colour.
- Coordinates/hit-testing: use the engine functions from Task 7 instead of the inline copies in the mockup.
- Animation clock: keep the mockup's **wall-clock** `appearT`/drift (`(now - startT)/1500`) — it is the fix for background-tab rAF throttling; do not revert to per-frame accumulation.
- Reduced motion: keep the mockup's `prefers-reduced-motion` gate (freeze drift/twinkle/signals).
- Canvas lifecycle in React: create the canvas via `ref`; start the render loop in a `useEffect` that returns a cleanup cancelling the `requestAnimationFrame` and removing listeners; recreate glow sprites and refit the camera when the graph payload changes.
- Click behaviour: on a node click, open the note on disk via the existing bridge — `window.gb.shell.openPath(`${vaultPath}/${node.path}`)` (get `vaultPath` from `useSettings((s) => s.vaultPath)` as `screens/vault.tsx` does). Also open the side card (title, path, excerpt-from-first-body-line if available else omit, related-by-meaning list from adjacency with weights). The card's "open in vault" affordance calls the same `openPath`.
- Empty state: when `graph.nodes.length === 0`, render the existing "your vault is on disk" empty message instead of a blank canvas.
- Chrome styling: use existing tokens/utility classes already in the renderer (as `screens/vault.tsx` does); the canvas ground stays dark by design.

- [ ] **Step 1: Create the component** by porting the mockup per the rules above, wired to `useVaultGraph()` and the engine. (No new test here — the pure logic is covered by Task 7; Task 9 adds a screen smoke test. Keep imperative canvas code thin and delegate math to the engine.)

- [ ] **Step 2: Type-check** — Run: `npm run typecheck --prefix desktop` (or the repo's configured TS check) — Expected: no errors in `BrainConstellation.tsx`.

- [ ] **Step 3: Commit**

```bash
git add desktop/src/renderer/components/BrainConstellation.tsx
git commit -m "feat(desktop): BrainConstellation canvas component (ported from mockup)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 9: Host the constellation in the vault screen

**Files:**
- Modify: `desktop/src/renderer/screens/vault.tsx`
- Test: `desktop/src/renderer/__tests__/VaultScreen.test.tsx`

**Interfaces:**
- Consumes: `BrainConstellation` (Task 8), `useVaultGraph` (Task 6).
- Produces: `VaultScreen` renders `<BrainConstellation />` (which owns the empty state) and keeps an "open vault folder" affordance available (e.g. in the top bar), preserving the existing `window.gb.shell.openPath(vaultPath)` action.

- [ ] **Step 1: Write the failing test**

```tsx
// desktop/src/renderer/__tests__/VaultScreen.test.tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { VaultScreen } from '../screens/vault';

const request = vi.fn();
beforeEach(() => {
  request.mockReset();
  request.mockResolvedValue({ ok: true, data: { nodes: [], edges: [], regions: [] } });
  (globalThis as any).window = Object.assign((globalThis as any).window ?? {}, {
    gb: { api: { request }, shell: { openPath: vi.fn().mockResolvedValue({ ok: true }) } },
  });
});

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><VaultScreen /></QueryClientProvider>);
}

describe('VaultScreen', () => {
  it('requests the vault graph and shows the empty state when there are no notes', async () => {
    renderScreen();
    expect(await screen.findByText(/your vault is on disk/i)).toBeInTheDocument();
    expect(request).toHaveBeenCalledWith('GET', '/v1/vault/graph');
  });
});
```

- [ ] **Step 2: Run to verify it fails** — Run: `npm test --prefix desktop -- VaultScreen` — Expected: FAIL (no graph request / text mismatch)

- [ ] **Step 3: Rewrite `vault.tsx`** to host `<BrainConstellation />` under the existing `TopBar`, keeping the "open vault folder" button in the bar. The empty-state copy ("your vault is on disk") must remain reachable (rendered by `BrainConstellation` when `nodes.length === 0`).

- [ ] **Step 4: Run to verify pass** — Run: `npm test --prefix desktop -- VaultScreen` — Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add desktop/src/renderer/screens/vault.tsx desktop/src/renderer/__tests__/VaultScreen.test.tsx
git commit -m "feat(desktop): vault screen hosts the brain constellation

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

### Task 10: Full verification pass

- [ ] **Step 1: Python suite** — Run: `pytest ghostbrain/semantic/tests ghostbrain/api/tests -q` — Expected: all pass.
- [ ] **Step 2: Renderer suite** — Run: `npm test --prefix desktop` — Expected: all pass.
- [ ] **Step 3: Manual smoke** — with a real (or seeded) vault, run `python -m ghostbrain.semantic.main` (or the existing refresh CLI) to produce `layout.json`, launch the desktop app, open the **vault** screen, and confirm: constellation renders, hover blooms a node, clicking a node opens the note on disk and the side card, region legend isolates. Use the mockup as the visual acceptance bar.
- [ ] **Step 4: Commit** any fixes found during smoke.

---

## Deferred (not in this plan)

- **Slice 4 — hybrid physics:** a light force layer applied on hover/drag over the semantic base positions (the "C" option). Additive; revisit only if more interactivity is wanted after living with the static-semantic layout.
- Payload caching (ETag/last-built) — add if `build_graph()` latency becomes noticeable on a large vault; the builder is a pure function of the vault + `layout.json`, so caching is a clean drop-in later.
- In-app `NoteView` navigation on click (instead of opening on disk) — v1 opens on disk to match the vault screen's existing "we feed your editor" ethos.

---

## Self-Review

- **Spec coverage:** projection+cache (Tasks 1–2 ✓), graph API + shared palette (Tasks 3–5 ✓), renderer with hover/click/isolate (Tasks 6–9 ✓), always-dark canvas + reduced-motion + wall-clock clock (Task 8 port rules ✓), empty/fallback/large-vault edge cases (builder fallback + empty tests + deferred caching ✓), testing across all three layers (✓). Physics is explicitly deferred per spec.
- **Placeholders:** none — every code step carries real code; the one "port" task (8) references the committed mockup and enumerates exact translation rules rather than hand-waving.
- **Type consistency:** `build_graph()` dict keys match `GraphResponse` fields; TS `VaultGraph*` mirror the Pydantic models; engine signatures used in Task 8 match Task 7 definitions; `region_color`/`region_label` names consistent across Tasks 3–4.
