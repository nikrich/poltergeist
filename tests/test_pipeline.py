"""End-to-end tests for the pipeline orchestrator (mocked LLM)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import yaml


def _write_routing(vault: Path, rules: dict[str, str]) -> None:
    (vault / "90-meta" / "routing.yaml").write_text(
        yaml.safe_dump(
            {"version": 1, "claude_code": {"project_paths": rules}}
        )
    )


def _set_routing_mode(vault: Path, mode: str) -> None:
    cfg_path = vault / "90-meta" / "config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text()) or {}
    cfg.setdefault("worker", {})["routing_mode"] = mode
    cfg_path.write_text(yaml.safe_dump(cfg))


def _write_session(vault: Path, project_path: Path) -> Path:
    transcript = vault / "transcripts" / "session.jsonl"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text(
        json.dumps({"type": "user", "sessionId": "s1",
                    "timestamp": "2026-05-07T10:00:00Z",
                    "message": {"content": "Help me build the worker."}}) + "\n"
        + json.dumps({"type": "assistant", "sessionId": "s1",
                      "timestamp": "2026-05-07T10:00:01Z",
                      "message": {"content": [
                          {"type": "text", "text": "Sure, let's start with the queue."}
                      ]}}) + "\n",
        encoding="utf-8",
    )
    return transcript


def test_review_only_writes_inbox_only(vault: Path) -> None:
    from ghostbrain.worker import pipeline

    project = vault / "fake-consulting-project"
    project.mkdir()
    _write_routing(vault, {str(project): "consulting"})
    _set_routing_mode(vault, "review_only")
    transcript = _write_session(vault, project)

    event = {
        "id": "claudecode-abc",
        "source": "claude-code",
        "type": "session",
        "timestamp": "2026-05-07T10:00:00Z",
        "title": "test",
        "metadata": {
            "projectPath": str(project),
            "transcriptPath": str(transcript),
        },
    }

    with patch("ghostbrain.worker.pipeline.artifact_extractor.extract") as ex:
        summary = pipeline.process_event(event)

    # Inbox always populated; context path skipped in review-only.
    assert summary["context"] == "consulting"
    assert summary["routing_mode"] == "review_only"
    assert summary["inbox_path"]
    assert summary["context_path"] is None
    assert summary["artifact_count"] == 0
    ex.assert_not_called()


def test_live_mode_writes_to_context_and_extracts(vault: Path) -> None:
    from ghostbrain.worker import pipeline

    project = vault / "fake-consulting-project"
    project.mkdir()
    _write_routing(vault, {str(project): "consulting"})
    _set_routing_mode(vault, "live")
    transcript = _write_session(vault, project)

    event = {
        "id": "claudecode-abc",
        "source": "claude-code",
        "type": "session",
        "timestamp": "2026-05-07T10:00:00Z",
        "metadata": {
            "projectPath": str(project),
            "transcriptPath": str(transcript),
        },
    }

    with patch("ghostbrain.worker.pipeline.artifact_extractor.extract",
               return_value=[Path("/fake/specs/x.md")]) as ex:
        summary = pipeline.process_event(event)

    assert summary["context"] == "consulting"
    assert summary["routing_mode"] == "live"
    assert summary["context_path"] is not None
    assert summary["artifact_count"] == 1
    ex.assert_called_once()


def test_missing_transcript_still_processes_event(vault: Path) -> None:
    from ghostbrain.worker import pipeline

    project = vault / "fake-project"
    project.mkdir()
    _write_routing(vault, {str(project): "personal"})
    _set_routing_mode(vault, "live")

    event = {
        "id": "claudecode-missing",
        "source": "claude-code",
        "type": "session",
        "timestamp": "2026-05-07T10:00:00Z",
        "metadata": {
            "projectPath": str(project),
            "transcriptPath": str(vault / "does-not-exist.jsonl"),
        },
    }

    with patch("ghostbrain.worker.pipeline.artifact_extractor.extract",
               return_value=[]) as ex:
        summary = pipeline.process_event(event)

    # Subagent sessions (and any other case where the JSONL is gone before the
    # worker reads the queue) used to produce useless stub notes with just a
    # title. The pipeline now drops them.
    assert summary["status"] == "skipped"
    assert summary["reason"] == "missing_transcript"
    ex.assert_not_called()
