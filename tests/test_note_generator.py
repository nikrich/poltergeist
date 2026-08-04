"""Tests for the note generator."""

from __future__ import annotations

from pathlib import Path

import frontmatter

from ghostbrain.worker.note_generator import write_note
from ghostbrain.worker.router import RoutingDecision


def _decision(ctx: str = "consulting", conf: float = 1.0) -> RoutingDecision:
    return RoutingDecision(
        context=ctx, confidence=conf, reasoning="test", method="path",
    )


def _event(**overrides) -> dict:
    base = {
        "id": "abc-123",
        "source": "claude-code",
        "type": "session",
        "timestamp": "2026-05-07T10:00:00Z",
        "title": "Working on the worker",
        "metadata": {"projectPath": "/repos/x"},
    }
    base.update(overrides)
    return base


def test_writes_to_inbox_always(vault: Path) -> None:
    result = write_note(
        _event(), _decision(),
        body="# body", write_to_context=False,
    )
    assert result.inbox_path.exists()
    assert result.context_path is None
    assert result.inbox_path.parent == vault / "00-inbox" / "raw" / "claude-code"


def test_writes_to_context_when_allowed(vault: Path) -> None:
    result = write_note(
        _event(), _decision("work"),
        body="# body", write_to_context=True,
    )
    assert result.context_path is not None
    assert result.context_path.exists()
    assert result.context_path.parent == (
        vault / "20-contexts" / "work" / "claude" / "sessions"
    )


def test_skips_context_for_needs_review(vault: Path) -> None:
    result = write_note(
        _event(), _decision("needs_review", 0.0),
        body="# body", write_to_context=True,
    )
    assert result.context_path is None


def test_github_pr_routes_to_prs_subdir(vault: Path) -> None:
    event = {
        "id": "github:pr:AcmeLabs/x#1",
        "source": "github", "type": "pr",
        "timestamp": "2026-05-07T10:00:00Z",
        "title": "feat: ship",
        "metadata": {"repo": "AcmeLabs/x", "org": "AcmeLabs"},
    }
    result = write_note(event, _decision("consulting"),
                        body="# body", write_to_context=True)
    assert result.context_path is not None
    assert result.context_path.parent == (
        vault / "20-contexts" / "consulting" / "github" / "prs"
    )


def test_github_issue_routes_to_issues_subdir(vault: Path) -> None:
    event = {
        "id": "github:issue:AcmeLabs/x#7",
        "source": "github", "type": "issue",
        "timestamp": "2026-05-07T10:00:00Z",
        "title": "Bug: x",
        "metadata": {"repo": "AcmeLabs/x", "org": "AcmeLabs"},
    }
    result = write_note(event, _decision("consulting"),
                        body="# body", write_to_context=True)
    assert result.context_path is not None
    assert result.context_path.parent == (
        vault / "20-contexts" / "consulting" / "github" / "issues"
    )


def test_frontmatter_includes_routing_metadata(vault: Path) -> None:
    result = write_note(
        _event(), _decision("consulting", 0.9),
        body="# body", write_to_context=True,
    )
    note = frontmatter.load(result.context_path)
    assert note["context"] == "consulting"
    assert note["routingConfidence"] == 0.9
    assert note["routingMethod"] == "path"
    assert note["source"] == "claude-code"
    assert note["projectPath"] == "/repos/x"
