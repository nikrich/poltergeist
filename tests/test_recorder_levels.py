"""Audio levels for the recording waveform, read from the growing WAV."""
from __future__ import annotations

import math
import struct
import threading
import time
from pathlib import Path

from ghostbrain.recorder import chunker, levels

SR = chunker.SAMPLE_RATE


def _tone(seconds: float, amp: int) -> bytes:
    return b"".join(
        struct.pack("<h", int(amp * math.sin(2 * math.pi * 440 * i / SR)))
        for i in range(int(seconds * SR))
    )


def _wav(tmp_path: Path, pcm: bytes = b"") -> Path:
    header = bytearray(44)
    header[0:4] = b"RIFF"
    header[8:16] = b"WAVEfmt "
    struct.pack_into("<IHHIIHH", header, 16, 16, 1, 1, SR, SR * 2, 2, 16)
    header[36:40] = b"data"
    p = tmp_path / "m.wav"
    p.write_bytes(bytes(header) + pcm)
    return p


def test_to_level_maps_dbfs_onto_0_1() -> None:
    assert levels.to_level(0) == 0.0
    assert levels.to_level(32767) == 1.0
    # -60 dBFS is the floor, -30 dBFS is halfway.
    assert levels.to_level(32768 * 10 ** (-60 / 20)) == 0.0
    assert abs(levels.to_level(32768 * 10 ** (-30 / 20)) - 0.5) < 0.01


def test_prefills_the_window_from_recent_audio(tmp_path: Path) -> None:
    wav = _wav(tmp_path, _tone(1.0, 200) + _tone(1.0, 16000))
    gen = levels.follow_levels(wav, prefill_blocks=10, idle_timeout_s=0.2, interval_s=0.01)
    first = next(gen)
    assert first is not None and len(first) == 10  # the last second
    assert min(first) > 0.8


def test_streams_new_blocks_then_stops_when_the_file_stops_growing(tmp_path: Path) -> None:
    wav = _wav(tmp_path)
    out: list[list[float]] = []
    done = threading.Event()

    def consume() -> None:
        for lv in levels.follow_levels(wav, prefill_blocks=0, idle_timeout_s=0.5, interval_s=0.01):
            if lv:
                out.append(lv)
        done.set()

    threading.Thread(target=consume, daemon=True).start()
    for amp in (0, 16000, 0):
        with wav.open("ab") as f:
            f.write(_tone(0.3, amp))
        time.sleep(0.05)
    assert done.wait(5), "should end once the WAV stops growing"
    flat = [v for chunk in out for v in chunk]
    assert len(flat) == 9  # 0.9 s of audio in 100 ms blocks
    assert max(flat[:3]) == 0.0 and min(flat[3:6]) > 0.8 and max(flat[6:]) == 0.0


def test_partial_blocks_wait_for_the_rest(tmp_path: Path) -> None:
    wav = _wav(tmp_path, _tone(0.15, 16000))  # 1.5 blocks
    gen = levels.follow_levels(wav, prefill_blocks=5, idle_timeout_s=0.3, interval_s=0.01)
    got = [lv for lv in gen if lv]
    assert sum(len(x) for x in got) == 1
