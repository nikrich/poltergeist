"""B4: the weekly profile applier writes through the vault write path."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from ghostbrain.changes import log as changes
from ghostbrain.history import store
from ghostbrain.vault_write import set_hold_policy

DAY = date(2026, 5, 7)
CP = "80-profile/current-projects.md"
REVIEW = "80-profile/_review.md"


def _proposal(field: str, after: str, *, op: str = "add", parent_path: str = "") -> dict:
    return {
        "field": field, "operation": op, "before": "", "after": after,
        "evidence": "...", "confidence": 0.92, "proposed_at": "2026-05-07T10:00:00Z",
        "parent_event_id": "x", "parent_session_id": None, "parent_note_path": parent_path,
    }


def _write_proposed(vault: Path, proposals: list[dict]) -> None:
    out = vault / "80-profile" / "_proposed" / "2026-05-05.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(p) + "\n" for p in proposals), encoding="utf-8")


def _three_adds(vault: Path, text: str = "Ship the importer") -> None:
    parent = str(vault / "20-contexts" / "work" / "x" / "p.md")
    _write_proposed(vault, [_proposal("current-projects", text, parent_path=parent) for _ in range(3)])


def _audit_statuses(vault: Path) -> list[str]:
    out: list[str] = []
    for f in sorted((vault / "90-meta" / "audit").glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec.get("event_type") == "profile_diff_applied":
                out.append(rec.get("status"))
    return out


@pytest.fixture(autouse=True)
def _reset_policy():
    yield
    set_hold_policy(None)


def test_current_projects_bytes_match_the_old_algorithm(vault: Path) -> None:
    from ghostbrain.profile import apply as ap

    original = (
        "---\nupdated: 2026-01-01  # hand-kept\n---\n# Current projects\n\n"
        "## work\n\n- Existing thing\n\n## personal\n"
    )
    (vault / CP).write_text(original, encoding="utf-8")
    _three_adds(vault)
    ap.apply_weekly(target_date=DAY)
    assert (vault / CP).read_text(encoding="utf-8") == ap._insert_bullet_under_h2(
        original, "work", "- Ship the importer")


def test_the_change_is_listed_as_the_profile_job_and_revertible(vault: Path) -> None:
    from ghostbrain.changes import revert as rv
    from ghostbrain.profile import apply as ap

    before = (vault / CP).read_bytes()  # seeded by bootstrap
    _three_adds(vault)
    ap.apply_weekly(target_date=DAY)
    [row] = changes.list_changes(actor="worker:profile-apply")
    assert (row.rel_path, row.op) == (CP, "modify")
    assert row.reason == "added 1 current project(s) from your sessions"
    [snap] = store.list_snapshots(CP)
    assert snap.actor == "worker:profile-apply" and store.get_blob(snap.blob) == before
    assert _audit_statuses(vault) == ["applied"]
    rv.revert(row.id)
    assert (vault / CP).read_bytes() == before


def test_stable_proposals_append_to_the_review_file(vault: Path) -> None:
    from ghostbrain.profile import apply as ap

    (vault / REVIEW).write_text("# Profile diffs awaiting review\n", encoding="utf-8")
    cp_before = (vault / CP).read_bytes()
    parent = str(vault / "20-contexts" / "work" / "x" / "p.md")
    _write_proposed(vault, [
        _proposal("preferences", "Use ruff over flake8", op="update", parent_path=parent)
        for _ in range(5)
    ])
    ap.apply_weekly(target_date=DAY)
    assert "Use ruff over flake8" in (vault / REVIEW).read_text(encoding="utf-8")
    assert (vault / CP).read_bytes() == cp_before
    [row] = changes.list_changes(actor="worker:profile-apply")
    assert (row.rel_path, row.reason) == (REVIEW, "queued 1 profile change(s) for review")


def test_a_missing_current_projects_is_created_and_not_listed(vault: Path) -> None:
    from ghostbrain.profile import apply as ap

    (vault / CP).unlink()
    _three_adds(vault)
    ap.apply_weekly(target_date=DAY)
    assert "- Ship the importer" in (vault / CP).read_text(encoding="utf-8")
    assert changes.list_changes(actor="worker:profile-apply") == []  # a worker create is ingest


def test_a_held_profile_write_leaves_the_file_alone(vault: Path) -> None:
    from ghostbrain.profile import apply as ap

    set_hold_policy(lambda _p: ["held for test"])
    before = (vault / CP).read_bytes()
    _three_adds(vault)
    result = ap.apply_weekly(target_date=DAY)
    assert len(result.applied) == 1
    assert (vault / CP).read_bytes() == before
    [row] = changes.list_changes(status="pending")
    assert row.rel_path == CP
    assert _audit_statuses(vault) == ["pending"]
