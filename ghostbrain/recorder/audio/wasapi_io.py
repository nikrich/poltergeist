"""Pure DSP + file plumbing for the WASAPI backend. No pyaudiowpatch here —
this module is imported by tests on every OS."""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

TARGET_RATE = 16000


def to_mono_16k(frames: np.ndarray, src_rate: int, src_channels: int) -> np.ndarray:
    """float32 interleaved [-1,1] → int16 mono 16 kHz."""
    if len(frames) == 0:
        return np.array([], dtype=np.int16)
    if src_channels > 1:
        frames = frames.reshape(-1, src_channels).mean(axis=1)
    if src_rate != TARGET_RATE:
        n_out = int(round(len(frames) * TARGET_RATE / src_rate))
        x_out = np.linspace(0, len(frames) - 1, n_out)
        frames = np.interp(x_out, np.arange(len(frames)), frames)
    return np.clip(frames * 32767.0, -32768, 32767).astype(np.int16)


def mix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Clip-protected sum; shorter input is zero-padded (amix semantics)."""
    n = max(len(a), len(b))
    out = np.zeros(n, dtype=np.int32)
    out[: len(a)] += a.astype(np.int32)
    out[: len(b)] += b.astype(np.int32)
    return np.clip(out, -32768, 32767).astype(np.int16)


class IncrementalWavWriter:
    """16 kHz mono PCM16 WAV whose header is fixed up on every append, so an
    abrupt process death (sidecar crash, OS kill) leaves a playable file for
    the recovery pass."""

    _HEADER_LEN = 44

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._f = open(path, "wb")
        self._data_bytes = 0
        self._write_header()

    def _write_header(self) -> None:
        f = self._f
        f.seek(0)
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + self._data_bytes))
        f.write(b"WAVEfmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, 1, TARGET_RATE,
                            TARGET_RATE * 2, 2, 16))
        f.write(b"data")
        f.write(struct.pack("<I", self._data_bytes))

    def append(self, pcm: np.ndarray) -> None:
        raw = pcm.astype("<i2").tobytes()
        self._f.seek(self._HEADER_LEN + self._data_bytes)
        self._f.write(raw)
        self._data_bytes += len(raw)
        self._write_header()
        self._f.flush()

    def close(self) -> None:
        try:
            self._write_header()
            self._f.flush()
        finally:
            self._f.close()
