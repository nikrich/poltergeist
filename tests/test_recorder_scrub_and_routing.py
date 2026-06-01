"""Tests for the audio-routing precondition + whisper noise scrub.

The recorder failed silently in production: a 72-minute manual recording
produced a transcript with 129 [BLANK_AUDIO] lines and zero real content
because the macOS Output device wasn't routed through BlackHole. These
tests pin both halves of the fix:

- ``_scrub_noise_tokens`` removes the silence-marker lines whisper.cpp
  emits, so a noise-only recording can be detected by callers (empty
  file = warn) instead of dumped into the vault as 100% noise.
- ``output_likely_reaches_blackhole`` accepts the canonical Ghost Brain
  multi-output, direct BlackHole, generic aggregate-device labels, and
  user-extended names; rejects anything else (and falls open on probe
  failure so a broken probe never blocks recording).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ghostbrain.recorder import audio_capture
from ghostbrain.recorder.audio_capture import (
    AudioRoutingError,
    assert_output_routes_to_blackhole,
    output_likely_reaches_blackhole,
)
from ghostbrain.recorder.transcribe import (
    _NOISE_TOKEN_RE,
    _collapse_phrase_loops,
    _scrub_noise_tokens,
    _whisper_cmd,
)


# ---------------------------------------------------------------------------
# Noise scrub
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("line", [
    "[BLANK_AUDIO]",
    "[ BLANK_AUDIO ]",
    "[blank_audio]",
    "[SILENCE]",
    "[ Silence ]",
    "[silence]",
    "[MUSIC]",
    "[music]",
    "[NOISE]",
    "[INAUDIBLE]",
    "[ pause ]",
    "[_BEG_]",
    "[_END_]",
    "  [BLANK_AUDIO]  ",
    # whisper-cli's -otxt prefixes each segment with " >> " (the speaker
    # marker). A noise segment must still be scrubbed even with that prefix
    # — without this, every meeting recorded with trailing silence ends up
    # with a wall of " >> [INAUDIBLE]" lines in the saved transcript.
    " >> [INAUDIBLE]",
    ">> [BLANK_AUDIO]",
    "  >>   [ Silence ]  ",
    # whisper sometimes packs multiple noise tokens into a single segment.
    " >> [INAUDIBLE] [INAUDIBLE] [INAUDIBLE]",
    "[BLANK_AUDIO] [BLANK_AUDIO]",
])
def test_noise_token_regex_matches(line: str) -> None:
    assert _NOISE_TOKEN_RE.match(line), f"expected match: {line!r}"


@pytest.mark.parametrize("line", [
    "real transcript text",
    "[00:01:23.000 --> 00:01:25.000] hello there",
    "[BLANK_AUDIO] but actually some text",
    "music was playing in the background",  # word "music" but no brackets
    "[Unknown speaker]",  # different bracket content
    "",
])
def test_noise_token_regex_skips_real_lines(line: str) -> None:
    assert not _NOISE_TOKEN_RE.match(line), f"unexpected match: {line!r}"


def test_scrub_drops_noise_lines_and_keeps_real_ones(tmp_path: Path) -> None:
    """A typical whisper.cpp output with mostly noise + a few real lines."""
    p = tmp_path / "x.txt"
    p.write_text(
        "[BLANK_AUDIO]\n"
        "Hey team, can someone look at the partner deploy?\n"
        "[ Silence ]\n"
        "[BLANK_AUDIO]\n"
        "Yeah I'll grab it after lunch.\n"
        "[MUSIC]\n",
        encoding="utf-8",
    )
    _scrub_noise_tokens(p)
    out = p.read_text(encoding="utf-8").splitlines()
    assert out == [
        "Hey team, can someone look at the partner deploy?",
        "Yeah I'll grab it after lunch.",
    ]


def test_scrub_empty_when_all_noise(tmp_path: Path) -> None:
    """Recordings with zero detected speech (output device misrouted)
    collapse to an empty file — the caller can detect this and warn
    instead of writing a useless note."""
    p = tmp_path / "x.txt"
    p.write_text("[BLANK_AUDIO]\n" * 50 + "[SILENCE]\n[MUSIC]\n", encoding="utf-8")
    _scrub_noise_tokens(p)
    assert p.read_text(encoding="utf-8") == ""


def test_scrub_idempotent(tmp_path: Path) -> None:
    p = tmp_path / "x.txt"
    p.write_text("real line one\n[BLANK_AUDIO]\nreal line two\n", encoding="utf-8")
    _scrub_noise_tokens(p)
    once = p.read_text(encoding="utf-8")
    _scrub_noise_tokens(p)
    twice = p.read_text(encoding="utf-8")
    assert once == twice == "real line one\nreal line two\n"


def test_scrub_missing_file_is_noop(tmp_path: Path) -> None:
    """A racy whisper failure that leaves no .txt should not crash the
    scrubber — the caller will have its own missing-file error."""
    _scrub_noise_tokens(tmp_path / "does-not-exist.txt")  # no raise


# ---------------------------------------------------------------------------
# Phrase-loop collapse (whisper context hallucinations)
# ---------------------------------------------------------------------------


def test_whisper_cmd_includes_no_context_flag() -> None:
    """-nc is the canonical mitigation for whisper.cpp riding a single
    hallucinated short phrase across an entire file. Without it whisper
    feeds each segment's text into the next as a prompt, snowballing
    "Okay." into hundreds of "Okay. Okay. Okay." lines."""
    cmd = _whisper_cmd("/bin/whisper-cli", Path("/m.bin"), Path("/w.wav"), Path("/w"))
    assert "-nc" in cmd


def test_collapse_short_phrase_loop() -> None:
    raw = "I'll try direct debit. Okay. Okay. Okay. Okay. Okay. Okay. Okay."
    out = _collapse_phrase_loops(raw)
    assert "Okay." in out
    assert "[...repeated 7x]" in out
    # Real text before the loop survives.
    assert "I'll try direct debit." in out


def test_collapse_long_phrase_without_terminator() -> None:
    """The May-29 / Jun-01 transcripts looped on "And then we had our third
    one last quarter" — 9 words, no terminating punctuation. Must collapse."""
    phrase = "And then we had our third one last quarter"
    raw = "Opening sentence. " + " ".join([phrase] * 12)
    out = _collapse_phrase_loops(raw)
    assert "[...repeated 12x]" in out
    # Phrase appears exactly once in the collapsed output.
    assert out.count(phrase) == 1
    assert "Opening sentence." in out


