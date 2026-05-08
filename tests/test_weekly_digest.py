"""Tests for the weekly digest. LLM is mocked — we exercise aggregation,
rendering, week-boundary logic, and the empty-week fallback."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import yaml


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _frontmatter_doc(meta: dict, body: str = "") -> str:
    return f"---\n{yaml.safe_dump(meta, sort_keys=False).rstrip()}\n---\n\n{body}\n"


def _write_daily_digest(vault: Path, d: date, contexts: list[str], glance: str) -> None:
    body = (
        f"# Digest — {d.strftime('%A')}, {d.isoformat()}\n\n"
        f"## Yesterday at a glance\n\n{glance}\n\n"
        f"## Sanlam\n\n- something\n"
    )
    meta = {
        "id": f"digest-{d.isoformat()}",
        "type": "digest",
        "date": d.isoformat(),
        "contexts": contexts,
        "noteCount": 5,
    }
    _write(vault / "10-daily" / f"{d.isoformat()}.md", _frontmatter_doc(meta, body))


def _write_artifact(
    vault: Path, *, context: str, artifact_type: str, title: str,
    created: str,
) -> Path:
    folder_map = {
        "decision": "decisions", "action_item": "action_items",
        "unresolved": "unresolved", "spec": "specs",
    }
    path = (
        vault / "20-contexts" / context / "calendar" / "artifacts"
        / folder_map[artifact_type] / f"{title.lower().replace(' ', '-')}.md"
    )
    meta = {
        "id": title.lower().replace(" ", "-"),
        "context": context,
        "type": "artifact",
        "artifactType": artifact_type,
        "source": "recorder",
        "created": created,
        "title": title,
    }
    _write(path, _frontmatter_doc(meta, f"# {title}\n\nbody\n"))
    return path


def _write_audit(vault: Path, day: date, events: list[dict]) -> None:
    f = vault / "90-meta" / "audit" / f"{day.isoformat()}.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("a", encoding="utf-8") as h:
        for e in events:
            h.write(json.dumps(e) + "\n")


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_most_recent_sunday_when_today_is_sunday() -> None:
    from ghostbrain.worker.weekly_digest import _most_recent_sunday
    sunday = date(2026, 5, 10)  # Sunday
    assert _most_recent_sunday(sunday) == sunday


def test_most_recent_sunday_when_today_is_midweek() -> None:
    from ghostbrain.worker.weekly_digest import _most_recent_sunday
    wednesday = date(2026, 5, 13)
    assert _most_recent_sunday(wednesday) == date(2026, 5, 10)


def test_extract_glance_section() -> None:
    from ghostbrain.worker.weekly_digest import _extract_glance_section
    body = (
        "# Digest — Saturday, 2026-05-09\n\n"
        "## Yesterday at a glance\n\n"
        "TrustFlow happened. Heavy day.\n\n"
        "## Sanlam\n\n- something\n"
    )
    assert "TrustFlow happened" in _extract_glance_section(body)
    assert "Sanlam" not in _extract_glance_section(body)


def test_quiet_contexts_excludes_needs_review() -> None:
    from ghostbrain.worker.weekly_digest import _quiet_contexts
    activity = {"sanlam": 50, "codeship": 1, "personal": 0, "needs_review": 0}
    quiet = _quiet_contexts(activity)
    assert "codeship" in quiet
    assert "personal" in quiet
    assert "sanlam" not in quiet
    assert "needs_review" not in quiet


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def test_build_weekly_input_pulls_daily_digests(vault: Path) -> None:
    from ghostbrain.worker.weekly_digest import build_weekly_input

    week_end = date(2026, 5, 10)  # Sunday
    for offset, ctx_list in [
        (-6, ["sanlam"]), (-5, ["sanlam", "codeship"]),
        (-1, ["sanlam"]), (0, ["sanlam", "personal"]),
    ]:
        _write_daily_digest(
            vault, week_end + timedelta(days=offset),
            contexts=ctx_list, glance="TL;DR text.",
        )

    inp = build_weekly_input(week_end)
    assert inp.iso_week_label.startswith("2026-W")
    assert inp.week_start == "2026-05-04"
    assert inp.week_end == "2026-05-10"
    assert len(inp.days) == 4
    # Days should be in date order.
    assert [d.digest_date for d in inp.days] == [
        "2026-05-04", "2026-05-05", "2026-05-09", "2026-05-10",
    ]


def test_build_weekly_input_pulls_artifacts_in_window(vault: Path) -> None:
    from ghostbrain.worker.weekly_digest import build_weekly_input

    week_end = date(2026, 5, 10)
    _write_artifact(vault, context="sanlam", artifact_type="decision",
                     title="In-window decision", created="2026-05-08T10:00:00Z")
    _write_artifact(vault, context="sanlam", artifact_type="action_item",
                     title="Owner action", created="2026-05-09T10:00:00Z")
    _write_artifact(vault, context="codeship", artifact_type="unresolved",
                     title="Drift risk", created="2026-05-07T10:00:00Z")
    # Out of window — last week
    _write_artifact(vault, context="sanlam", artifact_type="decision",
                     title="Old decision", created="2026-04-30T10:00:00Z")
    # Out of window — next week
    _write_artifact(vault, context="sanlam", artifact_type="decision",
                     title="Future decision", created="2026-05-11T10:00:00Z")

    inp = build_weekly_input(week_end)
    titles = {a.title for a in inp.artifacts}
    assert titles == {"In-window decision", "Owner action", "Drift risk"}


def test_build_weekly_input_audit_totals(vault: Path) -> None:
    from ghostbrain.worker.weekly_digest import build_weekly_input

    week_end = date(2026, 5, 10)
    _write_audit(vault, date(2026, 5, 5), [
        {"event_type": "event_processed", "status": "success",
         "context": "sanlam", "source": "github"},
        {"event_type": "event_processed", "status": "success",
         "context": "sanlam", "source": "github"},
        {"event_type": "event_processed", "status": "success",
         "context": "codeship", "source": "claude-code"},
    ])
    _write_audit(vault, date(2026, 5, 10), [
        {"event_type": "event_processed", "status": "success",
         "context": "sanlam", "source": "slack"},
    ])
    # Out of window — should not count
    _write_audit(vault, date(2026, 4, 30), [
        {"event_type": "event_processed", "status": "success",
         "context": "sanlam", "source": "github"},
    ])

    inp = build_weekly_input(week_end)
    assert inp.total_events == 4
    assert inp.activity_by_context["sanlam"] == 3
    assert inp.activity_by_context["codeship"] == 1
    assert inp.activity_by_source["github"] == 2
    assert inp.activity_by_source["slack"] == 1


def test_build_weekly_input_marks_quiet_contexts(vault: Path) -> None:
    from ghostbrain.worker.weekly_digest import build_weekly_input

    week_end = date(2026, 5, 10)
    _write_audit(vault, date(2026, 5, 5), [
        {"event_type": "event_processed", "status": "success",
         "context": "sanlam", "source": "github"},
    ] * 30)

    inp = build_weekly_input(week_end)
    # sanlam very active, others silent → others should appear in quiet
    assert "sanlam" not in inp.quiet_contexts
    assert "codeship" in inp.quiet_contexts
    assert "reducedrecipes" in inp.quiet_contexts
    assert "personal" in inp.quiet_contexts


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def test_render_emits_wikilinks_for_artifacts(vault: Path) -> None:
    from ghostbrain.worker.weekly_digest import (
        build_weekly_input,
        render_weekly_input_for_prompt,
    )

    week_end = date(2026, 5, 10)
    _write_artifact(vault, context="sanlam", artifact_type="decision",
                     title="Defer SIMI", created="2026-05-07T10:00:00Z")
    _write_artifact(vault, context="sanlam", artifact_type="action_item",
                     title="Send funding doc", created="2026-05-08T10:00:00Z")

    inp = build_weekly_input(week_end)
    rendered = render_weekly_input_for_prompt(inp)

    # Wikilink form should be aliased: [[path|alias]]
    assert "[[20-contexts/sanlam/calendar/artifacts/decisions/" in rendered
    assert "|defer-simi]]" in rendered or "defer-simi]" in rendered
    # Type grouping should appear
    assert "decisions (1):" in rendered
    assert "action_items (1):" in rendered


# ---------------------------------------------------------------------------
# generate_weekly_digest
# ---------------------------------------------------------------------------


def test_generate_weekly_digest_writes_to_vault(vault: Path) -> None:
    from ghostbrain.worker import weekly_digest as wd
    from ghostbrain.llm.client import LLMResult

    week_end = date(2026, 5, 10)
    _write_daily_digest(vault, week_end, ["sanlam"], "Productive week.")
    _write_audit(vault, week_end, [
        {"event_type": "event_processed", "status": "success",
         "context": "sanlam", "source": "github"},
    ])

    canned = LLMResult(
        text="# Week 2026-W19 — 2026-05-04 → 2026-05-10\n\nReal body.",
        structured=None, model="sonnet", cost_usd=0.0,
        duration_ms=1, session_id="s", raw={},
    )
    with patch("ghostbrain.worker.weekly_digest.llm.run", return_value=canned):
        out = wd.generate_weekly_digest(week_end)

    assert out.exists()
    assert out.parent == vault / "10-daily" / "weekly"
    body = out.read_text(encoding="utf-8")
    assert "Real body" in body
    # Frontmatter sanity
    assert "type: weekly_digest" in body
    assert "isoWeek: " in body


def test_generate_weekly_falls_back_when_llm_errors(vault: Path) -> None:
    from ghostbrain.worker import weekly_digest as wd
    from ghostbrain.llm import client as llm

    week_end = date(2026, 5, 10)
    _write_artifact(vault, context="sanlam", artifact_type="decision",
                     title="Real decision", created="2026-05-08T10:00:00Z")
    _write_audit(vault, week_end, [
        {"event_type": "event_processed", "status": "success",
         "context": "sanlam", "source": "github"},
    ])

    with patch("ghostbrain.worker.weekly_digest.llm.run",
                side_effect=llm.LLMError("budget")):
        out = wd.generate_weekly_digest(week_end)

    body = out.read_text(encoding="utf-8")
    # Mechanical fallback should still surface the decision.
    assert "Real decision" in body
    assert "Decisions" in body


def test_generate_weekly_empty_week_skips_llm(vault: Path) -> None:
    from ghostbrain.worker import weekly_digest as wd

    week_end = date(2026, 5, 10)
    # No daily, no artifacts, no audit → should NOT call the LLM.
    sentinel = []

    def explode(*a, **kw):
        sentinel.append("called")
        raise AssertionError("LLM should not be called for empty week")

    with patch("ghostbrain.worker.weekly_digest.llm.run", side_effect=explode):
        out = wd.generate_weekly_digest(week_end)

    body = out.read_text(encoding="utf-8")
    assert "Quiet week" in body
    assert sentinel == []
