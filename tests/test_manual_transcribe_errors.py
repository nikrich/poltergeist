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