def test_collapse_spans_newlines() -> None:
    """whisper-cli writes one segment per line; loops typically span many
    segments and therefore many file lines. The regex must traverse \\s+
    (which includes newlines) to collapse those cross-line runs."""
    raw = "\n".join([" >> Okay."] * 8)
    out = _collapse_phrase_loops(raw)
    assert "[...repeated 8x]" in out


def test_collapse_preserves_short_runs() -> None:
    """Three repeats of "Yeah." can occur naturally in conversation and
    must NOT be collapsed. The collapse threshold is intentionally
    conservative."""
    raw = "Yeah. Yeah. Yeah. Yeah."  # 4 reps, below the 5-rep threshold
    out = _collapse_phrase_loops(raw)
    assert out == raw


def test_collapse_preserves_unrelated_text() -> None:
    raw = "The deploy worked. Tests passed. Shipping it now."
    out = _collapse_phrase_loops(raw)
    assert out == raw


def test_scrub_collapses_loop_in_full_pipeline(tmp_path: Path) -> None:
    """End-to-end: the file-level scrub applies the loop collapser before
    the per-line noise filter, so a whisper-cli output containing both a
    loop and noise markers comes out clean."""
    p = tmp_path / "x.txt"
    p.write_text(
        " >> So I'll try direct debit. "
        + ("Okay. " * 30).rstrip() + "\n"
        " >> [INAUDIBLE]\n"
        " >> Sounds good.\n",
        encoding="utf-8",
    )
    _scrub_noise_tokens(p)
    out = p.read_text(encoding="utf-8")
    assert "Okay." in out  # one canonical copy
    assert "[...repeated" in out  # loop marker present
    assert out.count("Okay.") <= 2  # not 30
    assert "[INAUDIBLE]" not in out
    assert "Sounds good." in out


# ---------------------------------------------------------------------------
# Output routing
# ---------------------------------------------------------------------------


def test_output_routes_blackhole_directly() -> None:
    assert output_likely_reaches_blackhole("BlackHole 2ch")
    assert output_likely_reaches_blackhole("blackhole 16ch")


def test_output_routes_via_named_multi_output() -> None:
    """Ghost Brain is the canonical multi-output device the bootstrap
    creates. The check has to accept it (and the typical macOS default
    aggregate-device labels) since system_profiler doesn't expose
    sub-device lists in JSON."""
    assert output_likely_reaches_blackhole("Ghost Brain")
    assert output_likely_reaches_blackhole("Multi-Output Device")
    assert output_likely_reaches_blackhole("Aggregate Device")


def test_output_rejects_plain_speakers() -> None:
    """Speakers don't relay to BlackHole — recording would only capture
    the mic. This is the failure mode that produced the original
    [BLANK_AUDIO] transcript."""
    assert not output_likely_reaches_blackhole("MacBook Pro Speakers")
    assert not output_likely_reaches_blackhole("AirPods Pro")
    assert not output_likely_reaches_blackhole("External Headphones")


def test_output_env_var_extends_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    """Users with a custom multi-output name can opt in without a code
    change."""
    assert not output_likely_reaches_blackhole("Studio Bus")
    monkeypatch.setenv("GHOSTBRAIN_ALLOWED_AUDIO_OUTPUTS", "studio bus,other thing")
    assert output_likely_reaches_blackhole("Studio Bus")
    assert output_likely_reaches_blackhole("Other Thing")


def test_output_unknown_probe_falls_open() -> None:
    """When system_profiler can't be queried (linux dev, broken install),
    returning None should be treated as 'allow' — better a silent
    recording than a permanently-blocked one."""
    assert output_likely_reaches_blackhole(None)


def test_assert_raises_with_actionable_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """The exception body has to tell the user exactly what to fix —
    a generic 'recording failed' is what we're moving away from."""
    monkeypatch.setattr(
        audio_capture, "current_default_output_device", lambda: "MacBook Pro Speakers",
    )
    with pytest.raises(AudioRoutingError) as exc_info:
        assert_output_routes_to_blackhole()
    msg = str(exc_info.value)
    assert "MacBook Pro Speakers" in msg
    assert "BlackHole" in msg
    assert "Ghost Brain" in msg or "multi-output" in msg.lower()


def test_assert_silent_when_routed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        audio_capture, "current_default_output_device", lambda: "Ghost Brain",
    )
    assert_output_routes_to_blackhole()  # no raise
