from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ghostbrain.connectors.whatsapp import voice as v
from ghostbrain.connectors.whatsapp.store import Message


def vmsg(tmp_path: Path, *, stanza="ABC/1", exists=True) -> Message:
    path = tmp_path / "Message" / "Media" / f"{stanza.replace('/', '_')}.opus"
    if exists:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"opus")
    return Message(pk=1, stanza_id=stanza, at=datetime(2026, 10, 9, tzinfo=UTC),
                   sender="Alex", is_from_me=False, type_code=3, text=None, caption=None,
                   media_path=path)


def fake_to_wav(src: Path, dst: Path) -> None:
    dst.write_bytes(b"wav")


def fake_transcribe(text="hello there"):
    calls = []

    def run(wav: Path, *, timeout_s: int) -> Path:
        calls.append(wav)
        out = wav.with_suffix(".txt")
        out.write_text(f"{text}\n", encoding="utf-8")
        return out

    run.calls = calls
    return run


def make(tmp_path, *, budget=5, transcribe=None, live=False):
    return v.VoiceTranscriber(tmp_path / "cache", budget=budget,
                              transcribe=transcribe or fake_transcribe(),
                              to_wav=fake_to_wav, recording_live=lambda: live)


def test_miss_transcribes_and_caches(tmp_path):
    tr = fake_transcribe()
    t = make(tmp_path, transcribe=tr)
    assert t.line_for(vmsg(tmp_path)) == ("🎙 hello there", False)
    t2 = make(tmp_path, transcribe=fake_transcribe("WRONG"))
    assert t2.line_for(vmsg(tmp_path)) == ("🎙 hello there", False)
    assert len(tr.calls) == 1


def test_not_downloaded_is_not_cached(tmp_path):
    t = make(tmp_path)
    m = vmsg(tmp_path, exists=False)
    assert t.line_for(m) == (v.NOT_DOWNLOADED, False)
    cache = tmp_path / "cache"
    assert not cache.exists() or not any(cache.iterdir())
    m.media_path.parent.mkdir(parents=True, exist_ok=True)
    m.media_path.write_bytes(b"opus")
    assert t.line_for(m) == ("🎙 hello there", False)


def test_budget_exhaustion_is_pending(tmp_path):
    t = make(tmp_path, budget=1)
    assert t.line_for(vmsg(tmp_path, stanza="A"))[1] is False
    assert t.line_for(vmsg(tmp_path, stanza="B")) == (v.PENDING, True)


def test_live_recording_defers(tmp_path):
    tr = fake_transcribe()
    t = make(tmp_path, transcribe=tr, live=True)
    assert t.line_for(vmsg(tmp_path)) == (v.PENDING, True)
    assert tr.calls == []


def test_failures_retry_then_mark_failed(tmp_path):
    def boom(wav, *, timeout_s):
        raise RuntimeError("whisper died")

    m = vmsg(tmp_path)
    for _ in range(v.MAX_ATTEMPTS - 1):
        assert make(tmp_path, transcribe=boom).line_for(m) == (v.PENDING, True)
    assert make(tmp_path, transcribe=boom).line_for(m) == (v.FAILED, False)
    assert make(tmp_path).line_for(m) == (v.FAILED, False)


def test_empty_transcript(tmp_path):
    t = make(tmp_path, transcribe=fake_transcribe(""))
    assert t.line_for(vmsg(tmp_path)) == ("🎙 (no speech)", False)


def test_ffmpeg_missing_is_unavailable_and_burns_no_attempt(tmp_path, monkeypatch):
    monkeypatch.setattr(v, "_ffmpeg_binary", lambda: None)
    tr = fake_transcribe()
    t = v.VoiceTranscriber(tmp_path / "cache", budget=5, transcribe=tr,
                           recording_live=lambda: False)
    for _ in range(v.MAX_ATTEMPTS + 1):
        assert t.line_for(vmsg(tmp_path)) == (v.UNAVAILABLE, True)
    assert tr.calls == []
    assert not (tmp_path / "cache" / "ABC_1.failed").exists()
    # Once ffmpeg is installed the note transcribes normally.
    assert make(tmp_path, transcribe=tr).line_for(vmsg(tmp_path)) == ("🎙 hello there", False)


