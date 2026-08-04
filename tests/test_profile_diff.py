"""Tests for the per-session profile-diff proposer."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from ghostbrain.llm.client import LLMResult


def _llm(text: str = "", structured=None) -> LLMResult:
    return LLMResult(
        text=text, structured=structured, model="sonnet", cost_usd=0.0,
        duration_ms=1, session_id="s", raw={},
    )


def _diff(field: str, after: str, *, op: str = "add", conf: float = 0.92) -> dict:
    return {
        "field": field, "operation": op, "before": "",
        "after": after, "evidence": "...", "confidence": conf,
    }


def test_propose_writes_jsonl_lines(vault: Path) -> None:
    from ghostbrain.profile import diff

    payload = {"diffs": [
        _diff("current-projects", "Built ghost-brain Phase 6"),
        _diff("decisions", "Use Sonnet for extractor"),
    ]}
    with patch("ghostbrain.profile.diff.llm.run",
               return_value=_llm(structured=payload)):
        proposals = diff.propose_for_session(
            excerpt="some excerpt content",
            parent_event_id="ev-1",
            parent_session_id="sess-1",
            parent_note_path=vault / "20-contexts" / "consulting" / "claude" / "sessions" / "p.md",
        )

    assert len(proposals) == 2
    out = vault / "80-profile" / "_proposed"
    files = list(out.glob("*.jsonl"))
    assert files
    lines = files[0].read_text().splitlines()
    assert len(lines) == 2
    rec = json.loads(lines[0])
    assert rec["field"] == "current-projects"
    assert rec["after"] == "Built ghost-brain Phase 6"
    assert rec["parent_event_id"] == "ev-1"
    assert "20-contexts/consulting" in rec["parent_note_path"]


def test_low_confidence_diffs_dropped(vault: Path) -> None:
    from ghostbrain.profile import diff

    payload = {"diffs": [
        _diff("current-projects", "barely real", conf=0.5),
        _diff("current-projects", "very real", conf=0.95),
    ]}
    with patch("ghostbrain.profile.diff.llm.run",
               return_value=_llm(structured=payload)):
        proposals = diff.propose_for_session(
            excerpt="x", parent_event_id="ev",
        )

    assert len(proposals) == 1
    assert proposals[0].after == "very real"


def test_invalid_field_or_operation_dropped(vault: Path) -> None:
    from ghostbrain.profile import diff

    payload = {"diffs": [
        _diff("not-a-field", "x"),
        {"field": "current-projects", "operation": "delete",
         "after": "x", "evidence": "y", "confidence": 0.9},
        _diff("current-projects", "ok"),
    ]}
    with patch("ghostbrain.profile.diff.llm.run",
               return_value=_llm(structured=payload)):
        proposals = diff.propose_for_session(excerpt="x", parent_event_id="ev")
    assert [p.after for p in proposals] == ["ok"]


def test_empty_diffs_writes_no_file(vault: Path) -> None:
    from ghostbrain.profile import diff

    with patch("ghostbrain.profile.diff.llm.run",
               return_value=_llm(structured={"diffs": []})):
        proposals = diff.propose_for_session(excerpt="x", parent_event_id="ev")
    assert proposals == []
    out_dir = vault / "80-profile" / "_proposed"
    assert not list(out_dir.glob("*.jsonl"))


def test_llm_error_returns_empty_silently(vault: Path) -> None:
    from ghostbrain.profile import diff
    from ghostbrain.llm import client as llm

    with patch("ghostbrain.profile.diff.llm.run",
               side_effect=llm.LLMError("oops")):
        proposals = diff.propose_for_session(excerpt="x", parent_event_id="ev")
    assert proposals == []


def test_empty_excerpt_skips_call(vault: Path) -> None:
    from ghostbrain.profile import diff

    with patch("ghostbrain.profile.diff.llm.run") as mock:
        proposals = diff.propose_for_session(excerpt="   ", parent_event_id="ev")
    mock.assert_not_called()
    assert proposals == []
