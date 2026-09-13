"""Vault-level user settings exposed to the desktop app."""
from typing import Literal

from pydantic import BaseModel, Field

CaptureBackend = Literal["auto", "native", "blackhole"]
EffectiveCaptureBackend = Literal["native", "blackhole", "wasapi", "unsupported"]
SlideFallback = Literal["ask", "display", "audio"]


class RecorderSettings(BaseModel):
    """Subset of `recorder:` in <vault>/90-meta/config.yaml that the
    meetings UI surfaces. Other recorder knobs (poll interval, legacy audio
    device name) stay file-only for now."""

    enabled: bool = True
    excluded_titles: list[str] = Field(default_factory=lambda: ["Focus", "focus"])
    manual_context: str = "personal"
    # macOS capture method. `auto` = native ScreenCaptureKit helper when it is
    # present and permitted, else the legacy BlackHole/ffmpeg path.
    capture_backend: CaptureBackend = "auto"
    # Native only: save deduplicated slide key-frames + OCR text into the note.
    capture_slides: bool = True
    slide_fps: int = Field(default=1, ge=1, le=5)
    # Native only: what to do when no meeting-app window is on screen.
    slide_fallback: SlideFallback = "ask"
    # Read-only: what `capture_backend` resolves to on this machine right now.
    capture_backend_effective: EffectiveCaptureBackend = "unsupported"


class UpdateRecorderSettings(BaseModel):
    """Partial update — any omitted field is left untouched in the file."""

    enabled: bool | None = None
    excluded_titles: list[str] | None = None
    manual_context: str | None = None
    capture_backend: CaptureBackend | None = None
    capture_slides: bool | None = None
    slide_fps: int | None = Field(default=None, ge=1, le=5)
    slide_fallback: SlideFallback | None = None
