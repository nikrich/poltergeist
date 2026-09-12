"""AudioBackend seam: per-platform capture + routing, one protocol.

The daemon is platform-agnostic; each backend owns how system audio is
reached (ScreenCaptureKit helper or BlackHole route on macOS, WASAPI
loopback on Windows) and how capture runs (subprocess vs in-process
thread)."""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Protocol

from ghostbrain.recorder.audio_capture import CaptureHandle


@dataclasses.dataclass
class RouteHandle:
    """What begin_meeting_route changed, so end_meeting_route can undo it."""
    previous_output: str
    switched: bool


class CaptureUnavailableError(RuntimeError):
    """A capture precondition is unmet (permission not granted, macOS too
    old, helper missing). Not a crash: the API maps it to HTTP 412 so the
    desktop can show a fixable hint instead of a generic error toast."""


class AudioBackend(Protocol):
    name: str

    def preflight(self) -> tuple[bool, list[str]]: ...
    def begin_meeting_route(self, device: str, fallback: str) -> RouteHandle: ...
    def end_meeting_route(self, handle: RouteHandle) -> None: ...
    def start_capture(self, wav_path: Path, *, log_path: Path | None = None) -> CaptureHandle: ...
    def stop_capture(self, pid: int) -> bool: ...
    def capture_alive(self, pid: int) -> bool: ...


class UnsupportedBackend:
    """Placeholder for platforms with no audio backend (Linux today)."""

    name = "unsupported"
    platform_message = (
        "recorder is not supported on this OS yet (audio backend missing); "
        "see docs/install/ for per-OS status"
    )

    def preflight(self) -> tuple[bool, list[str]]:
        return False, [self.platform_message]

    def begin_meeting_route(self, device: str, fallback: str) -> RouteHandle:
        raise RuntimeError(self.platform_message)

    def end_meeting_route(self, handle: RouteHandle) -> None:  # pragma: no cover
        pass

    def start_capture(self, wav_path: Path, *, log_path: Path | None = None) -> CaptureHandle:
        raise RuntimeError(self.platform_message)

    def stop_capture(self, pid: int) -> bool:  # pragma: no cover
        return True

    def capture_alive(self, pid: int) -> bool:  # pragma: no cover
        return False
