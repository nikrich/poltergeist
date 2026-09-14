from __future__ import annotations

import json
from pathlib import Path

import pytest

from ghostbrain.api.repo import recorder as repo
from ghostbrain.recorder import manual
from ghostbrain.recorder.transcribe import TranscribeError


def _wav(tmp_path: Path) -> Path:
    wav = tmp_path / "meeting-20260911-090000-manual.wav"
    wav.write_bytes(b"RIFF" + b"\0" * 200_000)
    return wav


def test_recover_one_raises_when_whisper_fails(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(manual, "_already_filed", lambda name: False)
    monkeypatch.setattr(manual, "transcribe", lambda wav: (_ for _ in ()).throw(TranscribeError("`whisper-cli` not found on PATH. Install via `brew install whisper-cpp`.")))
    cfg = manual.ManualConfig(enabled=True, context="work", recordings_dir=tmp_path)
    with pytest.raises(TranscribeError, match="whisper-cli"):
        manual.recover_one(_wav(tmp_path), cfg)


def test_recover_one_raises_on_empty_transcript(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(manual, "_already_filed", lambda name: False)
    txt = tmp_path / "out.txt"
    txt.write_text("   \n")
    monkeypatch.setattr(manual, "transcribe", lambda wav: txt)
    cfg = manual.ManualConfig(enabled=True, context="work", recordings_dir=tmp_path)
    with pytest.raises(TranscribeError, match="empty"):
        manual.recover_one(_wav(tmp_path), cfg)


def test_background_transcribe_persists_the_error(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(repo, "STATE_FILE", tmp_path / "manual.state")
    monkeypatch.setattr(repo, "recover_one", lambda *a, **k: (_ for _ in ()).throw(TranscribeError("No whisper model found. Drop a ggml-*.bin file at ~/ghostbrain/recorder/models/")))
    (tmp_path / "manual.state").write_text(json.dumps({"phase": "transcribing"}))
    repo._transcribe_in_background({"wavPath": str(tmp_path / "x.wav"), "startedAt": "2026-09-11T09:00:00+00:00"})
    state = json.loads((tmp_path / "manual.state").read_text())
    assert state["phase"] == "done"
    assert "No whisper model found" in state["error"]


def test_orphan_recovery_continues_after_non_transcription_failure(tmp_path: Path, monkeypatch):
    """Verify that the orphan recovery sweep continues when one WAV fails with a non-transcription error."""
    # Create two orphan WAVs
    wav1 = tmp_path / "meeting-20260911-090000-manual.wav"
    wav1.write_bytes(b"RIFF" + b"\0" * 200_000)
    wav2 = tmp_path / "meeting-20260911-091500-manual.wav"
    wav2.write_bytes(b"RIFF" + b"\0" * 200_000)

    # Mock recover_one to fail for wav1 with OSError, succeed for wav2
    call_count = [0]

    def mock_recover_one(wav: Path, cfg, **kwargs):
        call_count[0] += 1
        if wav.name == "meeting-20260911-090000-manual.wav":
            raise OSError("disk full")
        # For wav2, create and return a transcript
        tx = tmp_path / "transcript.md"
        tx.write_text("# Meeting transcript\n\nSome content")
        return tx

    monkeypatch.setattr(manual, "recover_one", mock_recover_one)
    monkeypatch.setattr(manual, "_already_filed", lambda name: False)
    monkeypatch.setattr(manual, "_looks_alive", lambda wav, now: False)  # Don't filter by age

    # Run the recovery sweep
    results = manual.run_recovery_pass(manual.ManualConfig(enabled=True, context="work", recordings_dir=tmp_path))

    # Both WAVs should have been processed (call_count == 2), and one successful result returned
    assert call_count[0] == 2, f"Expected 2 calls to recover_one, got {call_count[0]}"
    assert len(results) == 1, f"Expected 1 successful recovery, got {len(results)}"
