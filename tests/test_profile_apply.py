"""Tests for the weekly profile-diff applier."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path


def _proposal(field: str, after: str, *, op: str = "add",
              parent_path: str = "", confidence: float = 0.92) -> dict:
    return {
        "field": field, "operation": op,
        "before": "", "after": after,
        "evidence": "...", "confidence": confidence,
        "proposed_at": "2026-05-07T10:00:00Z",
        "parent_event_id": "x", "parent_session_id": None,
        "parent_note_path": parent_path,
    }


def _write_proposed(vault: Path, day: date, proposals: list[dict]) -> None:
    out = vault / "80-profile" / "_proposed" / f"{day.isoformat()}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for p in proposals:
            f.write(json.dumps(p) + "\n")


def _configure_contexts(vault: Path, ctxs: list[str]) -> None:
    f = vault / "90-meta" / "routing.yaml"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("contexts:\n" + "\n".join(f"  - {c}" for c in ctxs))


def test_default_current_projects_doc_uses_configured_contexts(vault: Path) -> None:
    """When current-projects.md doesn't exist yet, the applier's own default
    body (not bootstrap's) must derive its H2 sections from routing_config,
    not the legacy hardcoded four."""
    from ghostbrain.profile.apply import apply_weekly

    _configure_contexts(vault, ["alpha"])
    target = vault / "80-profile" / "current-projects.md"
    target.unlink()  # bootstrap seeds one; delete to exercise apply.py's own default

    parent = str(vault / "20-contexts" / "alpha" / "p.md")
    _write_proposed(vault, date(2026, 5, 5), [
        _proposal("current-projects", "Ship the thing", parent_path=parent)
        for _ in range(3)
    ])

    apply_weekly(target_date=date(2026, 5, 7))

    cp = target.read_text()
    assert "## alpha" in cp
    for legacy in ("sanlam", "codeship", "reducedrecipes"):
        assert f"## {legacy}" not in cp


def test_three_corroborating_adds_apply_to_current_projects(vault: Path) -> None:
    from ghostbrain.profile.apply import apply_weekly

    parent = str(vault / "20-contexts" / "codeship" / "claude" / "sessions" / "p.md")
    _write_proposed(vault, date(2026, 5, 5), [
        _proposal("current-projects", "Building ghost-brain", parent_path=parent),
        _proposal("current-projects", "building ghost-brain", parent_path=parent),  # normalized match
    ])
    _write_proposed(vault, date(2026, 5, 6), [
        _proposal("current-projects", "Building ghost-brain.", parent_path=parent),
    ])

    result = apply_weekly(target_date=date(2026, 5, 7))

    assert len(result.applied) == 1
    cp = (vault / "80-profile" / "current-projects.md").read_text()
    assert "Building ghost-brain" in cp
    # Bullet should land under codeship since parent paths point there.
    sec = cp.split("## codeship", 1)[1].split("\n## ", 1)[0]
    assert "Building ghost-brain" in sec


def test_one_proposal_discarded(vault: Path) -> None:
    from ghostbrain.profile.apply import apply_weekly

    _write_proposed(vault, date(2026, 5, 6), [
        _proposal("current-projects", "Tried something once"),
    ])
    result = apply_weekly(target_date=date(2026, 5, 7))
    assert result.applied == []
    assert result.discarded_count == 1


def test_stable_field_proposals_always_deferred(vault: Path) -> None:
    from ghostbrain.profile.apply import apply_weekly

    # 5 corroborating "preferences" updates — must NOT auto-apply.
    parent = str(vault / "20-contexts" / "codeship" / "x" / "p.md")
    _write_proposed(vault, date(2026, 5, 5), [
        _proposal("preferences", "Use ruff over flake8", op="update",
                  parent_path=parent)
        for _ in range(5)
    ])

    result = apply_weekly(target_date=date(2026, 5, 7))
    assert result.applied == []
    assert any("preferences" in line for line in result.deferred_for_review)
    review = (vault / "80-profile" / "_review.md").read_text()
    assert "Use ruff over flake8" in review


def test_no_proposals_within_window_is_noop(vault: Path) -> None:
    from ghostbrain.profile.apply import apply_weekly

    # Older than 7 days → ignored.
    _write_proposed(vault, date(2026, 4, 1), [
        _proposal("current-projects", "Old thing"),
        _proposal("current-projects", "Old thing"),
        _proposal("current-projects", "Old thing"),
    ])
    result = apply_weekly(target_date=date(2026, 5, 7))
    assert result.applied == []
    assert result.discarded_count == 0


def test_grouping_preserves_distinct_facts(vault: Path) -> None:
    from ghostbrain.profile.apply import apply_weekly

    parent = str(vault / "20-contexts" / "codeship" / "claude" / "sessions" / "p.md")
    _write_proposed(vault, date(2026, 5, 5), [
        _proposal("current-projects", "A", parent_path=parent),
        _proposal("current-projects", "A", parent_path=parent),
        _proposal("current-projects", "A", parent_path=parent),
        _proposal("current-projects", "B", parent_path=parent),
    ])
    result = apply_weekly(target_date=date(2026, 5, 7))
    assert len(result.applied) == 1
    # 1 proposal for "B" → discarded (below 3 threshold).
    cp = (vault / "80-profile" / "current-projects.md").read_text()
    assert "- A" in cp
    assert "- B" not in cp


def test_picks_h2_from_parent_note_paths(vault: Path) -> None:
    from ghostbrain.profile.apply import apply_weekly

    sanlam_parent = str(vault / "20-contexts" / "sanlam" / "x" / "p.md")
    _write_proposed(vault, date(2026, 5, 5), [
        _proposal("current-projects", "ASCP capstone work", parent_path=sanlam_parent)
        for _ in range(3)
    ])
    apply_weekly(target_date=date(2026, 5, 7))

    cp = (vault / "80-profile" / "current-projects.md").read_text()
    sanlam_sec = cp.split("## sanlam", 1)[1].split("\n## ", 1)[0]
    assert "ASCP capstone work" in sanlam_sec
