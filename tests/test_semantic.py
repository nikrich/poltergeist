"""Tests for semantic linking. SentenceTransformer is mocked — we don't
download the model in CI."""

from __future__ import annotations

from pathlib import Path

import pytest


def _write_note(path: Path, title: str, body: str, context: str) -> None:
    import yaml
    path.parent.mkdir(parents=True, exist_ok=True)
    front = {
        "id": title.lower().replace(" ", "-"),
        "type": "note",
        "context": context,
        "source": "manual",
        "title": title,
    }
    yaml_block = yaml.safe_dump(front, sort_keys=False).rstrip()
    path.write_text(f"---\n{yaml_block}\n---\n\n{body}\n", encoding="utf-8")


class FakeEmbedder:
    """Returns a deterministic vector for each piece of text.

    Same-prefix texts get similar vectors; different-prefix texts get
    orthogonal vectors. Lets us assert on related-note ordering.
    """

    def encode(self, texts, **_kwargs):
        import numpy as np
        out = []
        for t in texts:
            head = (t.split("\n", 1)[0] or "")[:1].lower()
            base = ord(head) - ord("a") if head.isalpha() else 0
            vec = np.zeros(8, dtype="float32")
            vec[base % 8] = 1.0
            # Add a tiny stable wobble so identical heads aren't *identical* vectors.
            vec[(base + 1) % 8] = 0.1 * len(t) % 1.0
            out.append(vec)
        return np.asarray(out)


@pytest.fixture()
def index_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GHOSTBRAIN_SEMANTIC_INDEX_DIR", str(tmp_path / "semantic"))
    import importlib
    from ghostbrain.semantic import index as idx_mod
    importlib.reload(idx_mod)
    from ghostbrain.semantic import refresh as refresh_mod
    importlib.reload(refresh_mod)
    return tmp_path / "semantic"


def test_refresh_writes_related_frontmatter(vault: Path, index_dir: Path) -> None:
    import frontmatter
    from ghostbrain.semantic.refresh import refresh

    work_dir = vault / "20-contexts" / "work"
    consulting_dir = vault / "20-contexts" / "consulting"

    _write_note(
        work_dir / "calendar" / "doc.md",
        "Avro schema discussion",
        "Avro schema for Kinesis", "work",
    )
    _write_note(
        work_dir / "github" / "prs" / "pr.md",
        "Avro schema fix",
        "Avro schema fix for the policy domain", "work",
    )
    _write_note(
        consulting_dir / "claude" / "sessions" / "x.md",
        "Build hive orchestration",
        "Building the hive multi-repo orchestrator", "consulting",
    )

    result = refresh(
        top_k=5,
        min_similarity=0.0,
        embedder=FakeEmbedder(),
    )

    # Bootstrap seeds extra context-stub notes; we only care that *our*
    # notes were embedded and the PR got SOME related entries written.
    assert result.embedded >= 3
    assert result.linked >= 1
    pr = frontmatter.load(work_dir / "github" / "prs" / "pr.md")
    related = pr.metadata.get("related") or []
    assert related, "expected at least one related entry"
    # All entries should be wikilinks pointing at vault-relative paths.
    assert all(r.startswith("[[") and r.endswith("]]") for r in related)


def test_refresh_indexes_transcripts(vault: Path, index_dir: Path) -> None:
    """Transcripts now participate in semantic indexing so meeting content
    gets cross-context backlinks. The 8000-char body cap in
    refresh._extract_text_and_context keeps long transcripts from
    dominating the embedding space."""
    from ghostbrain.semantic.refresh import refresh

    work_cal = vault / "20-contexts" / "work" / "calendar" / "transcripts"
    work_cal.mkdir(parents=True, exist_ok=True)
    _write_note(work_cal / "include-me.md", "Transcript", "noisy text", "work")
    _write_note(
        vault / "20-contexts" / "work" / "calendar" / "keep.md",
        "Calendar event", "real meeting", "work",
    )

    refresh(top_k=3, min_similarity=0.4, embedder=FakeEmbedder())

    from ghostbrain.semantic.index import load
    idx = load()
    assert any("/calendar/keep.md" in k for k in idx.entries)
    assert any("transcripts/" in k for k in idx.entries)


def test_refresh_skips_unchanged_on_second_run(vault: Path, index_dir: Path) -> None:
    from ghostbrain.semantic.refresh import refresh

    _write_note(
        vault / "20-contexts" / "work" / "calendar" / "n1.md",
        "A", "alpha", "work",
    )
    _write_note(
        vault / "20-contexts" / "work" / "calendar" / "n2.md",
        "B", "beta", "work",
    )

    first = refresh(top_k=1, min_similarity=0.0, embedder=FakeEmbedder())
    first_embedded = first.embedded

    # Re-run; nothing changed → all reused.
    second = refresh(top_k=1, min_similarity=0.0, embedder=FakeEmbedder())
    assert second.embedded == 0
    assert second.reused == first_embedded


def test_cross_context_only_filter(vault: Path, index_dir: Path) -> None:
    """When ``cross_context_only=True``, related: only points to other contexts."""
    import frontmatter
    from ghostbrain.semantic.refresh import refresh

    _write_note(
        vault / "20-contexts" / "work" / "calendar" / "a.md",
        "Avro schema A", "Avro schema A", "work",
    )
    _write_note(
        vault / "20-contexts" / "work" / "calendar" / "b.md",
        "Avro schema B", "Avro schema B", "work",
    )
    _write_note(
        vault / "20-contexts" / "consulting" / "calendar" / "c.md",
        "Avro schema C", "Avro schema C", "consulting",
    )

    refresh(top_k=3, min_similarity=0.0,
            cross_context_only=True, embedder=FakeEmbedder())

    a = frontmatter.load(vault / "20-contexts" / "work" / "calendar" / "a.md")
    related = a.metadata.get("related") or []
    # All related entries should be from a non-work context.
    assert related, "expected at least one cross-context related note"
    for r in related:
        assert "20-contexts/work" not in r, (
            f"related entry {r} should be cross-context, not work"
        )
