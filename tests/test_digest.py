"""Tests for the daily digest generator."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import yaml

from ghostbrain.llm.client import LLMResult


def _llm_text(text: str) -> LLMResult:
    return LLMResult(text=text, structured=None, model="sonnet",
                     cost_usd=0.0, duration_ms=1, session_id="s", raw={})


def _write_audit(vault: Path, day: date, events: list[dict]) -> None:
    audit = vault / "90-meta" / "audit"
    audit.mkdir(parents=True, exist_ok=True)
    f = audit / f"{day.isoformat()}.jsonl"
    with f.open("w", encoding="utf-8") as h:
        for e in events:
            h.write(json.dumps(e) + "\n")


def _write_inbox_note(vault: Path, name: str, frontmatter_dict: dict, body: str) -> Path:
    d = vault / "00-inbox" / "raw" / "claude-code"
    d.mkdir(parents=True, exist_ok=True)
    yaml_block = yaml.safe_dump(frontmatter_dict, sort_keys=False).rstrip()
    p = d / name
    p.write_text(f"---\n{yaml_block}\n---\n\n{body}\n", encoding="utf-8")
    return p


def test_build_digest_input_aggregates_by_context(vault: Path) -> None:
    from ghostbrain.worker.digest import build_digest_input

    note_a = _write_inbox_note(
        vault, "n-a.md",
        {"id": "a", "title": "Build worker", "context": "codeship",
         "source": "claude-code", "routingMethod": "path",
         "routingConfidence": 1.0, "ingestedAt": "2026-05-07T10:00Z"},
        "# Build worker\n\nbody",
    )
    note_b = _write_inbox_note(
        vault, "n-b.md",
        {"id": "b", "title": "Capstone fix", "context": "sanlam",
         "source": "claude-code", "routingMethod": "path",
         "routingConfidence": 1.0, "ingestedAt": "2026-05-07T11:00Z"},
        "# Capstone fix\n\nbody",
    )

    summary_day = date(2026, 5, 7)
    _write_audit(vault, summary_day, [
        {"ts": "2026-05-07T10:00:00Z", "event_type": "worker_started"},
        {"ts": "2026-05-07T10:01:00Z", "event_type": "event_processed",
         "event_id": "a", "status": "success", "source": "claude-code",
         "context": "codeship", "method": "path",
         "inbox_path": str(note_a), "artifact_count": 2},
        {"ts": "2026-05-07T11:00:00Z", "event_type": "event_processed",
         "event_id": "b", "status": "success", "source": "claude-code",
         "context": "sanlam", "method": "path",
         "inbox_path": str(note_b), "artifact_count": 0},
        {"ts": "2026-05-07T11:30:00Z", "event_type": "event_failed",
         "event_id": "x"},
    ])

    digest = build_digest_input(target_date=date(2026, 5, 8))

    assert digest.digest_date == "2026-05-08"
    assert digest.day_name == "Friday"
    assert {n.title for n in digest.notes} == {"Build worker", "Capstone fix"}
    assert set(digest.by_context.keys()) == {"codeship", "sanlam"}
    assert digest.by_context["codeship"][0].artifact_count == 2
    assert digest.health["processed"] == 2
    assert digest.health["failed"] == 1
    assert digest.health["last_capture"] == "2026-05-07T11:00:00Z"


def test_build_digest_input_empty_day(vault: Path) -> None:
    from ghostbrain.worker.digest import build_digest_input

    digest = build_digest_input(target_date=date(2026, 5, 8))
    assert digest.notes == []
    assert digest.by_context == {}
    assert digest.health["processed"] == 0


def test_render_input_for_prompt_groups_by_context(vault: Path) -> None:
    from ghostbrain.worker.digest import (
        CapturedNote, DigestInput, render_input_for_prompt,
    )

    # Configure the contexts this fixture uses, in canonical order.
    (vault / "90-meta" / "routing.yaml").write_text(
        "contexts:\n  - sanlam\n  - codeship\n", encoding="utf-8"
    )

    notes = [
        CapturedNote(title="A", context="codeship", source="claude-code",
                     artifact_count=2, note_path=None, ingested_at=None,
                     routing_method="path", routing_confidence=1.0),
        CapturedNote(title="B", context="sanlam", source="claude-code",
                     artifact_count=0, note_path=None, ingested_at=None,
                     routing_method="path", routing_confidence=1.0),
    ]
    d = DigestInput(
        digest_date="2026-05-08", day_name="Friday",
        notes=notes,
        by_context={"codeship": [notes[0]], "sanlam": [notes[1]]},
        health={"processed": 2, "failed": 0, "last_capture": "2026-05-07T11:00:00Z"},
        review_queue=[],
    )

    rendered = render_input_for_prompt(d)
    assert "Context: sanlam" in rendered  # known contexts in canonical order
    assert "Context: codeship" in rendered
    # sanlam comes before codeship per the configured context ordering
    assert rendered.index("Context: sanlam") < rendered.index("Context: codeship")
    assert "2 artifact(s)" in rendered  # codeship had 2
    assert "processed: 2" in rendered


def test_generate_digest_writes_to_vault(vault: Path) -> None:
    from ghostbrain.worker import digest

    summary_day = date(2026, 5, 7)
    note = _write_inbox_note(
        vault, "n.md",
        {"id": "x", "title": "Real session", "context": "codeship",
         "source": "claude-code", "routingMethod": "path",
         "routingConfidence": 1.0, "ingestedAt": "2026-05-07T10:00Z"},
        "# Real session\n\n",
    )
    _write_audit(vault, summary_day, [
        {"ts": "2026-05-07T10:01:00Z", "event_type": "event_processed",
         "event_id": "x", "status": "success", "source": "claude-code",
         "context": "codeship", "method": "path",
         "inbox_path": str(note), "artifact_count": 0},
    ])

    with patch("ghostbrain.worker.digest.llm.run",
               return_value=_llm_text("# Digest — Friday, 2026-05-08\n\nMock body.")):
        out = digest.generate_digest(target_date=date(2026, 5, 8))

    assert out == vault / "10-daily" / "2026-05-08.md"
    assert out.exists()
    body = out.read_text()
    assert "Mock body." in body
    assert "context: cross" in body  # frontmatter


def test_generate_digest_empty_day_uses_local_template(vault: Path) -> None:
    """No notes, no audit lines → don't call LLM, use the local empty body."""
    from ghostbrain.worker import digest

    with patch("ghostbrain.worker.digest.llm.run") as mock_llm:
        out = digest.generate_digest(target_date=date(2026, 5, 8))

    mock_llm.assert_not_called()
    body = out.read_text()
    assert "No events captured" in body


