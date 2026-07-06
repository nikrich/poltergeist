import numpy as np

from ghostbrain.semantic.projection import project, last_method


def test_project_returns_normalised_2d():
    rng = np.random.default_rng(0)
    vecs = rng.standard_normal((20, 8)).astype("float32")
    out = project(vecs)
    assert out.shape == (20, 2)
    assert out.min() >= -1000.0 - 1e-6 and out.max() <= 1000.0 + 1e-6
    # Both axes actually use the range (not collapsed to a point).
    assert np.ptp(out[:, 0]) > 100.0 and np.ptp(out[:, 1]) > 100.0


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
