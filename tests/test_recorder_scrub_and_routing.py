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
from ghostbrain.recorder.transcribe import _NOISE_TOKEN_RE, _scrub_noise_tokens


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
