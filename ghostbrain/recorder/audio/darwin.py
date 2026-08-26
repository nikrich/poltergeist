"""macOS backend: existing ffmpeg/avfoundation capture + SwitchAudioSource
routing, unchanged behavior, wrapped behind the AudioBackend protocol."""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ghostbrain.recorder import audio_capture, audio_switcher
from ghostbrain.recorder.audio.base import RouteHandle
from ghostbrain.recorder.audio_capture import CaptureHandle

log = logging.getLogger("ghostbrain.recorder.audio.darwin")


class DarwinBackend:
    def preflight(self) -> tuple[bool, list[str]]:
        missing: list[str] = []
        if shutil.which("ffmpeg") is None:
            missing.append("ffmpeg not on PATH (install via Homebrew: brew install ffmpeg)")
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
