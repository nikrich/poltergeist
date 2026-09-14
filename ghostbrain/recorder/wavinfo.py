"""WAV duration without ffprobe.

Every recorder backend writes canonical 16 kHz mono PCM16 WAV, so the stdlib
``wave`` module is enough. A recording that was killed mid-write (SIGKILL,
power loss) can have a stale or zeroed header; fall back to the file size in
that case so callers still get a sensible duration.
"""
from __future__ import annotations

import logging
import wave
from pathlib import Path

log = logging.getLogger("ghostbrain.recorder.wavinfo")

_HEADER_BYTES = 44
_BYTES_PER_SECOND = 16000 * 1 * 2  # rate * channels * sample width


def wav_duration_seconds(path: Path) -> float:
    """Duration of ``path`` in seconds; ``0.0`` when the file is missing."""
    try:
        size = path.stat().st_size
    except OSError:
        return 0.0
    try:
        with wave.open(str(path), "rb") as f:
            frames = f.getnframes()
            rate = f.getframerate() or 16000
            if frames > 0:
                return frames / float(rate)
    except (wave.Error, EOFError, OSError) as e:
        log.warning("wav header unreadable for %s (%s); estimating from size", path.name, e)
    if size <= _HEADER_BYTES:
        return 0.0
    return (size - _HEADER_BYTES) / float(_BYTES_PER_SECOND)
