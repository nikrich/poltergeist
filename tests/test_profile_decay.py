"""Tests for the monthly profile decay + promotion."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path


def _write_audit(vault: Path, day: date, events: list[dict]) -> None:
    out = vault / "90-meta" / "audit" / f"{day.isoformat()}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


def _write_current_projects(vault: Path, body: str) -> None:
    p = vault / "80-profile" / "current-projects.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def test_archives_items_not_reinforced_in_60_days(vault: Path) -> None:
    from ghostbrain.profile.decay import decay_monthly

    _write_current_projects(vault,
        "# Current projects\n\n## consulting\n- Stale work\n- Recent work\n"
    )
    # "Stale work" last reinforced 70 days before target.
    _write_audit(vault, date(2026, 2, 26), [
        {"ts": "2026-02-26T10:00:00+00:00",
         "event_type": "profile_diff_applied",
         "after": "Stale work", "field": "current-projects"},
    ])
    # "Recent work" reinforced 5 days before target.
    _write_audit(vault, date(2026, 5, 2), [
        {"ts": "2026-05-02T10:00:00+00:00",
         "event_type": "profile_diff_applied",
         "after": "Recent work", "field": "current-projects"},
    ])

    result = decay_monthly(target_date=date(2026, 5, 7))

    assert result["archived"] == 1
    cp = (vault / "80-profile" / "current-projects.md").read_text()
    assert "Stale work" not in cp
    assert "Recent work" in cp
    archive = (vault / "80-profile" / "_archive.md").read_text()
    assert "Stale work" in archive


def test_proposes_promotion_for_long_stable_items(vault: Path) -> None:
    from ghostbrain.profile.decay import decay_monthly

    _write_current_projects(vault,
        "# Current projects\n\n## consulting\n- Settled fact\n"
    )
    # Last reinforced 35 days ago — between PROMOTION_DAYS and DECAY_DAYS.
    _write_audit(vault, date(2026, 4, 2), [
        {"ts": "2026-04-02T10:00:00+00:00",
         "event_type": "profile_diff_applied",
         "after": "Settled fact"},
    ])

    result = decay_monthly(target_date=date(2026, 5, 7))
    assert result["promoted"] == 1
    pending = (vault / "80-profile" / "_pending_stable.md").read_text()
    assert "Settled fact" in pending


def test_hand_edited_items_left_alone(vault: Path) -> None:
    """Items never touched by the applier (no audit history) shouldn't decay."""
    from ghostbrain.profile.decay import decay_monthly

    _write_current_projects(vault,
        "# Current projects\n\n## work\n- TODO: hand-written placeholder\n"
        "- Hand-curated entry\n"
    )
    result = decay_monthly(target_date=date(2026, 5, 7))
    assert result["archived"] == 0
    cp = (vault / "80-profile" / "current-projects.md").read_text()
    assert "Hand-curated entry" in cp
