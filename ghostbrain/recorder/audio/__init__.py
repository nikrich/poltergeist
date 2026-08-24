"""Factory: pick the AudioBackend for this platform."""
from __future__ import annotations

import sys

from ghostbrain.recorder.audio.base import AudioBackend, RouteHandle, UnsupportedBackend

__all__ = ["AudioBackend", "RouteHandle", "UnsupportedBackend", "get_backend"]


def get_backend(platform: str | None = None) -> AudioBackend:
    plat = platform or sys.platform
    if plat == "darwin":
        from ghostbrain.recorder.audio.darwin import DarwinBackend
        return DarwinBackend()
    if plat == "win32":
        from ghostbrain.recorder.audio.wasapi import WasapiBackend
        return WasapiBackend()
    return UnsupportedBackend()
