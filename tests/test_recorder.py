"""Tests for the autonomous recorder daemon. Pure logic — ffmpeg, whisper,
audio switching all mocked."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ghostbrain.recorder.policy import RecorderPolicy, should_record
from ghostbrain.recorder.sources.base import events_from_connector_dicts


# ---------------------------------------------------------------------------
# policy
# ---------------------------------------------------------------------------


def test_policy_skips_focus_titles() -> None:
    policy = RecorderPolicy(excluded_titles=("Focus", "focus"))
    ok, reason = should_record(title="Focus", context="work", policy=policy)
    assert ok is False
    assert "exclusion" in reason.lower()


def test_policy_case_insensitive() -> None:
    policy = RecorderPolicy(excluded_titles=("Focus",))
    for title in ("Focus", "focus", "FOCUS", "FoCuS"):
        ok, _ = should_record(title=title, context="work", policy=policy)
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
        included_contexts=("work", "consulting"),
    )
    assert should_record(title="x", context="work", policy=policy)[0] is True
    assert should_record(title="x", context="personal", policy=policy)[0] is False


def test_policy_disabled_blocks_everything() -> None:
    policy = RecorderPolicy(enabled=False)
    ok, _ = should_record(title="anything", context="work", policy=policy)
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
            event_id="ev1", title="Test", context="work",
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


class FakeSource:
    """Test double for MeetingSource: returns a fixed list of MeetingEvents."""

    id = "fake"

    def __init__(self, events) -> None:
        self._events = events

    def events(self, now):
        return self._events


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
        macos_accounts={"Calendar": "work"},
    )
    state = state_mod.RecorderState()

    events = events_from_connector_dicts(
        [focus_event, in_progress], config.macos_accounts,
    )
    candidate = _next_eligible_event(
        config, state, now, sources=[FakeSource(events)],
    )

    assert candidate is not None
    assert candidate.event_id == "ev-real"
    assert candidate.context == "work"
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
        macos_accounts={"Calendar": "work"},
    )
    state = state_mod.RecorderState(
        processed={"ev-done": now.isoformat()},
    )

    events = events_from_connector_dicts([event], config.macos_accounts)
    candidate = _next_eligible_event(
        config, state, now, sources=[FakeSource(events)],
    )

    assert candidate is None


class FakeBackend:
    """Test double for AudioBackend: records every call so tests can assert
    ordering (begin_route before start, stop before end_route) without any
    real ffmpeg/SwitchAudioSource process."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def preflight(self):
        return True, []

    def begin_meeting_route(self, device, fallback):
        self.calls.append(("begin_route", device))
        from ghostbrain.recorder.audio.base import RouteHandle
        return RouteHandle(previous_output="Speakers", switched=True)

    def end_meeting_route(self, handle):
        self.calls.append(("end_route", handle.previous_output))

    def start_capture(self, wav_path, *, log_path=None):
        self.calls.append(("start", str(wav_path)))
        from ghostbrain.recorder.audio_capture import CaptureHandle
        return CaptureHandle(pid=4242, wav_path=wav_path)

    def stop_capture(self, pid):
        self.calls.append(("stop", pid))
        return True

    def capture_alive(self, pid):
        return True


