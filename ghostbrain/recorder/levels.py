"""Audio levels for the recording waveform, read from the growing WAV.

The recording WAV already holds the mixed mic + system audio and grows
within milliseconds of the sound on every capture backend, so the waveform
follows the file rather than opening the microphone a second time.
"""
from __future__ import annotations

import math
import time
from collections.abc import Iterator
from pathlib import Path

from ghostbrain.recorder import chunker

_BLOCK = chunker.SAMPLE_RATE // 10  # 100 ms per level
_BLOCK_BYTES = _BLOCK * chunker.BYTES_PER_SAMPLE
_FLOOR_DB = -60.0


def to_level(rms: float) -> float:
    """RMS of PCM16 → 0..1 on a dB scale (-60 dBFS and below is flat)."""
    if rms <= 0:
        return 0.0
    db = 20 * math.log10(min(rms, 32768.0) / 32768.0)
    return round(max(0.0, min(1.0, (db - _FLOOR_DB) / -_FLOOR_DB)), 3)


def _data_bytes(wav: Path) -> int:
    try:
        return max(0, wav.stat().st_size - chunker.WAV_HEADER_BYTES)
    except OSError:
        return 0


def follow_levels(
    wav: Path,
    *,
    prefill_blocks: int = 48,
    interval_s: float = 0.1,
    idle_timeout_s: float = 5.0,
    keepalive_s: float = 15.0,
) -> Iterator[list[float] | None]:
    """Yield a list of new 100 ms levels as the WAV grows, starting with the
    last ``prefill_blocks`` so the waveform is full straight away. Capture
    writes samples even in silence, so a file that stops growing for
    ``idle_timeout_s`` means the recording ended. Yields None as a keepalive."""
    end = _data_bytes(wav)
    pos = max(0, end - end % _BLOCK_BYTES - prefill_blocks * _BLOCK_BYTES)
    last_growth = last_yield = time.monotonic()
    while True:
        end = _data_bytes(wav)
        whole = (end - pos) // _BLOCK_BYTES
        now = time.monotonic()
        if whole > 0:
            pcm = chunker.read_pcm(
                wav, start_sample=pos // chunker.BYTES_PER_SAMPLE, max_samples=whole * _BLOCK,
            )
            out = [to_level(rms) for rms in chunker.block_rms(pcm)]
            pos += len(out) * _BLOCK_BYTES
            last_growth = last_yield = now
            if out:
                yield out
        elif now - last_growth >= idle_timeout_s:
            return
        elif now - last_yield >= keepalive_s:
            last_yield = now
            yield None
        time.sleep(interval_s)
