"""wav_duration_seconds replaces ffprobe."""
from __future__ import annotations

import struct
import wave
from pathlib import Path

from ghostbrain.recorder.wavinfo import wav_duration_seconds


def test_duration_from_header(tmp_path: Path):
    p = tmp_path / "a.wav"
    with wave.open(str(p), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(16000)
        f.writeframes(b"\x00" * 2 * 16000 * 3)  # 3 s
    assert wav_duration_seconds(p) == 3.0


def test_duration_falls_back_to_size_on_zero_header(tmp_path: Path):
    p = tmp_path / "crashed.wav"
    header = (b"RIFF" + struct.pack("<I", 0) + b"WAVEfmt "
              + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16)
              + b"data" + struct.pack("<I", 0))
    p.write_bytes(header + b"\x00" * 32000 * 2)  # 2 s of samples, stale sizes
    assert abs(wav_duration_seconds(p) - 2.0) < 1e-6


def test_duration_missing_or_tiny(tmp_path: Path):
    assert wav_duration_seconds(tmp_path / "nope.wav") == 0.0
    p = tmp_path / "tiny.wav"
    p.write_bytes(b"RIFF")
    assert wav_duration_seconds(p) == 0.0
