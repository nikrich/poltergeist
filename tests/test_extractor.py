"""Tests for the artifact extractor (LLM mocked)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import frontmatter

from ghostbrain.llm.client import LLMResult


def _llm_result(text: str) -> LLMResult:
    return LLMResult(
        text=text, structured=None, model="sonnet", cost_usd=0.0,
        duration_ms=1, session_id="s", raw={},
    )


def test_writes_artifacts_for_each_extracted_item(vault: Path) -> None:
    from ghostbrain.worker import extractor

    payload = (
        '{"items": ['
        '{"type":"decision","title":"Use claude -p subprocess",'
        '"content":"Decided because Max OAuth covers it.","tags":["llm"]},'
        '{"type":"spec","title":"Worker queue spec",'
        '"content":"Filesystem queue with atomic rename.","tags":[]}'
        ']}'
    )

    with patch("ghostbrain.worker.extractor.llm.run",
               return_value=_llm_result(payload)):
        paths = extractor.extract(
            "some excerpt",
            context="codeship",
            parent_note_id="parent-1",
            parent_note_path=vault / "00-inbox" / "raw" / "claude-code" / "p.md",
        )

    assert len(paths) == 2
    artifacts_dir = vault / "20-contexts" / "codeship" / "claude" / "artifacts"
    assert (artifacts_dir / "decisions").exists()
    assert (artifacts_dir / "specs").exists()
    decisions = list((artifacts_dir / "decisions").glob("*.md"))
    assert decisions, "decision artifact not written"
    note = frontmatter.load(decisions[0])
    assert note["artifactType"] == "decision"
    assert note["context"] == "codeship"


def test_empty_array_writes_nothing(vault: Path) -> None:
    from ghostbrain.worker import extractor

    with patch("ghostbrain.worker.extractor.llm.run",
               return_value=_llm_result('{"items": []}')):
        paths = extractor.extract(
            "trivial chat", context="codeship",
            parent_note_id="p", parent_note_path=None,
        )
    assert paths == []


def test_invalid_artifact_types_filtered(vault: Path) -> None:
    from ghostbrain.worker import extractor

    payload = (
        '{"items": ['
        '{"type":"unknown-type","title":"X","content":"Y"},'
        '{"type":"decision","title":"Real decision","content":"Real content"}'
        ']}'
    )
    with patch("ghostbrain.worker.extractor.llm.run",
               return_value=_llm_result(payload)):
        paths = extractor.extract(
            "excerpt", context="personal",
            parent_note_id="p", parent_note_path=None,
        )
    # Only the valid item is written.
    assert len(paths) == 1


def test_extractor_handles_raw_array_fallback(vault: Path) -> None:
    """Tolerant: if the LLM returns a raw array (no envelope), still works."""
    from ghostbrain.worker import extractor

    payload = (
        '[{"type":"decision","title":"X","content":"Y"}]'
    )
    with patch("ghostbrain.worker.extractor.llm.run",
               return_value=_llm_result(payload)):
        paths = extractor.extract(
            "excerpt", context="codeship",
            parent_note_id="p", parent_note_path=None,
        )
    assert len(paths) == 1


def test_llm_error_returns_empty_list(vault: Path) -> None:
    from ghostbrain.worker import extractor
    from ghostbrain.llm import client as llm

    with patch("ghostbrain.worker.extractor.llm.run",
               side_effect=llm.LLMError("rate limit")):
        paths = extractor.extract(
            "excerpt", context="codeship",
            parent_note_id="p", parent_note_path=None,
        )
    assert paths == []
