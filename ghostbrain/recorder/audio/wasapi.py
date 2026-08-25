"""Windows backend: WASAPI loopback (system audio) + default mic via
pyaudiowpatch, mixed in-process to 16 kHz mono WAV.

No drivers, no admin, no device switching — loopback taps the default
output directly, so begin/end_meeting_route are no-ops and
`recorder.audio_device` is ignored on this platform."""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

import numpy as np

from ghostbrain.recorder.audio.base import RouteHandle
from ghostbrain.recorder.audio.wasapi_io import IncrementalWavWriter, mix, to_mono_16k
from ghostbrain.recorder.audio_capture import CaptureHandle

log = logging.getLogger("ghostbrain.recorder.audio.wasapi")

_CHUNK = 480  # 10 ms at 48 kHz
_ACTIVE: dict[int, "_CaptureThread"] = {}


class _CaptureThread(threading.Thread):
    def __init__(self, wav_path: Path) -> None:
        super().__init__(name="wasapi-capture", daemon=True)
        self.wav_path = wav_path
        # Named _stop_event, not _stop: threading.Thread already defines a
        # private _stop() method that join() relies on internally — an
        # attribute named `_stop` shadows it and breaks join().
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        import pyaudiowpatch as pa

        audio = pa.PyAudio()
        writer = IncrementalWavWriter(self.wav_path)
        loop_stream = mic_stream = None
        try:
            loop_dev = audio.get_default_wasapi_loopback()
            mic_dev = audio.get_default_input_device_info()
            loop_rate = int(loop_dev["defaultSampleRate"])
            loop_ch = int(loop_dev["maxInputChannels"])
            mic_rate = int(mic_dev["defaultSampleRate"])
            mic_ch = max(1, int(mic_dev["maxInputChannels"]))
            loop_stream = audio.open(
                format=pa.paInt16, channels=loop_ch, rate=loop_rate,
                input=True, input_device_index=loop_dev["index"],
                frames_per_buffer=_CHUNK,
            )
            mic_stream = audio.open(
                format=pa.paInt16, channels=mic_ch, rate=mic_rate,
                input=True, input_device_index=mic_dev["index"],
                frames_per_buffer=_CHUNK,
            )
            while not self._stop_event.is_set():
                loop_raw = loop_stream.read(_CHUNK, exception_on_overflow=False)
                mic_raw = mic_stream.read(_CHUNK, exception_on_overflow=False)
                loop_f = np.frombuffer(loop_raw, dtype=np.int16).astype(np.float32) / 32768.0
                mic_f = np.frombuffer(mic_raw, dtype=np.int16).astype(np.float32) / 32768.0
                writer.append(mix(
                    to_mono_16k(loop_f, loop_rate, loop_ch),
                    to_mono_16k(mic_f, mic_rate, mic_ch),
                ))
        except Exception:  # noqa: BLE001 — device unplug/change ends the stream
            log.exception("wasapi capture ended with error; WAV kept for recovery")
        finally:
            for s in (loop_stream, mic_stream):
                try:
                    if s is not None:
                        s.stop_stream()
                        s.close()
                except Exception:  # noqa: BLE001
                    pass
            audio.terminate()
            writer.close()


class WasapiBackend:
    def preflight(self) -> tuple[bool, list[str]]:
        missing: list[str] = []
        try:
            import pyaudiowpatch  # noqa: F401
        except ImportError:
            missing.append(
                "pyaudiowpatch not installed — pip install 'ghostbrain[recorder-win]' "
                "(on corporate networks, download wheels via browser/approved channel)"
            )
        return (not missing, missing)

    def begin_meeting_route(self, device: str, fallback: str) -> RouteHandle:
        # WASAPI loopback taps the default output directly — nothing to switch.
        return RouteHandle(previous_output="", switched=False)

    def end_meeting_route(self, handle: RouteHandle) -> None:
        pass

    def start_capture(self, wav_path: Path, *, log_path: Path | None = None) -> CaptureHandle:
        thread = _CaptureThread(wav_path)
        thread.start()
        _ACTIVE[os.getpid()] = thread
        log.info("wasapi capture started → %s", wav_path.name)
        return CaptureHandle(pid=os.getpid(), wav_path=wav_path)

    def stop_capture(self, pid: int) -> bool:
        thread = _ACTIVE.pop(pid, None)
        if thread is None:
            return True
        thread.stop()
        thread.join(timeout=5.0)
        return not thread.is_alive()

    def capture_alive(self, pid: int) -> bool:
        if pid != os.getpid():
            return False  # stale pid from a previous process → daemon finalizes
        thread = _ACTIVE.get(pid)
        return thread is not None and thread.is_alive()
