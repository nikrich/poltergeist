from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

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


def test_ffmpeg_missing_is_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(v, "_ffmpeg_binary", lambda: None)
    t = v.VoiceTranscriber(tmp_path / "cache", budget=5, transcribe=fake_transcribe(),
                           recording_live=lambda: False)
    assert t.line_for(vmsg(tmp_path)) == (v.PENDING, True)
