"""Tests for the Connector base — queue filename bounding."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from ghostbrain.connectors._base import Connector, _queue_filename


class _Dummy(Connector):
    name = "dummy"

    def fetch(self, since):
        return []

    def normalize(self, raw):
        return raw

    def health_check(self) -> bool:
        return True


def test_short_id_keeps_readable_filename() -> None:
    fn = _queue_filename("2026-06-05T09-00-00", "gmail", "gmail:thread:abc123")
    assert fn == "2026-06-05T09-00-00-gmail-gmail-thread-abc123.json"


def test_long_id_is_bounded_and_deterministic() -> None:
    long_id = "microsoft:transcript:" + "A" * 200 + ":" + "B" * 200
    fn1 = _queue_filename("2026-06-05T09-00-00", "teams_meetings", long_id)
    fn2 = _queue_filename("2026-06-05T09-00-00", "teams_meetings", long_id)
    assert fn1 == fn2  # deterministic → re-enqueue stays idempotent
    assert len(fn1) <= 255
    assert fn1.startswith("2026-06-05T09-00-00-teams_meetings-")
    assert fn1.endswith(".json")


def test_enqueue_writes_event_with_overlong_id(tmp_path: Path) -> None:
    conn = _Dummy(config={}, queue_dir=tmp_path / "q", state_dir=tmp_path / "s")
    event = {
        "id": "microsoft:transcript:" + "X" * 300,
        "timestamp": datetime(2026, 6, 5, tzinfo=timezone.utc).isoformat(),
        "body": "hello",
    }
    conn._enqueue(event)  # must not raise OSError: File name too long
    pending = list((tmp_path / "q" / "pending").glob("*.json"))
    assert len(pending) == 1
    assert len(pending[0].name) <= 255
