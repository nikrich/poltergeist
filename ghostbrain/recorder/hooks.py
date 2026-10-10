"""Recorder lifecycle hooks other modules subscribe to.

``on_transcribed`` callbacks run once a recording's meeting note has been
written (manual recordings and calendar recordings alike), with the WAV path
and the note path. The design module uses it to link a session's artefact
to its meeting. Failures are logged only: nothing here may raise into
transcription.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger("ghostbrain.recorder.hooks")

_on_transcribed: list[Callable[[Path, Path], None]] = []


def on_transcribed(callback: Callable[[Path, Path], None]) -> None:
    """Run ``callback(wav, note_path)`` after each meeting note is written."""
    if callback not in _on_transcribed:
        _on_transcribed.append(callback)


def fire_transcribed(wav: Path, note_path: Path) -> None:
    """Call every ``on_transcribed`` callback. Never raises."""
    for callback in _on_transcribed[:]:  # a callback may register another
        try:
            callback(Path(wav), Path(note_path))
        except Exception:
            log.exception("on_transcribed hook failed for %s", Path(wav).name)
