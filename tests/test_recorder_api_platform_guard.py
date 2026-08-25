"""Recorder API repo functions must return a clean 'unsupported' when the
audio backend is unsupported (Linux today) and must fall through to normal
logic on any platform with a real backend (darwin, win32)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ghostbrain.api.repo import recorder as recorder_repo


@pytest.fixture
def unsupported_platform():
    """Patch sys.platform inside the audio backend factory to an unsupported value."""
    with patch("ghostbrain.recorder.audio.sys") as mock_sys:
        mock_sys.platform = "linux"
        yield mock_sys


def test_status_raises_on_unsupported_platform(unsupported_platform):
    with pytest.raises(recorder_repo.RecorderUnsupportedError):
        recorder_repo.status()


def test_start_raises_on_unsupported_platform(unsupported_platform):
    with pytest.raises(recorder_repo.RecorderUnsupportedError):
        recorder_repo.start(title=None, context=None)


def test_stop_raises_on_unsupported_platform(unsupported_platform):
    with pytest.raises(recorder_repo.RecorderUnsupportedError):
        recorder_repo.stop()


def test_clear_raises_on_unsupported_platform(unsupported_platform):
    with pytest.raises(recorder_repo.RecorderUnsupportedError):
        recorder_repo.clear()


def test_status_works_on_supported_platform():
    """Sanity: when the backend is supported (darwin here), status() falls
    through to its normal logic (which on a clean test env returns the
    'idle' phase, NOT raises)."""
    with patch("ghostbrain.recorder.audio.sys") as mock_sys:
        mock_sys.platform = "darwin"
        # status() reads state files — patch any I/O that would fail in test env.
        with patch("ghostbrain.api.repo.recorder._read_state", return_value=None), \
             patch("ghostbrain.api.repo.recorder._daemon_active", return_value=None):
            result = recorder_repo.status()
    # status() returns a dict; we just verify it didn't raise UnsupportedError.
    assert isinstance(result, dict)


def test_recorder_functions_do_not_raise_unsupported_on_win32():
    """status/start/stop/clear must resolve to WasapiBackend (not
    UnsupportedBackend) when sys.platform is win32, so none of them raise
    RecorderUnsupportedError. Patches WasapiBackend's capture methods at the
    class level (rather than injecting a fake backend), so this also
    exercises the real get_backend() -> WasapiBackend platform resolution.
    WasapiBackend only imports pyaudiowpatch lazily inside its capture
    thread's run(), so this needs no Windows-only dependency."""
    from pathlib import Path
    from types import SimpleNamespace

    from ghostbrain.recorder.audio.wasapi import WasapiBackend
    from ghostbrain.recorder.audio_capture import CaptureHandle

    fake_handle = CaptureHandle(pid=4321, wav_path=Path("/tmp/fake.wav"))

    with patch("ghostbrain.recorder.audio.sys") as mock_sys, \
         patch.object(WasapiBackend, "start_capture", return_value=fake_handle), \
         patch.object(WasapiBackend, "stop_capture", return_value=True), \
         patch.object(WasapiBackend, "capture_alive", return_value=False), \
         patch("ghostbrain.api.repo.recorder._read_state", return_value=None), \
         patch("ghostbrain.api.repo.recorder._write_state"), \
         patch("ghostbrain.api.repo.recorder._daemon_active", return_value=None), \
         patch.object(recorder_repo.daemon_state, "load",
                       return_value=SimpleNamespace(active=None)), \
         patch("ghostbrain.api.repo.recorder.load_manual_config",
               return_value=SimpleNamespace(context="work", enabled=True)), \
         patch("ghostbrain.api.repo.recorder._current_calendar_event", return_value=None):
        mock_sys.platform = "win32"

        assert recorder_repo.status()["phase"] == "idle"

        started = recorder_repo.start(title="Standup", context=None)
        assert started["pid"] == 4321
        assert started["wavPath"] == str(fake_handle.wav_path)

        # No manual state and no daemon-owned recording -> normal business
        # logic (RecorderNotActive), never RecorderUnsupportedError.
        with pytest.raises(recorder_repo.RecorderNotActive):
            recorder_repo.stop()

        assert recorder_repo.clear()["phase"] == "idle"


def _manual_recording_state(*, pid: int) -> dict:
    return {
        "phase": "recording",
        "pid": pid,
        "wavPath": "/tmp/meeting.wav",
        "title": "Standup",
        "context": "work",
        "parentPath": None,
        "startedAt": "2026-08-25T08:00:00+00:00",
        "transcriptPath": None,
        "error": None,
    }


def test_status_consults_backend_capture_alive_for_manual_recording():
    """status() must consult backend.capture_alive for the pid recorded in
    manual.state when phase == "recording" — not just for daemon-owned
    recordings (already covered by
    ghostbrain/api/tests/test_recorder.py::test_stop_kills_daemon_owned_recording).
    Isolated via the same monkeypatched _read_state/_write_state pattern used
    elsewhere in this file — never touches ~/ghostbrain."""
    fake_backend = MagicMock()
    fake_backend.capture_alive.return_value = True

    with patch("ghostbrain.recorder.audio.get_backend", return_value=fake_backend), \
         patch("ghostbrain.api.repo.recorder._read_state",
               return_value=_manual_recording_state(pid=4242)), \
         patch("ghostbrain.api.repo.recorder._write_state") as mock_write, \
         patch("ghostbrain.api.repo.recorder._daemon_active", return_value=None):
        result = recorder_repo.status()

    fake_backend.capture_alive.assert_called_once_with(4242)
    assert result["phase"] == "recording"
    mock_write.assert_not_called()


def test_status_promotes_stale_manual_pid_to_transcribing():
    """Same setup, but capture_alive is False (the process died without going
    through /stop) — status() should promote phase to 'transcribing' and
    persist that via _write_state, matching the pre-existing stale-pid
    recovery behaviour (previously driven by audio_capture.is_running)."""
    fake_backend = MagicMock()
    fake_backend.capture_alive.return_value = False

    with patch("ghostbrain.recorder.audio.get_backend", return_value=fake_backend), \
         patch("ghostbrain.api.repo.recorder._read_state",
               return_value=_manual_recording_state(pid=4242)), \
         patch("ghostbrain.api.repo.recorder._write_state") as mock_write, \
         patch("ghostbrain.api.repo.recorder._daemon_active", return_value=None):
        result = recorder_repo.status()

    fake_backend.capture_alive.assert_called_once_with(4242)
    assert result["phase"] == "transcribing"
    mock_write.assert_called_once()
    written_state = mock_write.call_args[0][0]
    assert written_state["phase"] == "transcribing"
