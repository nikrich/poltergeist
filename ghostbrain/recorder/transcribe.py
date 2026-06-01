"""Wrap whisper-cli (whisper.cpp) to transcribe a WAV file."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger("ghostbrain.recorder.transcribe")

DEFAULT_MODEL_DIR = Path.home() / "ghostbrain" / "recorder" / "models"
DEFAULT_MODEL = "ggml-medium.en.bin"
DEFAULT_TIMEOUT_S = 30 * 60  # 30 min for a long meeting; whisper is fast on Apple Silicon

# whisper.cpp emits these tokens whenever a segment has no detectable speech.
# Useful as an internal signal (low-energy audio) but visually destructive in
# the final transcript — a meeting recorded with the wrong audio output
# becomes 100+ lines of "[BLANK_AUDIO]" with no content. We strip them and
# collapse repeated noise markers; if the WHOLE transcript was noise the
# caller sees an empty file and can warn rather than save a junk note.
#
# Lines also commonly carry whisper-cli's " >> " speaker prefix and may pack
# multiple noise tokens into a single segment (e.g. " >> [INAUDIBLE]
# [INAUDIBLE]"), so the regex tolerates a leading ">>" and matches one-or-more
# bracketed markers — anything mixed with real text still falls through.
_NOISE_TOKEN_RE = re.compile(
    r"^\s*(?:>>\s*)?"
    r"(?:\[\s*(?:"
    r"BLANK_AUDIO|"
    r"SILENCE|silence|"
    r"MUSIC|music|"
    r"NOISE|noise|"
    r"INAUDIBLE|inaudible|"
    r"PAUSE|pause|"
    r"_BEG_|_END_"
    r")\s*\]\s*)+$",
    re.IGNORECASE,
)

# Whisper sometimes falls into a context-loop on ambiguous audio: it emits
# "Okay." (or "And then we had our third one last quarter", or any short
# phrase) for one segment, then each subsequent segment is decoded with the
# prior text as a prompt, biasing the model toward re-emitting the same
# phrase — for hundreds of segments. `-nc` on the whisper-cli side prevents
# new transcripts from looping; this regex collapses any loop that slips
# through (and cleans historical transcripts written before -nc was added).
#
# Threshold: ≥5 back-to-back exact repetitions of a 1–15-word phrase. Natural
# speech doesn't repeat the same multi-word phrase five times in a row — the
# false-positive rate at this threshold is essentially zero, while the
# false-negative rate against whisper's actual hallucination patterns is low.
_PHRASE_LOOP_RE = re.compile(
    # Lazy inner quantifier so the SHORTEST repeating unit is captured. That
    # makes the `[...repeated Nx]` marker reflect actual occurrence count
    # ("Okay. [...repeated 30x]") rather than a greedy multi-copy unit.
    # No trailing `\b` because phrases often end in punctuation, and `\W\W`
    # transitions don't carry a word boundary.
    r"(\S+(?:\s+\S+){0,14}?)(?:\s+\1){4,}",
)


def _collapse_phrase_loops(text: str) -> str:
    """Collapse runs of identical short phrases into one copy plus a marker."""
    def repl(m: re.Match) -> str:
        phrase = m.group(1)
        # Count non-overlapping occurrences across the matched run. Safe for
        # whole-phrase matches at word boundaries — the regex ensures every
        # repetition is a full \b…\b copy of group(1).
        n = m.group(0).count(phrase)
        return f"{phrase} [...repeated {n}x]"
    return _PHRASE_LOOP_RE.sub(repl, text)


def _whisper_cmd(
    binary: str,
    model: Path,
    wav_path: Path,
    output_base: Path,
    *,
    threads: int | None = None,
) -> list[str]:
    """Build the whisper-cli command line.

    `-nc` (no-context) is critical: without it, whisper feeds each segment's
    decoded text into the next segment as a prompt. That carry-over is the
    root cause of "Okay. Okay. Okay." loops in the saved transcript when
    the model briefly stalls on ambiguous audio.
    """
    cmd = [
        binary,
        "-m", str(model),
        "-f", str(wav_path),
        "-otxt",
        "-of", str(output_base),
        "-l", "en",
        "-nc",
    ]
    if threads:
        cmd.extend(["-t", str(threads)])
    return cmd


class TranscribeError(RuntimeError):
    pass


def transcribe(
    wav_path: Path,
    *,
    model_path: Path | None = None,
    threads: int | None = None,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> Path:
    """Run whisper-cli on a WAV file and return the path to the .txt output.

    The .txt lands next to the .wav (whisper-cli's default output naming).
    """
    binary = shutil.which("whisper-cli")
    if binary is None:
        raise TranscribeError(
            "`whisper-cli` not found on PATH. Install via `brew install whisper-cpp`."
        )

    if not wav_path.exists():
        raise TranscribeError(f"WAV not found: {wav_path}")

    model = _resolve_model(model_path)
    output_base = wav_path.with_suffix("")  # whisper-cli appends .txt itself

    cmd = _whisper_cmd(binary, model, wav_path, output_base, threads=threads)

    log.info("transcribing %s with %s", wav_path.name, model.name)
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as e:
        raise TranscribeError(f"whisper-cli timed out after {timeout_s}s") from e
    if proc.returncode != 0:
        raise TranscribeError(
            f"whisper-cli exited {proc.returncode}: "
            f"{(proc.stderr or '').strip()[:300]}"
        )

    txt_path = output_base.with_suffix(".txt")
    if not txt_path.exists():
        raise TranscribeError(f"whisper-cli ran but no .txt at {txt_path}")
    _scrub_noise_tokens(txt_path)
    return txt_path


def _scrub_noise_tokens(txt_path: Path) -> None:
    """Rewrite the transcript with whisper's silence-marker lines removed.

    Whisper emits one timestamped line per segment. When a segment has no
    speech the line is "[BLANK_AUDIO]" (or "[SILENCE]" etc.). Surfacing
    those to the user is purely noise — they don't carry any information
    the user can act on, and they hide the real content when speech IS
    sparse. We rewrite in place so every downstream consumer sees the
    clean version.

    Empty lines after scrubbing are also dropped — an all-noise recording
    becomes an empty file, which lets the daemon decide to emit an
    "audio captured but no speech detected" warning instead of saving a
    note that's 100% silence markers.
    """
    try:
        raw = txt_path.read_text(encoding="utf-8")
    except OSError:
        return  # leave file untouched on read error
    kept: list[str] = []
    dropped = 0
    for line in raw.splitlines():
        if _NOISE_TOKEN_RE.match(line):
            dropped += 1
            continue
        if not line.strip():
            continue
        kept.append(line)
    # Collapse hallucination loops AFTER the per-line noise filter. Doing it
    # before would consolidate runs of "[BLANK_AUDIO]" into a single line
    # with a "[...repeated]" suffix that the noise filter then can't drop,
    # so an all-noise recording wouldn't collapse to an empty file.
    body = _collapse_phrase_loops("\n".join(kept))
    if dropped:
        log.info(
            "scrubbed %d noise marker(s) from %s (%d real line(s) kept)",
            dropped, txt_path.name, len(kept),
        )
    # Preserve trailing newline for tools that expect it.
    txt_path.write_text(body + ("\n" if body else ""), encoding="utf-8")


def _resolve_model(model_path: Path | None) -> Path:
    if model_path is not None:
        if not model_path.exists():
            raise TranscribeError(f"model not found at {model_path}")
        return model_path

    env_path = os.environ.get("GHOSTBRAIN_WHISPER_MODEL")
    if env_path:
        p = Path(env_path).expanduser()
        if p.exists():
            return p
        raise TranscribeError(f"GHOSTBRAIN_WHISPER_MODEL set but {p} missing")

    default = DEFAULT_MODEL_DIR / DEFAULT_MODEL
    if default.exists():
        return default
    raise TranscribeError(
        f"No whisper model found. Drop a ggml-*.bin file at "
        f"{DEFAULT_MODEL_DIR}/ or set GHOSTBRAIN_WHISPER_MODEL."
    )