def test_missing_whisper_is_unavailable_and_stops_the_run(tmp_path):
    calls = []

    def no_whisper(wav, *, timeout_s):
        calls.append(wav)
        raise v.VoiceUnavailable("whisper-cli not found")

    t = make(tmp_path, budget=5, transcribe=no_whisper)
    assert t.line_for(vmsg(tmp_path, stanza="A")) == (v.UNAVAILABLE, True)
    assert t.budget == 0
    assert t.line_for(vmsg(tmp_path, stanza="B")) == (v.UNAVAILABLE, True)
    assert len(calls) == 1
    assert not list((tmp_path / "cache").glob("*.failed"))


def test_whisper_without_model_is_unavailable(monkeypatch, tmp_path):
    from ghostbrain.recorder import transcribe as tmod

    def no_model(model_path):
        raise tmod.TranscribeError("No whisper model found.")

    def must_not_run(*a, **k):
        raise AssertionError("transcribe called without a model")

    monkeypatch.setattr(tmod, "_resolve_model", no_model)
    monkeypatch.setattr(tmod, "transcribe", must_not_run)
    with pytest.raises(v.VoiceUnavailable):
        v._whisper(tmp_path / "x.wav", timeout_s=1)


def test_whisper_cli_missing_is_unavailable_other_errors_are_not(monkeypatch, tmp_path):
    from ghostbrain.recorder import transcribe as tmod

    def died(wav, *, timeout_s):
        raise tmod.TranscribeError("whisper failed")

    monkeypatch.setattr(tmod, "_resolve_model", lambda model_path: tmp_path / "m.bin")
    monkeypatch.setattr(tmod, "transcribe", died)
    monkeypatch.setattr(v.shutil, "which", lambda name: None)
    with pytest.raises(v.VoiceUnavailable):
        v._whisper(tmp_path / "x.wav", timeout_s=1)
    monkeypatch.setattr(v.shutil, "which", lambda name: f"/opt/homebrew/bin/{name}")
    with pytest.raises(tmod.TranscribeError):
        v._whisper(tmp_path / "x.wav", timeout_s=1)


def test_corrupt_failed_file_counts_as_zero(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "ABC_1.failed").write_text("not-a-number")

    def boom(wav, *, timeout_s):
        raise RuntimeError("whisper died")

    assert make(tmp_path, transcribe=boom).line_for(vmsg(tmp_path)) == (v.PENDING, True)
    assert (cache / "ABC_1.failed").read_text() == "1"


def test_transcript_cache_is_written_atomically(tmp_path, monkeypatch):
    replaced = []
    real_replace = v.os.replace

    def spy(src, dst):
        replaced.append((Path(src).name, Path(dst).name))
        real_replace(src, dst)

    monkeypatch.setattr(v.os, "replace", spy)
    assert make(tmp_path).line_for(vmsg(tmp_path)) == ("🎙 hello there", False)
    assert replaced == [("ABC_1.txt.tmp", "ABC_1.txt")]
    assert sorted(p.name for p in (tmp_path / "cache").iterdir()) == ["ABC_1.txt"]


def test_cached_line_for_never_transcribes(tmp_path):
    tr = fake_transcribe()
    t = make(tmp_path, transcribe=tr, budget=5)
    m = vmsg(tmp_path)
    assert t.cached_line_for(m) == (v.PENDING, True)
    assert tr.calls == [] and t.budget == 5
    assert t.line_for(m) == ("🎙 hello there", False)
    assert t.cached_line_for(m) == ("🎙 hello there", False)
    gone = vmsg(tmp_path, stanza="GONE", exists=False)
    assert t.cached_line_for(gone) == (v.NOT_DOWNLOADED, False)
