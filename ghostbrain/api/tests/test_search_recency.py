"""Recency-aware search ranking.

Pure cosine similarity has no notion of time: "what meetings did I have
today" ranks a similar note from May above this morning's transcript. Two
mechanisms fix that: a small exponential-decay recency boost applied to
every query, and an optional hard ``days`` filter for time-anchored
questions (exposed through the API and the MCP search tool).
"""

from __future__ import annotations

import time

import pytest

# numpy ships with the optional [semantic] extra; CI's backend job installs
# [dev,api] only. These ranking tests exercise the numpy code path, so they
# skip (not fail) where the extra isn't installed.
np = pytest.importorskip("numpy")

from ghostbrain.api.repo import search as repo_search  # noqa: E402
from ghostbrain.semantic.index import Index, IndexEntry  # noqa: E402


class _FakeEmbedder:
    def encode(self, texts):
        return [[1.0, 0.0]] * len(texts)


@pytest.fixture()
def two_note_index(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Two notes with IDENTICAL embeddings; only their mtimes differ."""
    now = time.time()
    index = Index(
        entries={
            "20-contexts/a/old-note.md": IndexEntry(
                row=0, mtime=now - 90 * 86400, content_hash="x"
            ),
            "20-contexts/a/fresh-note.md": IndexEntry(
                row=1, mtime=now - 3600, content_hash="y"
            ),
        },
        vectors=np.asarray([[1.0, 0.0], [1.0, 0.0]], dtype="float32"),
    )
    monkeypatch.setattr(repo_search, "_get_index", lambda: index)
    monkeypatch.setattr(repo_search, "_get_embedder", lambda name: _FakeEmbedder())
    # _hit_for reads the note file from the vault; write real files.
    vault = tmp_path / "vault"
    for rel in index.entries:
        p = vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("---\ntitle: t\n---\n\nbody\n", encoding="utf-8")
    monkeypatch.setenv("VAULT_PATH", str(vault))


def test_recency_boost_ranks_fresh_note_first(two_note_index) -> None:
    res = repo_search.search("anything", limit=2)
    paths = [h["path"] for h in res["items"]]
    assert paths[0].endswith("fresh-note.md"), paths


def test_days_filter_excludes_old_notes(two_note_index) -> None:
    res = repo_search.search("anything", limit=10, days=1)
    paths = [h["path"] for h in res["items"]]
    assert paths == ["20-contexts/a/fresh-note.md"], paths


def test_days_filter_none_returns_all(two_note_index) -> None:
    res = repo_search.search("anything", limit=10)
    assert res["total"] == 2


def test_filename_date_beats_lying_mtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """The semantic refresh rewrites `related:` frontmatter into old notes,
    bumping their mtime — an old calendar stub must still be excluded by
    days=1 because its filename carries the real date."""
    now = time.time()
    index = Index(
        entries={
            # January note, but mtime bumped this morning by a frontmatter rewrite.
            "20-contexts/a/calendar/20260127T080000-old-standup.md": IndexEntry(
                row=0, mtime=now - 60, content_hash="x"
            ),
            # Genuinely fresh note without a date in its filename (transcript slug).
            "20-contexts/a/calendar/transcripts/fresh-meeting-abc123.md": IndexEntry(
                row=1, mtime=now - 3600, content_hash="y"
            ),
        },
        vectors=np.asarray([[1.0, 0.0], [1.0, 0.0]], dtype="float32"),
    )
    monkeypatch.setattr(repo_search, "_get_index", lambda: index)
    monkeypatch.setattr(repo_search, "_get_embedder", lambda name: _FakeEmbedder())
    vault = tmp_path / "vault"
    for rel in index.entries:
        p = vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("---\ntitle: t\n---\n\nbody\n", encoding="utf-8")
    monkeypatch.setenv("VAULT_PATH", str(vault))

    res = repo_search.search("anything", limit=10, days=1)
    paths = [h["path"] for h in res["items"]]
    assert paths == [
        "20-contexts/a/calendar/transcripts/fresh-meeting-abc123.md"
    ], paths


def test_recency_boost_does_not_overpower_content(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A clearly better content match must beat a fresh weak match."""
    now = time.time()
    index = Index(
        entries={
            "20-contexts/a/old-relevant.md": IndexEntry(
                row=0, mtime=now - 90 * 86400, content_hash="x"
            ),
            "20-contexts/a/fresh-unrelated.md": IndexEntry(
                row=1, mtime=now - 3600, content_hash="y"
            ),
        },
        # old note: perfect match (cos=1); fresh note: weak match (cos≈0.3)
        vectors=np.asarray([[1.0, 0.0], [0.3, 0.954]], dtype="float32"),
    )
    monkeypatch.setattr(repo_search, "_get_index", lambda: index)
    monkeypatch.setattr(repo_search, "_get_embedder", lambda name: _FakeEmbedder())
    vault = tmp_path / "vault"
    for rel in index.entries:
        p = vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("---\ntitle: t\n---\n\nbody\n", encoding="utf-8")
    monkeypatch.setenv("VAULT_PATH", str(vault))

    res = repo_search.search("anything", limit=2)
    assert res["items"][0]["path"].endswith("old-relevant.md")
