"""Cut a growing 16 kHz mono PCM16 WAV into pause-aligned chunks.

Every capture backend writes the recording WAV incrementally (the native
helper and WASAPI rewrite the header sizes about once a second; ffmpeg only
finalises them on SIGINT). So readers here never trust the header's size
fields: audio is simply everything after the fixed 44-byte header.

Chunks end inside a pause so whisper never sees a word cut in half. Each
chunk is transcribed on its own with language auto-detection, which is what
lets a meeting that switches between English and Afrikaans come out right —
whisper's own ``-l auto`` only detects once, from the first 30 seconds.
"""
from __future__ import annotations

import re
import struct
from array import array
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

SAMPLE_RATE = 16_000
BYTES_PER_SAMPLE = 2
WAV_HEADER_BYTES = 44

# Pause detection works on 100 ms blocks; a pause is 300 ms (3 blocks) quiet.
_BLOCK = SAMPLE_RATE // 10
_PAUSE_BLOCKS = 3
# A window counts as a pause when its RMS is under this fraction of the
# chunk's median block RMS — meeting audio levels vary too much for a fixed
# threshold — or under the absolute floor (true digital silence).
_PAUSE_RELATIVE = 0.15
_PAUSE_FLOOR = 150.0
# Below this in every block, a chunk is treated as silence and not sent.
_SILENT_RMS = 2 * _PAUSE_FLOOR


@dataclass(frozen=True)
class Profile:
    """How long a chunk may be. ``min_s`` before looking for a pause,
    ``max_s`` before cutting at the quietest point regardless."""

    min_s: float
    max_s: float


LIVE = Profile(min_s=4.0, max_s=12.0)
FINAL = Profile(min_s=15.0, max_s=30.0)


@dataclass(frozen=True)
class Chunk:
    start_sample: int
    pcm: bytes

    @property
    def start_s(self) -> float:
        return self.start_sample / SAMPLE_RATE

    @property
    def duration_s(self) -> float:
        return len(self.pcm) / BYTES_PER_SAMPLE / SAMPLE_RATE


def read_pcm(wav_path: Path, *, start_sample: int, max_samples: int | None = None) -> bytes:
    """PCM bytes from ``start_sample`` to the current end of the file."""
    try:
        with wav_path.open("rb") as f:
            f.seek(WAV_HEADER_BYTES + start_sample * BYTES_PER_SAMPLE)
            data = f.read(-1 if max_samples is None else max_samples * BYTES_PER_SAMPLE)
    except OSError:
        return b""
    # The writer may be mid-sample; only hand back whole samples.
    return data[: len(data) - len(data) % BYTES_PER_SAMPLE]


def block_rms(pcm: bytes) -> list[float]:
    samples = array("h")
    samples.frombytes(pcm[: len(pcm) - len(pcm) % BYTES_PER_SAMPLE])
    out: list[float] = []
    for i in range(0, len(samples) - _BLOCK + 1, _BLOCK):
        block = samples[i : i + _BLOCK]
        out.append((sum(s * s for s in block) / _BLOCK) ** 0.5)
    return out


def is_silent(pcm: bytes) -> bool:
    """True when no 100 ms block rises above the silence floor — nothing for
    whisper to hear (it would hallucinate "Thank you." on it)."""
    return all(level < _SILENT_RMS for level in block_rms(pcm))


# What whisper says over near-silence (a key click or a breath is enough to
# get a chunk past is_silent). Matched on the whole segment, so real speech
# that merely contains these words is never touched.
_HALLUCINATIONS = re.compile(
    r"^\W*(?:thank you(?: (?:very much|so much|for watching|for listening))?"
    r"|thanks(?: for watching| for listening)?|you|bye|bye[- ]bye"
    r"|i'?m sorry|please subscribe|subtitles by .*)\W*$",
    re.IGNORECASE,
)
# Less loud audio than this (in 100 ms blocks) cannot hold a spoken phrase.
_HALLUCINATION_MAX_LOUD_BLOCKS = 8


