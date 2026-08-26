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


def test_wav_writer_header_refreshes_within_rewrite_window_without_close(tmp_path: Path):
    """M4: the header is rewritten every `_HEADER_REWRITE_EVERY` appends
    (not every single append, to avoid a seek+write+flush per ~10ms WASAPI
    chunk) — but the crash contract still holds: without close(), a fresh
    reader sees all audio written up to the last rewrite window boundary."""
    p = tmp_path / "m.wav"
    w = IncrementalWavWriter(p)
    n = IncrementalWavWriter._HEADER_REWRITE_EVERY
    for _ in range(n):
        w.append(np.zeros(160, dtype=np.int16))
    # Do NOT close. Exactly `n` appends means the header-rewrite threshold
    # was just crossed, so a fresh reader must see all of it.
    with wave.open(str(p), "rb") as r:
        assert r.getframerate() == 16000
        assert r.getnchannels() == 1
        assert r.getnframes() == 160 * n
    w.close()


def test_wav_writer_header_lags_data_below_rewrite_threshold(tmp_path: Path):
    """M4 characterization: below `_HEADER_REWRITE_EVERY` appends, the
    header is intentionally left stale (declaring less data than is
    actually on disk) — that's the batching itself. Data durability is
    covered separately below."""
    p = tmp_path / "m.wav"
    w = IncrementalWavWriter(p)
    w.append(np.zeros(160, dtype=np.int16))
    with wave.open(str(p), "rb") as r:
        assert r.getnframes() == 0  # header not yet refreshed
    w.close()


def test_wav_writer_flushes_data_every_append_even_before_header_refresh(
    tmp_path: Path,
):
    """M4: audio *data* must hit disk on every single append regardless of
    header-rewrite batching — only the header (which just declares sizes)
    is allowed to lag. Read the raw bytes directly (past the fixed 44-byte
    header) rather than through `wave`, since `wave` trusts the header's
    declared data size, not the actual file length."""
    p = tmp_path / "m.wav"
    w = IncrementalWavWriter(p)
    w.append(np.zeros(160, dtype=np.int16))
    raw = p.read_bytes()
    assert len(raw) == IncrementalWavWriter._HEADER_LEN + 160 * 2
    w.close()


def test_wav_writer_multiple_appends_accumulate_correctly(tmp_path: Path):
    """M3: several appends must accumulate into one contiguous WAV with the
    correct total length and a valid, closed-out header."""
    p = tmp_path / "m.wav"
    w = IncrementalWavWriter(p)
    w.append(np.full(4000, 100, dtype=np.int16))
    w.append(np.full(4000, 200, dtype=np.int16))
    w.append(np.full(4000, 300, dtype=np.int16))
    w.close()

    with wave.open(str(p), "rb") as r:
        assert r.getnframes() == 12000
        assert r.getnchannels() == 1
        assert r.getframerate() == 16000
        assert r.getsampwidth() == 2
        pcm = np.frombuffer(r.readframes(12000), dtype=np.int16)
        assert list(pcm[:2]) == [100, 100]
        assert list(pcm[4000:4002]) == [200, 200]
        assert list(pcm[8000:8002]) == [300, 300]


def test_to_mono_16k_empty_input_returns_empty():
    """Empty buffers from WASAPI at stream start/stop must return empty, not crash."""
    out = to_mono_16k(np.zeros(0, dtype=np.float32), src_rate=48000, src_channels=2)
    assert out.dtype == np.int16
    assert len(out) == 0


def test_to_mono_16k_truncates_misaligned_read_instead_of_raising():
    """M2: a read that isn't an exact multiple of the channel count (a torn
    read from a real device) used to raise ValueError from reshape(-1,
    channels). Drop the trailing partial frame instead of crashing the
    capture thread."""
    # 5 samples, 2 channels -> not divisible by 2 (one channel's worth of a
    # partial frame at the end).
    frames = np.array([0.1, 0.2, 0.3, 0.4, 0.5], dtype=np.float32)
    out = to_mono_16k(frames, src_rate=16000, src_channels=2)
    assert out.dtype == np.int16
    assert len(out) == 2  # last (misaligned) sample dropped, 2 usable frames


def test_to_mono_16k_misaligned_read_shorter_than_one_frame_returns_empty():
    """A read shorter than a single frame (channels=2, 1 sample) has zero
    usable frames — must return empty, not raise."""
    out = to_mono_16k(np.array([0.1], dtype=np.float32), src_rate=16000, src_channels=2)
    assert out.dtype == np.int16
    assert len(out) == 0
