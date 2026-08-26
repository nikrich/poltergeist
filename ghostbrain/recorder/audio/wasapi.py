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

_ACTIVE: dict[int, "_CaptureThread"] = {}


def _chunk_for(rate: int) -> int:
    """~10 ms worth of samples at `rate`. Each stream is opened/read with
    ITS OWN chunk size (not a single fixed one shared across streams) —
    loopback and mic commonly run at different rates (e.g. 48 kHz system
    output vs a 16 kHz BT-headset mic), and reading a fixed sample count
    from both means very different wall-clock time per read (10 ms vs
    30 ms), so the faster stream's buffer overruns while the slower read
    blocks."""
    return max(1, rate // 100)


class _CaptureThread(threading.Thread):
    def __init__(self, wav_path: Path) -> None:
        super().__init__(name="wasapi-capture", daemon=True)
        self.wav_path = wav_path
        # Named _stop_event, not _stop: threading.Thread already defines a
        # private _stop() method that join() relies on internally — an
        # attribute named `_stop` shadows it and breaks join().
        self._stop_event = threading.Event()
        # Set once streams are open (success) or startup failed (failure —
        # check start_error). start_capture() waits on this so a startup
        # failure (e.g. pa.PyAudio() or the loopback open() raising) is
        # reported synchronously to the caller instead of vanishing into
        # threading.excepthook while the daemon believes recording started.
        self._started_event = threading.Event()
        self.start_error: Exception | None = None

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        import pyaudiowpatch as pa

        audio = None
        writer = None
        loop_stream = mic_stream = None
        try:
            audio = pa.PyAudio()
            writer = IncrementalWavWriter(self.wav_path)
            loop_dev = audio.get_default_wasapi_loopback()
            loop_rate = int(loop_dev["defaultSampleRate"])
            loop_ch = int(loop_dev["maxInputChannels"])
            loop_chunk = _chunk_for(loop_rate)
            loop_stream = audio.open(
                format=pa.paInt16, channels=loop_ch, rate=loop_rate,
                input=True, input_device_index=loop_dev["index"],
                frames_per_buffer=loop_chunk,
            )
        except Exception as exc:  # noqa: BLE001 — startup failure, surface synchronously
            log.exception("wasapi capture failed to start")
            self.start_error = exc
            self._started_event.set()
            if loop_stream is not None:
                try:
                    loop_stream.stop_stream()
                    loop_stream.close()
                except Exception:  # noqa: BLE001
                    pass
            if writer is not None:
                writer.close()
            if audio is not None:
                audio.terminate()
            return

        # Streams are open — start_capture() can now return successfully.
        self._started_event.set()

        try:
            # Mic acquisition is best-effort: some machines (desktops,
            # conference rooms) have no default input device at all. Losing
            # the mic must not lose the loopback (system-audio) capture.
            mic_rate = mic_ch = mic_chunk = None
            try:
                mic_dev = audio.get_default_input_device_info()
                mic_rate = int(mic_dev["defaultSampleRate"])
                mic_ch = max(1, int(mic_dev["maxInputChannels"]))
                mic_chunk = _chunk_for(mic_rate)
                mic_stream = audio.open(
                    format=pa.paInt16, channels=mic_ch, rate=mic_rate,
                    input=True, input_device_index=mic_dev["index"],
                    frames_per_buffer=mic_chunk,
                )
            except Exception as exc:  # noqa: BLE001 — no default input device
                log.warning("no default input device; recording system audio only: %s", exc)
                mic_stream = None

            while not self._stop_event.is_set():
                loop_raw = loop_stream.read(loop_chunk, exception_on_overflow=False)
                loop_f = np.frombuffer(loop_raw, dtype=np.int16).astype(np.float32) / 32768.0
                loop_pcm = to_mono_16k(loop_f, loop_rate, loop_ch)
                if mic_stream is None:
                    mixed = loop_pcm
                else:
                    mic_raw = mic_stream.read(mic_chunk, exception_on_overflow=False)
                    mic_f = np.frombuffer(mic_raw, dtype=np.int16).astype(np.float32) / 32768.0
                    mixed = mix(loop_pcm, to_mono_16k(mic_f, mic_rate, mic_ch))
                writer.append(mixed)
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
        if not thread._started_event.wait(timeout=2.0):
            thread.stop()
            thread.join(timeout=2.0)
            raise RuntimeError(
                "wasapi capture did not start within 2s (device busy or "
                "unresponsive)"
            )
        if thread.start_error is not None:
            raise RuntimeError(f"wasapi capture failed to start: {thread.start_error}")
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