def test_generate_digest_falls_back_when_llm_errors(vault: Path) -> None:
    from ghostbrain.worker import digest
    from ghostbrain.llm import client as llm

    summary_day = date(2026, 5, 7)
    note = _write_inbox_note(
        vault, "n.md",
        {"id": "x", "title": "S", "context": "codeship",
         "source": "claude-code", "routingMethod": "path",
         "routingConfidence": 1.0},
        "# S\n",
    )
    _write_audit(vault, summary_day, [
        {"ts": "2026-05-07T10:00Z", "event_type": "event_processed",
         "event_id": "x", "status": "success", "source": "claude-code",
         "context": "codeship", "method": "path",
         "inbox_path": str(note), "artifact_count": 0},
    ])

    with patch("ghostbrain.worker.digest.llm.run",
               side_effect=llm.LLMError("rate limit")):
        out = digest.generate_digest(target_date=date(2026, 5, 8))

    body = out.read_text()
    # Mechanical fallback structure.
    assert "## Yesterday at a glance" in body
    assert "## Codeship" in body
    assert "## System health" in body


def test_per_context_digest_only_when_threshold_met(vault: Path) -> None:
    from ghostbrain.worker import digest

    summary_day = date(2026, 5, 7)
    # Make 6 codeship events (above the 5-event threshold)
    audit_events = []
    for i in range(6):
        note = _write_inbox_note(
            vault, f"n-{i}.md",
            {"id": f"e{i}", "title": f"Note {i}", "context": "codeship",
             "source": "claude-code", "routingMethod": "path",
             "routingConfidence": 1.0},
            "# x\n",
        )
        audit_events.append({
            "ts": "2026-05-07T10:00Z",
            "event_type": "event_processed",
            "event_id": f"e{i}", "status": "success",
            "source": "claude-code", "context": "codeship", "method": "path",
            "inbox_path": str(note), "artifact_count": 0,
        })
    _write_audit(vault, summary_day, audit_events)

    with patch("ghostbrain.worker.digest.llm.run",
               return_value=_llm_text("# main\n\nbody")):
        digest.generate_digest(target_date=date(2026, 5, 8))

    by_ctx = vault / "10-daily" / "by-context"
    assert (by_ctx / "codeship-2026-05-08.md").exists()
    # No sanlam events → no per-context file.
    assert not (by_ctx / "sanlam-2026-05-08.md").exists()
