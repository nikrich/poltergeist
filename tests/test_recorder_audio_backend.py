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


def _fake_pyaudiowpatch(
    monkeypatch, *, loop_rate=48000.0, mic_rate=44100.0, mic=True, on_read=None,
):
    """Install a minimal fake pyaudiowpatch into sys.modules.

    mic=False simulates a machine with no default input device: calling
    get_default_input_device_info() raises OSError, as pyaudiowpatch does
    when there's no default input (common on desktops/conference rooms).

    loop_rate/mic_rate let tests simulate mismatched device sample rates
    (e.g. 48 kHz system output vs a 16 kHz BT-headset mic). `fake.opened`
    records every `open()` call's kwargs so tests can assert on the
    frames_per_buffer each stream was opened with. `on_read(tag, n)`, if
    given, fires on every `.read(n)` call, tagged "loop" or "mic".
    """
    fake = types.ModuleType("pyaudiowpatch")
    fake.paInt16 = 8
    fake.opened = []

    class _Stream:
        def __init__(self, tag, channels):
            self.closed = False
            self._tag = tag
            self._channels = channels
        def read(self, n, exception_on_overflow=False):
            import numpy as np
            if on_read is not None:
                on_read(self._tag, n)
            # Real pyaudiowpatch: read(num_frames) with format=paInt16 returns
            # num_frames * channels int16 samples, interleaved.
            return np.zeros(n * self._channels, dtype=np.int16).tobytes()
        def stop_stream(self): pass
        def close(self): self.closed = True

    class _PyAudio:
        def get_default_wasapi_loopback(self):
            return {"index": 7, "defaultSampleRate": loop_rate, "maxInputChannels": 2}
        def get_default_input_device_info(self):
            if not mic:
                raise OSError("no default input")
            return {"index": 1, "defaultSampleRate": mic_rate, "maxInputChannels": 1}
        def open(self, **kwargs):
            fake.opened.append(kwargs)
            tag = "loop" if kwargs.get("input_device_index") == 7 else "mic"
            return _Stream(tag, kwargs.get("channels", 1))
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


def test_wasapi_capture_opens_each_stream_with_its_own_10ms_chunk(monkeypatch, tmp_path):
    """C2: a fixed 480-sample read from BOTH streams breaks when loopback and
    mic run at different rates (e.g. 48 kHz system output vs a 16 kHz
    BT-headset mic) — 10ms of loopback vs 30ms of mic per read, so the
    loopback stream overruns while the (much slower) mic read blocks. Each
    stream must be opened with its OWN 10ms chunk (rate // 100)."""
    fake = _fake_pyaudiowpatch(monkeypatch, loop_rate=48000.0, mic_rate=16000.0)
    from ghostbrain.recorder.audio.wasapi import WasapiBackend
    backend = WasapiBackend()
    handle = backend.start_capture(tmp_path / "m.wav")
    assert backend.stop_capture(handle.pid) is True

    loop_chunk = next(k["frames_per_buffer"] for k in fake.opened
                       if k.get("input_device_index") == 7)
    mic_chunk = next(k["frames_per_buffer"] for k in fake.opened
                      if k.get("input_device_index") == 1)
    assert loop_chunk == 480   # 48000 // 100 (10ms)
    assert mic_chunk == 160    # 16000 // 100 (10ms)


def test_wasapi_capture_writes_equal_length_16k_chunks_for_mismatched_rates(
    monkeypatch, tmp_path,
):
    """With per-stream 10ms chunk sizes, a 48 kHz loopback + 16 kHz mic pair
    both resample to ~160 samples per iteration at 16 kHz, so the WAV grows
    by exactly 160 frames per completed iteration — counted here via the
    mic stream's own read count (each iteration reads loop then mic exactly
    once), joined so writes and counts can't race."""
    import wave

    counts = {"loop": 0, "mic": 0}

    def on_read(tag, n):
        counts[tag] += 1

    _fake_pyaudiowpatch(
        monkeypatch, loop_rate=48000.0, mic_rate=16000.0, on_read=on_read,
    )
    from ghostbrain.recorder.audio.wasapi import WasapiBackend
    backend = WasapiBackend()
    wav_path = tmp_path / "m.wav"
    handle = backend.start_capture(wav_path)
    import time
    time.sleep(0.05)
    assert backend.stop_capture(handle.pid) is True  # joins the capture thread

    iterations = counts["mic"]
    assert iterations > 0
    with wave.open(str(wav_path), "rb") as f:
        assert f.getframerate() == 16000
        # Tolerance covers the (very unlikely, given the join above) edge
        # case of one extra in-flight iteration.
        assert abs(f.getnframes() - iterations * 160) <= 160


def test_wasapi_start_capture_surfaces_startup_failure_synchronously(monkeypatch, tmp_path):
    """I3: PyAudio()/loopback-open failures used to happen entirely inside
    the capture thread, outside its try block — the exception went to
    threading.excepthook, no WAV was ever created, and start_capture()
    returned normally, so the daemon believed recording had started. A
    startup failure must now raise synchronously from start_capture(), and
    must leave no _ACTIVE entry or lingering thread behind."""
    import threading
    import time

    fake = types.ModuleType("pyaudiowpatch")
    fake.paInt16 = 8

    class _BoomPyAudio:
        def __init__(self):
            raise RuntimeError("no audio device")

    fake.PyAudio = _BoomPyAudio
    monkeypatch.setitem(sys.modules, "pyaudiowpatch", fake)

    from ghostbrain.recorder.audio.wasapi import _ACTIVE, WasapiBackend
    backend = WasapiBackend()

    with pytest.raises(RuntimeError, match="no audio device"):
        backend.start_capture(tmp_path / "m.wav")

    assert os.getpid() not in _ACTIVE

    for _ in range(50):
        if not any(t.name == "wasapi-capture" and t.is_alive()
                   for t in threading.enumerate()):
            break
        time.sleep(0.01)
    else:
        pytest.fail("wasapi-capture thread still alive after startup failure")


def test_wasapi_preflight_reports_missing_dep(monkeypatch):
    monkeypatch.setitem(sys.modules, "pyaudiowpatch", None)
    import ghostbrain.recorder.audio.wasapi as w
    ok, missing = w.WasapiBackend().preflight()
    assert ok is False
    assert any("pyaudiowpatch" in m for m in missing)


def test_wasapi_capture_continues_without_mic(monkeypatch, tmp_path):
    import time
    import wave

    _fake_pyaudiowpatch(monkeypatch, mic=False)
    from ghostbrain.recorder.audio.wasapi import WasapiBackend
    backend = WasapiBackend()
    wav_path = tmp_path / "m.wav"
    handle = backend.start_capture(wav_path)
    time.sleep(0.1)  # let the capture loop write a few loopback-only chunks
    assert backend.stop_capture(handle.pid) is True

    with wave.open(str(wav_path), "rb") as f:
        assert f.getnframes() > 0
