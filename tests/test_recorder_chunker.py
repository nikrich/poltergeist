"""Pause-aligned chunking of a growing 16 kHz mono PCM16 WAV."""
from __future__ import annotations

import itertools
import math
import struct
import wave
from pathlib import Path

from ghostbrain.recorder import chunker

SR = chunker.SAMPLE_RATE


def _tone(seconds: float, amp: int = 8000) -> bytes:
    n = int(seconds * SR)
    return b"".join(
        struct.pack("<h", int(amp * math.sin(2 * math.pi * 440 * i / SR))) for i in range(n)
    )


def _silence(seconds: float) -> bytes:
    return b"\x00\x00" * int(seconds * SR)


def _write_growing_wav(path: Path, pcm: bytes) -> None:
    """Header claims zero data bytes — like ffmpeg before SIGINT finalises it."""
    header = bytearray(44)
    header[0:4] = b"RIFF"
    header[8:16] = b"WAVEfmt "
    struct.pack_into("<IHHIIHH", header, 16, 16, 1, 1, SR, SR * 2, 2, 16)
    header[36:40] = b"data"
    path.write_bytes(bytes(header) + pcm)


def test_read_pcm_ignores_stale_header_sizes(tmp_path: Path) -> None:
    wav = tmp_path / "m.wav"
    pcm = _tone(1.0)
    _write_growing_wav(wav, pcm)
    assert chunker.read_pcm(wav, start_sample=0) == pcm
    assert chunker.read_pcm(wav, start_sample=SR // 2) == pcm[SR:]


def test_read_pcm_drops_a_trailing_half_sample(tmp_path: Path) -> None:
    wav = tmp_path / "m.wav"
    _write_growing_wav(wav, _tone(0.5) + b"\x01")
    assert len(chunker.read_pcm(wav, start_sample=0)) % 2 == 0


def test_read_pcm_missing_file_is_empty(tmp_path: Path) -> None:
    assert chunker.read_pcm(tmp_path / "nope.wav", start_sample=0) == b""


def test_no_cut_before_min_seconds() -> None:
    pcm = _tone(2.0) + _silence(1.0)
    assert chunker.find_cut(pcm, chunker.LIVE) is None


def test_cuts_inside_first_pause_after_min_seconds() -> None:
    pcm = _tone(5.0) + _silence(0.6) + _tone(2.0)
    cut = chunker.find_cut(pcm, chunker.LIVE)
    assert cut is not None
    assert 5.0 * SR <= cut <= 5.6 * SR


def test_waits_for_a_pause_while_under_max_seconds() -> None:
    pcm = _tone(9.0)
    assert chunker.find_cut(pcm, chunker.LIVE) is None


def test_forces_a_cut_at_max_seconds_without_a_pause() -> None:
    pcm = _tone(13.0)
    cut = chunker.find_cut(pcm, chunker.LIVE)
    assert cut is not None
    assert chunker.LIVE.min_s * SR <= cut <= chunker.LIVE.max_s * SR


def test_flush_takes_everything_left() -> None:
    pcm = _tone(1.5)
    assert chunker.find_cut(pcm, chunker.LIVE, flush=True) == len(pcm) // 2
    assert chunker.find_cut(b"", chunker.LIVE, flush=True) is None


def test_final_profile_uses_longer_windows() -> None:
    pcm = _tone(10.0) + _silence(0.6) + _tone(10.0)
    # A pause at 10s is too early for the final pass (min 15s)…
    cut = chunker.find_cut(pcm, chunker.FINAL)
    assert cut is None


def test_iter_chunks_covers_the_whole_file_in_order(tmp_path: Path) -> None:
    wav = tmp_path / "m.wav"
    pcm = (_tone(5.0) + _silence(0.5)) * 6  # 33s with regular pauses
    _write_growing_wav(wav, pcm)
    chunks = list(chunker.iter_chunks(wav, chunker.LIVE))
    assert chunks[0].start_sample == 0
    for a, b in itertools.pairwise(chunks):
        assert b.start_sample == a.start_sample + len(a.pcm) // 2
    assert sum(len(c.pcm) for c in chunks) == len(pcm)


def test_pcm_to_wav_round_trips_through_the_wave_module(tmp_path: Path) -> None:
    pcm = _tone(0.25)
    out = tmp_path / "c.wav"
    out.write_bytes(chunker.pcm_to_wav(pcm))
    with wave.open(str(out)) as w:
        assert w.getframerate() == SR
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.readframes(w.getnframes()) == pcm
