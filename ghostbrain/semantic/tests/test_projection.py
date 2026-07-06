import json

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


def test_load_layout_returns_none_when_positions_wrong_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTBRAIN_SEMANTIC_INDEX_DIR", str(tmp_path))
    layout_path().parent.mkdir(parents=True, exist_ok=True)
    layout_path().write_text(json.dumps({"model_name": "m", "method": "pca", "positions": "nope"}))
    assert load_layout() is None


def test_load_layout_skips_malformed_entries(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTBRAIN_SEMANTIC_INDEX_DIR", str(tmp_path))
    layout_path().parent.mkdir(parents=True, exist_ok=True)
    layout_path().write_text(
        json.dumps(
            {
                "model_name": "m",
                "method": "pca",
                "positions": {
                    "good.md": [1.0, 2.0],
                    "bad-scalar.md": "nope",
                    "bad-len.md": [1.0, 2.0, 3.0],
                    "bad-type.md": ["x", "y"],
                },
            }
        )
    )
    loaded = load_layout()
    assert loaded is not None
    assert loaded.positions == {"good.md": [1.0, 2.0]}


def test_load_layout_returns_none_when_top_level_not_object(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTBRAIN_SEMANTIC_INDEX_DIR", str(tmp_path))
    layout_path().parent.mkdir(parents=True, exist_ok=True)
    layout_path().write_text(json.dumps([1, 2, 3]))
    assert load_layout() is None


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


def test_refresh_skips_layout_recompute_when_nothing_new(tmp_path, monkeypatch):
    """Second refresh() with no content changes must not recompute the
    projection — the layout file's positions should be byte-identical
    (same object round-tripped, not rebuilt from a fresh random_state)."""
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
    from ghostbrain.semantic.projection import layout_path

    refresh(embedder=FakeEmbedder(), min_similarity=-1.0)
    first_mtime = layout_path().stat().st_mtime_ns
    first_text = layout_path().read_text(encoding="utf-8")

    # Nothing changed on disk, so the second run should embed nothing and
    # must leave the layout file untouched (no recompute, no rewrite).
    refresh(embedder=FakeEmbedder(), min_similarity=-1.0)
    second_mtime = layout_path().stat().st_mtime_ns
    second_text = layout_path().read_text(encoding="utf-8")

    assert second_mtime == first_mtime
    assert second_text == first_text


def test_refresh_first_run_builds_layout_even_with_no_new_embeddings(tmp_path, monkeypatch):
    """Guard the "first-ever run" carve-out: an empty vault has nothing to
    embed, but a layout.json must still be created (not skipped forever
    because load_layout() returns None)."""
    monkeypatch.setenv("GHOSTBRAIN_SEMANTIC_INDEX_DIR", str(tmp_path / "sem"))
    vault = tmp_path / "vault"
    (vault / "20-contexts").mkdir(parents=True)
    monkeypatch.setenv("VAULT_PATH", str(vault))

    class FakeEmbedder:
        def encode(self, texts, show_progress_bar=False):
            return np.zeros((len(texts), 8), dtype="float32")

    from ghostbrain.semantic.refresh import refresh
    from ghostbrain.semantic.projection import load_layout, layout_path

    refresh(embedder=FakeEmbedder(), min_similarity=-1.0)
    assert layout_path().exists()
    assert load_layout() is not None