def is_hallucination(text: str, pcm: bytes) -> bool:
    """True when ``text`` is one of whisper's stock silence phrases and the
    audio it came from is too quiet to have contained it."""
    if not _HALLUCINATIONS.match(text.strip()):
        return False
    loud = sum(1 for level in block_rms(pcm) if level >= _SILENT_RMS)
    return loud < _HALLUCINATION_MAX_LOUD_BLOCKS


def find_cut(pcm: bytes, profile: Profile, *, flush: bool = False) -> int | None:
    """How many samples of ``pcm`` to take as the next chunk, or None to
    wait for more audio. ``flush`` takes whatever is left (end of recording)."""
    n = len(pcm) // BYTES_PER_SAMPLE
    if flush:
        return n or None
    min_blocks = int(profile.min_s * 10)
    max_blocks = int(profile.max_s * 10)
    if n < min_blocks * _BLOCK:
        return None

    rms = block_rms(pcm[: max_blocks * _BLOCK * BYTES_PER_SAMPLE])
    if len(rms) < _PAUSE_BLOCKS:
        return None
    median = sorted(rms)[len(rms) // 2]
    threshold = max(_PAUSE_FLOOR, median * _PAUSE_RELATIVE)

    windows = [
        (sum(rms[i : i + _PAUSE_BLOCKS]) / _PAUSE_BLOCKS, i)
        for i in range(max(0, min_blocks - 1), len(rms) - _PAUSE_BLOCKS + 1)
    ]
    for level, i in windows:
        if level < threshold:
            # Cut in the middle of the first pause past min_s.
            return (i + _PAUSE_BLOCKS // 2) * _BLOCK + _BLOCK // 2

    if n < max_blocks * _BLOCK or not windows:
        return None
    # Nobody paused for max_s: cut at the quietest point we saw.
    _, i = min(windows)
    return (i + _PAUSE_BLOCKS // 2) * _BLOCK + _BLOCK // 2


def next_chunk(
    wav_path: Path, start_sample: int, profile: Profile, *, flush: bool = False,
) -> Chunk | None:
    """The next pause-aligned chunk starting at ``start_sample``, if ready."""
    limit = None if flush else int(profile.max_s * SAMPLE_RATE)
    pcm = read_pcm(wav_path, start_sample=start_sample, max_samples=limit)
    cut = find_cut(pcm, profile, flush=flush)
    if cut is None:
        return None
    return Chunk(start_sample=start_sample, pcm=pcm[: cut * BYTES_PER_SAMPLE])


def iter_chunks(
    wav_path: Path,
    profile: Profile,
    *,
    start_sample: int = 0,
    end_sample: int | None = None,
) -> Iterator[Chunk]:
    """Chunk a finished WAV from ``start_sample`` to ``end_sample`` (or EOF).
    No chunk crosses ``end_sample``."""
    window = int(profile.max_s * SAMPLE_RATE)
    pos = start_sample
    while end_sample is None or pos < end_sample:
        limit = window if end_sample is None else min(window, end_sample - pos)
        pcm = read_pcm(wav_path, start_sample=pos, max_samples=limit)
        if not pcm:
            return
        # find_cut always cuts a full window, so None means this is the tail
        # of the range: take it whole.
        cut = find_cut(pcm, profile) or len(pcm) // BYTES_PER_SAMPLE
        yield Chunk(start_sample=pos, pcm=pcm[: cut * BYTES_PER_SAMPLE])
        pos += cut


def pcm_to_wav(pcm: bytes) -> bytes:
    """Wrap raw PCM16 mono 16 kHz in a WAV header (for posting to the server)."""
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + len(pcm), b"WAVE",
        b"fmt ", 16, 1, 1, SAMPLE_RATE, SAMPLE_RATE * BYTES_PER_SAMPLE,
        BYTES_PER_SAMPLE, 16,
        b"data", len(pcm),
    )
    return header + pcm
