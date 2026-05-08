"""Tests for the autonomous recorder daemon. Pure logic — ffmpeg, whisper,
audio switching all mocked."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ghostbrain.recorder.policy import RecorderPolicy, should_record


# ---------------------------------------------------------------------------
# policy
# ---------------------------------------------------------------------------


def test_policy_skips_focus_titles() -> None:
    policy = RecorderPolicy(excluded_titles=("Focus", "focus"))
    ok, reason = should_record(title="Focus", context="sanlam", policy=policy)
    assert ok is False
    assert "exclusion" in reason.lower()


def test_policy_case_insensitive() -> None:
    policy = RecorderPolicy(excluded_titles=("Focus",))
    for title in ("Focus", "focus", "FOCUS", "FoCuS"):
        ok, _ = should_record(title=title, context="sanlam", policy=policy)
        assert ok is False, title


def test_policy_wildcard_matches() -> None:
    policy = RecorderPolicy(excluded_titles=("Focus*", "1:1*"))
    assert should_record(title="Focus block", context="x", policy=policy)[0] is False
    assert should_record(title="1:1 with Alex", context="x", policy=policy)[0] is False
    assert should_record(title="Real meeting", context="x", policy=policy)[0] is True


def test_policy_excluded_contexts() -> None:
    policy = RecorderPolicy(
        excluded_titles=(),
        excluded_contexts=("personal",),
    )
    ok, reason = should_record(title="Standup", context="personal", policy=policy)
    assert ok is False
    assert "context excluded" in reason


def test_policy_included_contexts_acts_as_whitelist() -> None:
    policy = RecorderPolicy(
        excluded_titles=(),
        included_contexts=("sanlam", "codeship"),
    )
    assert should_record(title="x", context="sanlam", policy=policy)[0] is True
    assert should_record(title="x", context="personal", policy=policy)[0] is False


def test_policy_disabled_blocks_everything() -> None:
    policy = RecorderPolicy(enabled=False)
    ok, _ = should_record(title="anything", context="sanlam", policy=policy)
    assert ok is False


# ---------------------------------------------------------------------------
# state
# ---------------------------------------------------------------------------


def test_state_roundtrip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path))
    import importlib
    from ghostbrain.recorder import state as state_mod
    importlib.reload(state_mod)

    s = state_mod.RecorderState(
        active=state_mod.ActiveRecording(
            event_id="ev1", title="Test", context="sanlam",
            pid=12345, wav_path="/tmp/x.wav",
            started_at="2026-05-08T10:00:00+00:00",
            scheduled_end="2026-05-08T10:30:00+00:00",
        ),
        processed={"ev0": "2026-05-08T09:00:00+00:00"},
    )
    state_mod.save(s)

    loaded = state_mod.load()
    assert loaded.active is not None
    assert loaded.active.event_id == "ev1"
    assert loaded.processed == {"ev0": "2026-05-08T09:00:00+00:00"}


def test_state_prune_drops_old_processed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path))
    import importlib
    from ghostbrain.recorder import state as state_mod
    importlib.reload(state_mod)

    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=30)).isoformat()
    fresh = (now - timedelta(days=2)).isoformat()
    s = state_mod.RecorderState(
        active=None,
        processed={"old": old, "fresh": fresh},
    )
    state_mod.prune_processed(s, retention_days=14)
    assert "old" not in s.processed
    assert "fresh" in s.processed


# ---------------------------------------------------------------------------
# daemon decision
# ---------------------------------------------------------------------------


def _candidate_event(
    *, event_id: str, title: str, account: str,
    start: datetime, end: datetime,
) -> dict:
    return {
        "id": event_id,
        "source": "calendar",
        "type": "event",
        "title": title,
        "metadata": {
            "provider": "macos",
            "account": account,
            "start": start.isoformat(),
            "end":   end.isoformat(),
            "isAllDay": False,
        },
    }


def test_daemon_picks_in_progress_eligible_event(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, vault: Path,
) -> None:
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path))
    import importlib
    from ghostbrain.recorder import state as state_mod
    importlib.reload(state_mod)

    from ghostbrain.recorder.daemon import (
        DaemonConfig, _next_eligible_event,
    )

    now = datetime(2026, 5, 8, 10, 30, tzinfo=timezone.utc)
    in_progress = _candidate_event(
        event_id="ev-real",
        title="TrustFlow Deep Dive",
        account="Calendar",
        start=now - timedelta(minutes=2),
        end=now + timedelta(minutes=28),
    )
    focus_event = _candidate_event(
        event_id="ev-focus",
        title="Focus",
        account="Calendar",
        start=now - timedelta(minutes=1),
        end=now + timedelta(minutes=29),
    )

    config = DaemonConfig(
        poll_interval_s=30, end_grace_s=60,
        audio_device="Ghost Brain", fallback_output="",
        policy=RecorderPolicy(),
        macos_accounts={"Calendar": "sanlam"},
    )
    state = state_mod.RecorderState()

    fake_connector = MagicMock()
    fake_connector.fetch.return_value = [focus_event, in_progress]
    with patch(
        "ghostbrain.recorder.daemon.MacosCalendarConnector",
        return_value=fake_connector,
    ):
        candidate = _next_eligible_event(config, state, now)

    assert candidate is not None
    assert candidate.event_id == "ev-real"
    assert candidate.context == "sanlam"
    # Focus should have been recorded as processed (skipped)
    assert "ev-focus" in state.processed


def test_daemon_skips_already_processed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, vault: Path,
) -> None:
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path))
    import importlib
    from ghostbrain.recorder import state as state_mod
    importlib.reload(state_mod)
    from ghostbrain.recorder.daemon import DaemonConfig, _next_eligible_event

    now = datetime(2026, 5, 8, 10, 30, tzinfo=timezone.utc)
    event = _candidate_event(
        event_id="ev-done",
        title="Real meeting",
        account="Calendar",
        start=now - timedelta(minutes=2),
        end=now + timedelta(minutes=28),
    )

    config = DaemonConfig(
        poll_interval_s=30, end_grace_s=60,
        audio_device="Ghost Brain", fallback_output="",
        policy=RecorderPolicy(),
        macos_accounts={"Calendar": "sanlam"},
    )
    state = state_mod.RecorderState(
        processed={"ev-done": now.isoformat()},
    )

    fake_connector = MagicMock()
    fake_connector.fetch.return_value = [event]
    with patch(
        "ghostbrain.recorder.daemon.MacosCalendarConnector",
        return_value=fake_connector,
    ):
        candidate = _next_eligible_event(config, state, now)

    assert candidate is None


def test_daemon_skips_event_starting_too_far_in_future(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, vault: Path,
) -> None:
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path))
    import importlib
    from ghostbrain.recorder import state as state_mod
    importlib.reload(state_mod)
    from ghostbrain.recorder.daemon import DaemonConfig, _next_eligible_event

    now = datetime(2026, 5, 8, 10, 30, tzinfo=timezone.utc)
    future = _candidate_event(
        event_id="ev-future",
        title="Tomorrow",
        account="Calendar",
        start=now + timedelta(minutes=10),
        end=now + timedelta(minutes=40),
    )

    config = DaemonConfig(
        poll_interval_s=30, end_grace_s=60,
        audio_device="Ghost Brain", fallback_output="",
        policy=RecorderPolicy(),
        macos_accounts={"Calendar": "sanlam"},
    )
    state = state_mod.RecorderState()

    fake_connector = MagicMock()
    fake_connector.fetch.return_value = [future]
    with patch(
        "ghostbrain.recorder.daemon.MacosCalendarConnector",
        return_value=fake_connector,
    ):
        candidate = _next_eligible_event(config, state, now)
    assert candidate is None
