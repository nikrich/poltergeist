"""Pure-logic tests for the WASAPI capture path: no audio hardware."""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from ghostbrain.recorder.audio.wasapi_io import IncrementalWavWriter, mix, to_mono_16k


def test_to_mono_16k_downmixes_and_resamples():
    # 48 kHz stereo sine, 0.1 s
    t = np.linspace(0, 0.1, 4800, endpoint=False)
    stereo = np.stack([np.sin(2 * np.pi * 440 * t)] * 2, axis=1).astype(np.float32)
    out = to_mono_16k(stereo.reshape(-1), src_rate=48000, src_channels=2)
    assert out.dtype == np.int16
    assert abs(len(out) - 1600) <= 2      # 0.1 s at 16 kHz


def test_mix_clips_instead_of_wrapping():
    a = np.full(100, 30000, dtype=np.int16)
    b = np.full(100, 30000, dtype=np.int16)
    out = mix(a, b)
    assert out.max() == 32767             # clipped, not wrapped negative


def test_mix_handles_unequal_lengths():
    out = mix(np.ones(50, dtype=np.int16), np.ones(80, dtype=np.int16))
    assert len(out) == 80


def test_wav_writer_playable_without_close(tmp_path: Path):
    """Header sizes must be valid after append() alone — crash contract."""
    p = tmp_path / "m.wav"
    w = IncrementalWavWriter(p)
    w.append(np.zeros(16000, dtype=np.int16))
    # Do NOT close. A fresh reader must see one second of audio.
    with wave.open(str(p), "rb") as r:
        assert r.getframerate() == 16000
        assert r.getnchannels() == 1
        assert r.getnframes() == 16000
    w.close()


def test_to_mono_16k_empty_input_returns_empty():
    """Empty buffers from WASAPI at stream start/stop must return empty, not crash."""
    out = to_mono_16k(np.zeros(0, dtype=np.float32), src_rate=48000, src_channels=2)
    assert out.dtype == np.int16
    assert len(out) == 0
