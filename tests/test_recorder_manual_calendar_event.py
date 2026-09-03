"""Regression tests for the manual Record button's "what meeting am I in?" lookup.

``POST /v1/recorder/start`` calls ``_current_calendar_event`` so a manual
recording inherits the live meeting's title, context and parent note. That
lookup compared every calendar note's ``start``/``end`` against a
timezone-aware "now". All-day events are written with date-only strings
(``start: '2026-09-03'``), which ``datetime.fromisoformat`` turns into
*naive* datetimes — and comparing naive with aware raises ``TypeError``.
Nothing caught it, so a single all-day note on the calendar turned every
manual Record press into a bare 500 "Internal Server Error" while the
calendar daemon (which never calls this lookup) kept recording fine.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ghostbrain.api.repo import recorder


def _write_event(vault: Path, name: str, *, start: str, end: str, title: str) -> Path:
    cal = vault / "20-contexts" / "sanlam" / "calendar"
    cal.mkdir(parents=True, exist_ok=True)
    note = cal / f"{name}.md"
    note.write_text(
        "---\n"
        f"title: '{title}'\n"
        "context: sanlam\n"
        f"start: '{start}'\n"
        f"end: '{end}'\n"
        "---\n\n"
        f"# {title}\n",
        encoding="utf-8",
    )
    return note


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    return tmp_path


def test_all_day_event_does_not_break_current_event_lookup(vault: Path) -> None:
    """A date-only all-day note on the calendar must not raise; the live
    timed meeting next to it is still found and linked."""
    now = datetime.now(UTC)
    today = now.date().isoformat()
    _write_event(
        vault,
        f"{today.replace('-', '')}-clinton-on-leave",
        start=today,
        end=(now + timedelta(days=4)).date().isoformat(),
        title="Clinton on leave",
    )
    live = _write_event(
        vault,
        "live-standup",
        start=(now - timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
        end=(now + timedelta(minutes=20)).isoformat().replace("+00:00", "Z"),
        title="Live standup",
    )

    found = recorder._current_calendar_event()

    assert found is not None
    assert found["frontmatter"]["title"] == "Live standup"
    assert found["rel_path"] == str(live.relative_to(vault))


def test_all_day_event_alone_is_not_treated_as_the_current_meeting(vault: Path) -> None:
    """An all-day entry (leave, room block) is not a meeting to record
    against: with only that on the calendar the lookup returns None."""
    now = datetime.now(UTC)
    today = now.date().isoformat()
    _write_event(
        vault,
        "all-day-only",
        start=today,
        end=(now + timedelta(days=1)).date().isoformat(),
        title="Out of office",
    )

    assert recorder._current_calendar_event() is None
