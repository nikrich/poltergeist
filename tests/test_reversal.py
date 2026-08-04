"""Tests for decision-reversal detection. LLM mocked end-to-end."""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import frontmatter
import yaml

from ghostbrain.llm.client import LLMResult


def _llm_result(payload: dict) -> LLMResult:
    return LLMResult(
        text=json.dumps(payload), structured=None, model="haiku", cost_usd=0.0,
        duration_ms=1, session_id="s", raw={},
    )


def _write_decision(
    vault: Path, *, context: str, artifact_id: str, title: str,
    body: str, created: datetime,
) -> Path:
    folder = vault / "20-contexts" / context / "calendar" / "artifacts" / "decisions"
    folder.mkdir(parents=True, exist_ok=True)
    meta = {
        "id": artifact_id,
        "context": context,
        "type": "artifact",
        "artifactType": "decision",
        "source": "recorder",
        "created": created.isoformat(),
        "title": title,
    }
    yaml_block = yaml.safe_dump(meta, sort_keys=False).rstrip()
    path = folder / f"{artifact_id}.md"
    path.write_text(f"---\n{yaml_block}\n---\n\n# {title}\n\n{body}\n",
                    encoding="utf-8")
    return path


def test_no_candidates_short_circuits(vault: Path) -> None:
    """When the new artifact is the only decision in its context, do
    nothing — no LLM call required."""
    from ghostbrain.worker import reversal

    new = _write_decision(
        vault, context="work", artifact_id="new-1",
        title="Use Postgres", body="Decision body.",
        created=datetime.now(timezone.utc),
    )

    sentinel: list[str] = []
    def explode(*a, **kw):
        sentinel.append("called")
        raise AssertionError("LLM should not fire when no candidates")

    with patch("ghostbrain.worker.reversal.llm.run", side_effect=explode):
        result = reversal.check_for_reversals(new)

    assert result.contradicted_paths == []
    assert sentinel == []


def test_reversal_writes_frontmatter_on_both_notes(vault: Path) -> None:
    from ghostbrain.worker import reversal

    now = datetime.now(timezone.utc)
    old = _write_decision(
        vault, context="work", artifact_id="old-1",
        title="Use DynamoDB for policy domain",
        body="We're going DynamoDB; cheaper and simpler.",
        created=now - timedelta(days=10),
    )
    new = _write_decision(
        vault, context="work", artifact_id="new-1",
        title="Use Postgres for policy domain",
        body="Switching to Postgres after the dynamo cost spike.",
        created=now,
    )

    with patch(
        "ghostbrain.worker.reversal.llm.run",
        return_value=_llm_result({"reversals": [
            {"contradicts_id": "old-1",
             "reasoning": "earlier said DynamoDB; new picks Postgres"},
        ]}),
    ):
        result = reversal.check_for_reversals(new)

    assert len(result.contradicted_paths) == 1
    assert result.contradicted_paths[0] == old

    new_note = frontmatter.load(new)
    contradicts = new_note.metadata.get("contradicts") or []
    assert any("decisions/old-1" in s for s in contradicts), contradicts

    old_note = frontmatter.load(old)
    reversed_by = old_note.metadata.get("reversed_by") or []
    assert any("decisions/new-1" in s for s in reversed_by), reversed_by


def test_skips_non_decision_artifacts(vault: Path) -> None:
    from ghostbrain.worker import reversal

    folder = vault / "20-contexts" / "work" / "calendar" / "artifacts" / "action_items"
    folder.mkdir(parents=True, exist_ok=True)
    meta = {
        "id": "act-1", "context": "work", "type": "artifact",
        "artifactType": "action_item",
        "created": datetime.now(timezone.utc).isoformat(),
    }
    path = folder / "act-1.md"
    path.write_text(
        f"---\n{yaml.safe_dump(meta).rstrip()}\n---\n\n# action\n",
        encoding="utf-8",
    )

    sentinel: list[str] = []
    with patch("ghostbrain.worker.reversal.llm.run",
                side_effect=lambda *a, **k: sentinel.append("x")):
        result = reversal.check_for_reversals(path)

    assert result.contradicted_paths == []
    assert sentinel == []


def test_lookback_excludes_old_candidates(vault: Path) -> None:
    """Candidates older than lookback_days are not even sent to the LLM."""
    from ghostbrain.worker import reversal

    now = datetime.now(timezone.utc)
    _write_decision(
        vault, context="work", artifact_id="ancient",
        title="Old", body="Old.", created=now - timedelta(days=200),
    )
    new = _write_decision(
        vault, context="work", artifact_id="new-x",
        title="New", body="New.", created=now,
    )

    captured_prompts: list[str] = []
    def capture(prompt, **kwargs):
        captured_prompts.append(prompt)
        return _llm_result({"reversals": []})

    # No candidates within 90d → LLM should NOT be called at all.
    with patch("ghostbrain.worker.reversal.llm.run", side_effect=capture):
        result = reversal.check_for_reversals(new, lookback_days=90)

    assert result.contradicted_paths == []
    assert captured_prompts == []


def test_llm_error_returns_empty_result(vault: Path) -> None:
    from ghostbrain.worker import reversal
    from ghostbrain.llm import client as llm

    now = datetime.now(timezone.utc)
    _write_decision(
        vault, context="work", artifact_id="old-2",
        title="Old", body="Old.", created=now - timedelta(days=5),
    )
    new = _write_decision(
        vault, context="work", artifact_id="new-2",
        title="New", body="New.", created=now,
    )

    with patch("ghostbrain.worker.reversal.llm.run",
                side_effect=llm.LLMError("budget")):
        result = reversal.check_for_reversals(new)

    assert result.contradicted_paths == []
    # Frontmatter should not have been touched
    assert "contradicts" not in frontmatter.load(new).metadata


def test_unknown_contradicts_id_skipped(vault: Path) -> None:
    """If the LLM returns an ID we didn't send, ignore it (don't invent)."""
    from ghostbrain.worker import reversal

    now = datetime.now(timezone.utc)
    _write_decision(
        vault, context="work", artifact_id="real-old",
        title="Real old", body="...", created=now - timedelta(days=3),
    )
    new = _write_decision(
        vault, context="work", artifact_id="new-3",
        title="New", body="...", created=now,
    )

    with patch(
        "ghostbrain.worker.reversal.llm.run",
        return_value=_llm_result({"reversals": [
            {"contradicts_id": "fictional", "reasoning": "n/a"},
        ]}),
    ):
        result = reversal.check_for_reversals(new)

    assert result.contradicted_paths == []
    assert "contradicts" not in frontmatter.load(new).metadata
