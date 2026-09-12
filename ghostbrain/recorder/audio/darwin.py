"""macOS legacy backend ("blackhole"): ffmpeg/avfoundation capture of a
BlackHole virtual device + mic, with SwitchAudioSource routing. Kept for
macOS < 15 and for users who prefer it; the default on macOS 15+ is the
native ScreenCaptureKit helper in ``darwin_native.py``."""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ghostbrain.recorder import audio_capture, audio_switcher
from ghostbrain.recorder.audio.base import RouteHandle
from ghostbrain.recorder.audio_capture import CaptureHandle

log = logging.getLogger("ghostbrain.recorder.audio.darwin")


class DarwinBackend:
    name = "blackhole"

    def __init__(self, *, native_fallback_reason: str = "") -> None:
        # Set when ``capture_backend: auto`` landed here because the native
        # helper is unavailable — surfaced in preflight so users learn *why*
        # they are being asked for ffmpeg/BlackHole.
        self.native_fallback_reason = native_fallback_reason

    def preflight(self) -> tuple[bool, list[str]]:
        missing: list[str] = []
        if shutil.which("ffmpeg") is None:
            msg = "ffmpeg not on PATH (install via Homebrew: brew install ffmpeg)"
            if self.native_fallback_reason:
                msg += f"; native capture unavailable: {self.native_fallback_reason}"
            missing.append(msg)
        # BlackHole detection is slow + flaky; the route guard surfaces it at
        # start_capture instead of probing here (same trade-off as before).
        return (not missing, missing)

    def begin_meeting_route(self, device: str, fallback: str) -> RouteHandle:
        try:
            previous = audio_switcher.current_output()
        except audio_switcher.AudioSwitcherError as e:
            log.warning("could not read current audio output: %s", e)
            previous = fallback
        if previous and previous != device:
            try:
                audio_switcher.switch_to(device)
                return RouteHandle(previous_output=previous, switched=True)
            except audio_switcher.AudioSwitcherError as e:
                log.warning("audio switch failed (%s); continuing — recording may "
                            "still capture if %s is current output", e, device)
                return RouteHandle(previous_output=previous, switched=False)
        log.info("system output already %s; not switching", device)
        return RouteHandle(previous_output=previous, switched=False)

    def end_meeting_route(self, handle: RouteHandle) -> None:
        if not handle.switched or not handle.previous_output:
            return
        try:
            audio_switcher.switch_to(handle.previous_output)
        except audio_switcher.AudioSwitcherError as e:
            log.warning("could not restore audio output to %s: %s",
                        handle.previous_output, e)

    def start_capture(self, wav_path: Path, *, log_path: Path | None = None) -> CaptureHandle:
        return audio_capture.start_capture(wav_path, log_path=log_path)

    def stop_capture(self, pid: int) -> bool:
        return audio_capture.stop_capture(pid)

    def capture_alive(self, pid: int) -> bool:
        return audio_capture.is_running(pid)
