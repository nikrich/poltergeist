"""Recorder control schemas."""
from typing import Literal

from pydantic import BaseModel, Field

# Phase progression for a manual recording session:
#   idle → recording → transcribing → done → (UI clears, back to idle)
# A calendar-driven recording reports phase=recording, owner=daemon and
# bypasses the manual flow entirely.
RecorderPhase = Literal["idle", "recording", "transcribing", "done"]
RecorderOwner = Literal["manual", "daemon"]


class StartRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    context: str | None = Field(default=None, max_length=80)


class CaptureTargetRequest(BaseModel):
    """Answer to the native helper's "no meeting window found" prompt:
    capture the whole display, stay audio-only, or pin a specific window
    (one of ``RecorderStatus.captureWindows``)."""
    choice: Literal["display", "audio", "window"]
    window_id: int | None = Field(default=None, gt=0)


class CaptureWindow(BaseModel):
    """An on-screen window the user may pick as the slide source."""
    windowId: int
    app: str
    appName: str
    title: str
    width: int
    height: int
    # True when the helper would have auto-selected it as a meeting window.
    candidate: bool = False


class RecorderStatus(BaseModel):
    phase: RecorderPhase
    owner: RecorderOwner | None = None
    title: str | None = None
    startedAt: str | None = None
    wavPath: str | None = None
    transcriptPath: str | None = None  # vault-relative once transcribed
    error: str | None = None
    # Human-readable reasons a configured calendar isn't driving auto-record
    # (e.g. microsoft.calendar_context missing in routing.yaml). See
    # ghostbrain.recorder.sources.select_sources.
    sourceExclusions: list[str] = []
    # Which backend owns the live capture ("native", "blackhole", "wasapi").
    captureBackend: str | None = None
    # Native backend: the helper found no meeting-app window and is waiting
    # for the user to pick screen capture vs audio only
    # (POST /v1/recorder/capture/target).
    awaitingTargetChoice: bool = False
    # Pickable windows, populated while awaitingTargetChoice is true.
    captureWindows: list[CaptureWindow] = []


class CaptureHelperProbe(BaseModel):
    """Result of `ghostbrain-capture check --json` (macOS native backend)."""
    found: bool
    path: str | None = None
    ok: bool
    code: int | None = None
    reason: str
    macos_version: str
    macos_supported: bool
    screen_recording: str = "unknown"
    microphone: str = "unknown"
