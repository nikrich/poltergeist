"""AudioBackend factory + darwin delegation. WASAPI thread tests live here too (Task 4)."""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

from ghostbrain.recorder.audio import get_backend
from ghostbrain.recorder.audio.base import RouteHandle, UnsupportedBackend
from ghostbrain.recorder.audio.darwin import DarwinBackend


def test_factory_darwin():
    assert isinstance(get_backend("darwin"), DarwinBackend)


def test_factory_linux_unsupported():
    backend = get_backend("linux")
    assert isinstance(backend, UnsupportedBackend)
    ok, missing = backend.preflight()
    assert ok is False
    assert any("not supported" in m for m in missing)


def test_darwin_begin_route_switches_and_remembers_previous():
    with patch("ghostbrain.recorder.audio.darwin.audio_switcher") as sw:
        sw.current_output.return_value = "MacBook Pro Speakers"
        handle = DarwinBackend().begin_meeting_route("Ghost Brain", "")
    sw.switch_to.assert_called_once_with("Ghost Brain")
    assert handle == RouteHandle(previous_output="MacBook Pro Speakers", switched=True)


def test_darwin_begin_route_noop_when_already_on_device():
    with patch("ghostbrain.recorder.audio.darwin.audio_switcher") as sw:
        sw.current_output.return_value = "Ghost Brain"
        handle = DarwinBackend().begin_meeting_route("Ghost Brain", "")
    sw.switch_to.assert_not_called()
    assert handle.switched is False


def test_darwin_end_route_restores():
    with patch("ghostbrain.recorder.audio.darwin.audio_switcher") as sw:
        DarwinBackend().end_meeting_route(
            RouteHandle(previous_output="MacBook Pro Speakers", switched=True)
        )
    sw.switch_to.assert_called_once_with("MacBook Pro Speakers")


def test_darwin_end_route_noop_when_not_switched():
    with patch("ghostbrain.recorder.audio.darwin.audio_switcher") as sw:
        DarwinBackend().end_meeting_route(RouteHandle(previous_output="", switched=False))
    sw.switch_to.assert_not_called()


def test_darwin_capture_delegates(tmp_path: Path):
    with patch("ghostbrain.recorder.audio.darwin.audio_capture") as cap:
        DarwinBackend().start_capture(tmp_path / "x.wav")
        cap.start_capture.assert_called_once_with(tmp_path / "x.wav", log_path=None)


def _fake_pyaudiowpatch(monkeypatch, frames_per_read=480):
    """Install a minimal fake pyaudiowpatch into sys.modules."""
    fake = types.ModuleType("pyaudiowpatch")
    fake.paInt16 = 8

    class _Stream:
        def __init__(self):
            self.closed = False
        def read(self, n, exception_on_overflow=False):
            import numpy as np
            return np.zeros(n, dtype=np.float32).tobytes()
        def stop_stream(self): pass
        def close(self): self.closed = True

    class _PyAudio:
        def get_default_wasapi_loopback(self):
            return {"index": 7, "defaultSampleRate": 48000.0, "maxInputChannels": 2}
        def get_default_input_device_info(self):
            return {"index": 1, "defaultSampleRate": 44100.0, "maxInputChannels": 1}
        def open(self, **kwargs):
            return _Stream()
        def terminate(self): pass

    fake.PyAudio = _PyAudio
    monkeypatch.setitem(sys.modules, "pyaudiowpatch", fake)
    return fake


def test_wasapi_route_is_noop(monkeypatch):
    _fake_pyaudiowpatch(monkeypatch)
    from ghostbrain.recorder.audio.wasapi import WasapiBackend
    handle = WasapiBackend().begin_meeting_route("Ghost Brain", "")
    assert handle.switched is False


def test_wasapi_capture_thread_lifecycle(monkeypatch, tmp_path):
    _fake_pyaudiowpatch(monkeypatch)
    from ghostbrain.recorder.audio.wasapi import WasapiBackend
    backend = WasapiBackend()
    handle = backend.start_capture(tmp_path / "m.wav")
    assert handle.pid == os.getpid()
    assert backend.capture_alive(handle.pid) is True
    assert backend.stop_capture(handle.pid) is True
    assert backend.capture_alive(handle.pid) is False
    assert (tmp_path / "m.wav").exists()


def test_wasapi_preflight_reports_missing_dep(monkeypatch):
    monkeypatch.setitem(sys.modules, "pyaudiowpatch", None)
    import ghostbrain.recorder.audio.wasapi as w
    ok, missing = w.WasapiBackend().preflight()
    assert ok is False
    assert any("pyaudiowpatch" in m for m in missing)
