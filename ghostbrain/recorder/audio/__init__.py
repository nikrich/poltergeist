"""Factory: pick the AudioBackend for this platform (and, on macOS, the
configured capture method)."""
from __future__ import annotations

import sys
from typing import Any

from ghostbrain.recorder.audio.base import (
    AudioBackend,
    CaptureUnavailableError,
    RouteHandle,
    UnsupportedBackend,
)

__all__ = [
    "AudioBackend",
    "CaptureUnavailableError",
    "RouteHandle",
    "UnsupportedBackend",
    "get_backend",
    "resolve_capture_backend",
]


def resolve_capture_backend(recorder_cfg: dict[str, Any] | None = None) -> str:
    """``"native"`` or ``"blackhole"`` for macOS. Explicit config wins; ``auto``
    picks native only when the helper is present and its ``check`` passes."""
    from ghostbrain.recorder.config import capture_backend_from, load_recorder_block

    cfg = recorder_cfg if recorder_cfg is not None else load_recorder_block()
    mode = capture_backend_from(cfg)
    if mode in ("native", "blackhole"):
        return mode
    from ghostbrain.recorder.audio import darwin_native
    return "native" if darwin_native.probe().ok else "blackhole"


def get_backend(
    platform: str | None = None,
    *,
    recorder_cfg: dict[str, Any] | None = None,
) -> AudioBackend:
    plat = platform or sys.platform
    if plat == "darwin":
        from ghostbrain.recorder import config as rcfg
        from ghostbrain.recorder.audio import darwin_native

        cfg = recorder_cfg if recorder_cfg is not None else rcfg.load_recorder_block()
        if resolve_capture_backend(cfg) == "native":
            return darwin_native.NativeBackend(
                capture_slides=rcfg.capture_slides_from(cfg),
                slide_fps=rcfg.slide_fps_from(cfg),
                slide_fallback=rcfg.slide_fallback_from(cfg),
            )
        from ghostbrain.recorder.audio.darwin import DarwinBackend
        reason = ""
        if rcfg.capture_backend_from(cfg) == "auto":
            reason = darwin_native.probe().reason
        return DarwinBackend(native_fallback_reason=reason)
    if plat == "win32":
        from ghostbrain.recorder.audio.wasapi import WasapiBackend
        return WasapiBackend()
    return UnsupportedBackend()
