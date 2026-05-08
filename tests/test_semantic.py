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

    sanlam_dir = vault / "20-contexts" / "sanlam"
    codeship_dir = vault / "20-contexts" / "codeship"

    _write_note(
        sanlam_dir / "calendar" / "doc.md",
        "Avro schema discussion",
        "Avro schema for Kinesis", "sanlam",
    )
    _write_note(
        sanlam_dir / "github" / "prs" / "pr.md",
        "Avro schema fix",
        "Avro schema fix for the policy domain", "sanlam",
    )
    _write_note(
        codeship_dir / "claude" / "sessions" / "x.md",
        "Build hive orchestration",
        "Building the hive multi-repo orchestrator", "codeship",
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
    pr = frontmatter.load(sanlam_dir / "github" / "prs" / "pr.md")
    related = pr.metadata.get("related") or []
    assert related, "expected at least one related entry"
    # All entries should be wikilinks pointing at vault-relative paths.
    assert all(r.startswith("[[") and r.endswith("]]") for r in related)


def test_refresh_skips_transcripts_dir(vault: Path, index_dir: Path) -> None:
    from ghostbrain.semantic.refresh import refresh

    sanlam_cal = vault / "20-contexts" / "sanlam" / "calendar" / "transcripts"
    sanlam_cal.mkdir(parents=True, exist_ok=True)
    _write_note(sanlam_cal / "skip-me.md", "Transcript", "noisy text", "sanlam")
    _write_note(
        vault / "20-contexts" / "sanlam" / "calendar" / "keep.md",
        "Calendar event", "real meeting", "sanlam",
    )

    result = refresh(
        top_k=3, min_similarity=0.4, embedder=FakeEmbedder(),
    )
    # Transcript dir contributes ≥1 to skipped count, regardless of bootstrap.
    assert result.skipped >= 1
    # Verify the transcript wasn't embedded — its keep-counterpart was.
    from ghostbrain.semantic.index import load
    idx = load()
    assert any("/calendar/keep.md" in k for k in idx.entries)
    assert not any("transcripts/" in k for k in idx.entries)


def test_refresh_skips_unchanged_on_second_run(vault: Path, index_dir: Path) -> None:
    from ghostbrain.semantic.refresh import refresh

    _write_note(
        vault / "20-contexts" / "sanlam" / "calendar" / "n1.md",
        "A", "alpha", "sanlam",
    )
    _write_note(
        vault / "20-contexts" / "sanlam" / "calendar" / "n2.md",
        "B", "beta", "sanlam",
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
        vault / "20-contexts" / "sanlam" / "calendar" / "a.md",
        "Avro schema A", "Avro schema A", "sanlam",
    )
    _write_note(
        vault / "20-contexts" / "sanlam" / "calendar" / "b.md",
        "Avro schema B", "Avro schema B", "sanlam",
    )
    _write_note(
        vault / "20-contexts" / "codeship" / "calendar" / "c.md",
        "Avro schema C", "Avro schema C", "codeship",
    )

    refresh(top_k=3, min_similarity=0.0,
            cross_context_only=True, embedder=FakeEmbedder())

    a = frontmatter.load(vault / "20-contexts" / "sanlam" / "calendar" / "a.md")
    related = a.metadata.get("related") or []
    # All related entries should be from a non-sanlam context.
    assert related, "expected at least one cross-context related note"
    for r in related:
        assert "20-contexts/sanlam" not in r, (
            f"related entry {r} should be cross-context, not sanlam"
        )