def test_start_recording_uses_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_start_recording routes + captures via the backend, no direct
    audio_switcher/audio_capture calls."""
    from ghostbrain.recorder import daemon, state as state_mod
    backend = FakeBackend()
    monkeypatch.setattr(daemon, "DEFAULT_RECORDINGS_DIR", tmp_path)
    config = daemon.DaemonConfig(
        poll_interval_s=30, end_grace_s=60, audio_device="Ghost Brain",
        fallback_output="", policy=RecorderPolicy(), macos_accounts={},
    )
    state = state_mod.RecorderState()
    candidate = daemon._Candidate(
        event_id="ev1", title="standup", context="work",
        start=datetime.now(timezone.utc),
        end=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    daemon._start_recording(candidate, config, state, backend)
    assert ("begin_route", config.audio_device) in backend.calls
    assert any(c[0] == "start" for c in backend.calls)
    assert state.active is not None and state.active.pid == 4242
    # RouteHandle.previous_output still stashed under the legacy key so an
    # old-version _finalize (or a downgrade) can restore correctly.
    assert state.processed["_audio_before:ev1"] == "Speakers"


def test_start_recording_ends_route_on_capture_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If start_capture raises, the route must be unwound through the
    backend (backend.end_meeting_route), not a manual switch-back."""
    from ghostbrain.recorder import daemon, state as state_mod

    class FailingBackend(FakeBackend):
        def start_capture(self, wav_path, *, log_path=None):
            self.calls.append(("start", str(wav_path)))
            raise RuntimeError("ffmpeg boom")

    backend = FailingBackend()
    monkeypatch.setattr(daemon, "DEFAULT_RECORDINGS_DIR", tmp_path)
    config = daemon.DaemonConfig(
        poll_interval_s=30, end_grace_s=60, audio_device="Ghost Brain",
        fallback_output="", policy=RecorderPolicy(), macos_accounts={},
    )
    state = state_mod.RecorderState()
    candidate = daemon._Candidate(
        event_id="ev2", title="standup", context="work",
        start=datetime.now(timezone.utc),
        end=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    daemon._start_recording(candidate, config, state, backend)
    assert backend.calls[-1] == ("end_route", "Speakers")
    assert state.active is None
    assert "ev2" in state.processed


def test_finalize_stops_capture_and_restores_route(tmp_path: Path) -> None:
    """_finalize stops via the backend and restores the previous output via
    backend.end_meeting_route, using the value stashed at start."""
    from ghostbrain.recorder import daemon, state as state_mod
    backend = FakeBackend()
    config = daemon.DaemonConfig(
        poll_interval_s=30, end_grace_s=60, audio_device="Ghost Brain",
        fallback_output="", policy=RecorderPolicy(), macos_accounts={},
    )
    active = state_mod.ActiveRecording(
        event_id="ev3", title="standup", context="work", pid=999,
        wav_path=str(tmp_path / "missing.wav"),
        started_at=datetime.now(timezone.utc).isoformat(),
        scheduled_end=datetime.now(timezone.utc).isoformat(),
    )
    state = state_mod.RecorderState(active=active)
    state.processed["_audio_before:ev3"] = "MacBook Pro Speakers"

    daemon._finalize(active, config, state, backend, reason="scheduled_end")

    assert ("stop", 999) in backend.calls
    assert ("end_route", "MacBook Pro Speakers") in backend.calls
    # Legacy stash key must be popped so a restarted daemon doesn't reuse it.
    assert "_audio_before:ev3" not in state.processed


def test_finalize_pops_legacy_audio_before_key_for_in_flight_recording(
    tmp_path: Path,
) -> None:
    """A recording started under the pre-backend daemon stashed the same
    `_audio_before:{event_id}` key; _finalize must still pop + honor it so
    an in-flight recording survives the upgrade."""
    from ghostbrain.recorder import daemon, state as state_mod
    backend = FakeBackend()
    config = daemon.DaemonConfig(
        poll_interval_s=30, end_grace_s=60, audio_device="Ghost Brain",
        fallback_output="Fallback Speakers", policy=RecorderPolicy(),
        macos_accounts={},
    )
    active = state_mod.ActiveRecording(
        event_id="ev4", title="standup", context="work", pid=1000,
        wav_path=str(tmp_path / "missing.wav"),
        started_at=datetime.now(timezone.utc).isoformat(),
        scheduled_end=datetime.now(timezone.utc).isoformat(),
    )
    state = state_mod.RecorderState(active=active)
    state.processed["_audio_before:ev4"] = "Old Speakers"

    daemon._finalize(active, config, state, backend, reason="daemon_shutdown")

    assert ("end_route", "Old Speakers") in backend.calls
    assert "_audio_before:ev4" not in state.processed


def test_finalize_falls_back_to_config_when_no_stash(tmp_path: Path) -> None:
    """No `_audio_before` stash (e.g. crash before it was written) falls
    back to config.fallback_output."""
    from ghostbrain.recorder import daemon, state as state_mod
    backend = FakeBackend()
    config = daemon.DaemonConfig(
        poll_interval_s=30, end_grace_s=60, audio_device="Ghost Brain",
        fallback_output="Fallback Speakers", policy=RecorderPolicy(),
        macos_accounts={},
    )
    active = state_mod.ActiveRecording(
        event_id="ev5", title="standup", context="work", pid=1001,
        wav_path=str(tmp_path / "missing.wav"),
        started_at=datetime.now(timezone.utc).isoformat(),
        scheduled_end=datetime.now(timezone.utc).isoformat(),
    )
    state = state_mod.RecorderState(active=active)

    daemon._finalize(active, config, state, backend, reason="scheduled_end")

    assert ("end_route", "Fallback Speakers") in backend.calls


def test_should_finalize_uses_backend_capture_alive() -> None:
    """Liveness check goes through backend.capture_alive, not
    audio_capture.is_running directly."""
    from ghostbrain.recorder import daemon, state as state_mod
    active = state_mod.ActiveRecording(
        event_id="ev6", title="standup", context="work", pid=555,
        wav_path="/tmp/x.wav",
        started_at=datetime.now(timezone.utc).isoformat(),
        scheduled_end=(datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
    )
    config = daemon.DaemonConfig(
        poll_interval_s=30, end_grace_s=60, audio_device="Ghost Brain",
        fallback_output="", policy=RecorderPolicy(), macos_accounts={},
    )

    class DeadBackend(FakeBackend):
        def capture_alive(self, pid):
            self.calls.append(("alive", pid))
            return False

    backend = DeadBackend()
    now = datetime.now(timezone.utc)
    assert daemon._should_finalize(active, now, config, backend) is True
    assert ("alive", 555) in backend.calls


def test_run_once_uses_injected_backend_not_get_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run_once(config, state, backend) must use the injected backend and
    never call get_backend() itself when one is supplied."""
    from ghostbrain.recorder import daemon, state as state_mod
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(daemon, "DEFAULT_RECORDINGS_DIR", tmp_path)
    monkeypatch.setattr(daemon, "manual_recovery_pass", lambda: [])

    def _boom(*_a, **_kw):
        raise AssertionError("get_backend() should not be called when a "
                              "backend is injected")

    monkeypatch.setattr(daemon, "get_backend", _boom)

    config = daemon.DaemonConfig(
        poll_interval_s=30, end_grace_s=60, audio_device="Ghost Brain",
        fallback_output="", policy=RecorderPolicy(), macos_accounts={},
    )
    state = state_mod.RecorderState()
    backend = FakeBackend()
    # No calendar accounts configured -> _next_eligible_event short-circuits
    # to None, so this tick only needs to prove get_backend() was never hit.
    daemon.run_once(config, state, backend)


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
        macos_accounts={"Calendar": "work"},
    )
    state = state_mod.RecorderState()

    events = events_from_connector_dicts([future], config.macos_accounts)
    candidate = _next_eligible_event(
        config, state, now, sources=[FakeSource(events)],
    )
    assert candidate is None


class RaisingSource:
    """Test double for MeetingSource: always raises from events()."""

    id = "raising"

    def events(self, now):
        raise RuntimeError("boom")


def test_next_eligible_event_skips_source_that_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, vault: Path,
) -> None:
    """A misbehaving source must not abort the whole tick; the good
    source's event should still be found eligible."""
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path))
    import importlib
    from ghostbrain.recorder import state as state_mod
    importlib.reload(state_mod)
    from ghostbrain.recorder.daemon import DaemonConfig, _next_eligible_event

    now = datetime(2026, 5, 8, 10, 30, tzinfo=timezone.utc)
    good_event = _candidate_event(
        event_id="ev-good",
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
    state = state_mod.RecorderState()

    events = events_from_connector_dicts([good_event], config.macos_accounts)
    candidate = _next_eligible_event(
        config, state, now, sources=[RaisingSource(), FakeSource(events)],
    )

    assert candidate is not None
    assert candidate.event_id == "ev-good"


# ---------------------------------------------------------------------------
# C1: sources built once per daemon lifetime (not rebuilt every tick)
# ---------------------------------------------------------------------------


class CountingCachingSource:
    """Mimics GoogleSource/MicrosoftSource's own refresh-window cache: a
    fetch only happens once per `refresh_s`. Reusing the SAME instance
    across ticks is what makes that throttle effective."""

    id = "counting"

    def __init__(self, counter: dict, *, refresh_s: int = 300) -> None:
        self._counter = counter
        self._refresh_s = refresh_s
        self._cache: list = []
        self._fetched_at = None

    def events(self, now):
        if (self._fetched_at is not None
                and (now - self._fetched_at).total_seconds() < self._refresh_s):
            return self._cache
        self._counter["n"] += 1
        self._fetched_at = now
        return self._cache


def test_run_once_reuses_injected_sources_across_ticks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the same `sources` list is passed to run_once on consecutive
    ticks (as the fixed run_loop/recorder_daemon now do), a caching source's
    own refresh window suppresses the second fetch."""
    from ghostbrain.recorder import daemon, state as state_mod

    monkeypatch.setattr(daemon, "DEFAULT_RECORDINGS_DIR", tmp_path)
    monkeypatch.setattr(daemon, "manual_recovery_pass", lambda: [])

    counter = {"n": 0}
    source = CountingCachingSource(counter)
    config = daemon.DaemonConfig(
        poll_interval_s=30, end_grace_s=60, audio_device="Ghost Brain",
        fallback_output="", policy=RecorderPolicy(), macos_accounts={},
    )
    state = state_mod.RecorderState()
    backend = FakeBackend()

    daemon.run_once(config, state, backend, sources=[source])
    daemon.run_once(config, state, backend, sources=[source])

    assert counter["n"] == 1


def test_run_loop_builds_sources_once_per_lifetime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, vault: Path,
) -> None:
    """run_loop must call select_sources exactly once (before the while
    loop), never rebuilding sources on each tick — that was C1: rebuilding
    fresh source objects every 30s tick reset each source's own refresh-
    window cache, so remote sources (google/microsoft) got fetched on every
    tick instead of at most every 5 minutes."""
    from ghostbrain.recorder import daemon, state as state_mod

    monkeypatch.setattr(daemon, "DEFAULT_RECORDINGS_DIR", tmp_path)
    monkeypatch.setattr(daemon, "manual_recovery_pass", lambda: [])
    monkeypatch.setattr(
        daemon.DaemonConfig, "load",
        staticmethod(lambda: daemon.DaemonConfig(
            poll_interval_s=0, end_grace_s=60, audio_device="Ghost Brain",
            fallback_output="", policy=RecorderPolicy(), macos_accounts={},
        )),
    )
    monkeypatch.setattr(state_mod, "load", lambda: state_mod.RecorderState())
    monkeypatch.setattr(state_mod, "prune_processed", lambda *_a, **_kw: None)
    monkeypatch.setattr(state_mod, "save", lambda *_a, **_kw: None)

    backend = FakeBackend()
    monkeypatch.setattr(daemon, "get_backend", lambda **_kw: backend)

    calls = {"n": 0}

    def fake_select_sources(routing, recorder_cfg):
        calls["n"] += 1
        return [], []

    monkeypatch.setattr(daemon, "select_sources", fake_select_sources)

    ticks = {"n": 0}

    def fake_sleep(_seconds):
        ticks["n"] += 1
        if ticks["n"] >= 2:
            daemon._running = False

    monkeypatch.setattr(daemon.time, "sleep", fake_sleep)
    daemon._running = True
    try:
        daemon.run_loop()
    finally:
        daemon._running = True  # restore module default for other tests

    assert ticks["n"] == 2
    assert calls["n"] == 1
