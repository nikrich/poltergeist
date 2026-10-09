"""Live transcription of a recording WAV while it grows."""
from __future__ import annotations

import json
import math
import struct
import threading
import time
from pathlib import Path

import pytest

from ghostbrain.recorder import chunker, live
from ghostbrain.recorder.whisper_server import Segment, WhisperServerError

SR = chunker.SAMPLE_RATE


def _speech_then_pause(seconds: float = 5.0) -> bytes:
    tone = b"".join(
        struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / SR)))
        for i in range(int(seconds * SR))
    )
    return tone + b"\x00\x00" * int(0.6 * SR)


SPEECH = _speech_then_pause()


class FakeServer:
    """Duck-typed WhisperServer. ``fail_on`` = call numbers that raise."""

    def __init__(self, *, fail_on: tuple[int, ...] = (), fail_start: bool = False):
        self.fail_on = set(fail_on)
        self.fail_start = fail_start
        self.calls = 0
        self.languages: list[str] = []
        self.running = False
        self.starts = 0

    def start(self, timeout_s: float = 60.0) -> None:
        self.starts += 1
        if self.fail_start:
            raise WhisperServerError("no model")
        self.running = True

    def alive(self) -> bool:
        return self.running

    def stop(self) -> None:
        self.running = False

    def transcribe(self, pcm: bytes, *, language: str = "auto", offset_s: float = 0.0) -> list[Segment]:
        self.calls += 1
        self.languages.append(language)
        if self.calls in self.fail_on:
            self.running = False
            raise WhisperServerError("crashed")
        dur = len(pcm) / 2 / SR
        return [Segment(t0=round(offset_s, 2), t1=round(offset_s + dur, 2),
                        text=f"chunk at {offset_s:.1f}", lang="en")]


def _header() -> bytes:
    header = bytearray(44)
    header[0:4] = b"RIFF"
    header[8:16] = b"WAVEfmt "
    struct.pack_into("<IHHIIHH", header, 16, 16, 1, 1, SR, SR * 2, 2, 16)
    header[36:40] = b"data"
    return bytes(header)


@pytest.fixture
def wav(tmp_path: Path) -> Path:
    path = tmp_path / "meeting-20261009-100000-manual.wav"
    path.write_bytes(_header())
    return path


@pytest.fixture(autouse=True)
def _no_sessions():
    yield
    live.stop_all()


def _grow(wav: Path, pcm: bytes) -> None:
    with wav.open("ab") as f:
        f.write(pcm)


def _wait(pred, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return
        time.sleep(0.02)
    raise AssertionError("condition not met in time")


def _segments(wav: Path) -> list[dict]:
    p = live.live_path(wav)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def test_transcribes_chunks_as_the_wav_grows(wav: Path) -> None:
    server = FakeServer()
    session = live.begin(wav, server_factory=lambda: server, poll_s=0.01)
    assert session is not None
    _grow(wav, SPEECH)
    _wait(lambda: len(_segments(wav)) == 1)
    _grow(wav, SPEECH)
    _wait(lambda: len(_segments(wav)) == 2)

    segs = _segments(wav)
    assert [s["seq"] for s in segs] == [1, 2]
    assert segs[0]["t0"] == 0.0
    assert 5.0 <= segs[1]["t0"] <= 5.6
    assert session.status()["state"] == "live"


def test_fixed_language_is_passed_to_the_server(wav: Path) -> None:
    server = FakeServer()
    live.begin(wav, server_factory=lambda: server, language="af", poll_s=0.01)
    _grow(wav, SPEECH)
    _wait(lambda: server.calls >= 1)
    assert server.languages[0] == "af"


def test_restarts_the_server_once_after_a_crash(wav: Path) -> None:
    server = FakeServer(fail_on=(1,))
    live.begin(wav, server_factory=lambda: server, poll_s=0.01)
    _grow(wav, SPEECH)
    _wait(lambda: len(_segments(wav)) == 1)
    assert server.starts == 2
    # The crashed chunk was retried, not skipped.
    assert _segments(wav)[0]["t0"] == 0.0


def test_gives_up_after_a_second_crash(wav: Path) -> None:
    server = FakeServer(fail_on=(1, 2))
    session = live.begin(wav, server_factory=lambda: server, poll_s=0.01)
    _grow(wav, SPEECH)
    _wait(lambda: session.status()["state"] == "unavailable")
    assert "crashed" in session.status()["reason"]


def test_server_that_will_not_start_marks_live_unavailable(wav: Path) -> None:
    session = live.begin(wav, server_factory=lambda: FakeServer(fail_start=True), poll_s=0.01)
    _wait(lambda: session.status()["state"] == "unavailable")
    assert "no model" in session.status()["reason"]


def test_follow_replays_then_streams_without_duplicates(wav: Path) -> None:
    server = FakeServer()
    session = live.begin(wav, server_factory=lambda: server, poll_s=0.01)
    _grow(wav, SPEECH)
    _wait(lambda: len(_segments(wav)) == 1)

    events: list[dict] = []
    done = threading.Event()

    def consume() -> None:
        for ev in live.follow(wav, keepalive_s=0.05):
            if ev is not None:
                events.append(ev)
        done.set()

    t = threading.Thread(target=consume, daemon=True)
    t.start()
    _wait(lambda: any(e["type"] == "segment" for e in events))
    _grow(wav, SPEECH)
    _wait(lambda: sum(e["type"] == "segment" for e in events) == 2)

    with live.final_pass_server(wav, server_factory=lambda: FakeServer()) as reused:
        assert reused is server
    assert done.wait(5)

    seqs = [e["seq"] for e in events if e["type"] == "segment"]
    assert seqs == [1, 2]
    assert events[-1] == {"type": "end"}
    assert not server.running
    assert live.current() is None
    assert session.status()["state"] == "ended"


def test_follow_with_no_session_ends_immediately(wav: Path) -> None:
    assert list(live.follow(wav, keepalive_s=0.05)) == [{"type": "end"}]


def test_final_pass_server_starts_one_when_live_was_off(wav: Path) -> None:
    fresh = FakeServer()
    with live.final_pass_server(wav, server_factory=lambda: fresh) as server:
        assert server is fresh and fresh.running
    assert not fresh.running


def test_final_pass_server_yields_none_when_unavailable(wav: Path) -> None:
    with live.final_pass_server(wav, server_factory=lambda: FakeServer(fail_start=True)) as server:
        assert server is None


def test_final_pass_removes_the_live_file(wav: Path) -> None:
    server = FakeServer()
    live.begin(wav, server_factory=lambda: server, poll_s=0.01)
    _grow(wav, SPEECH)
    _wait(lambda: len(_segments(wav)) == 1)
    with live.final_pass_server(wav, server_factory=lambda: FakeServer()):
        pass
    assert not live.live_path(wav).exists()


def _config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, model: str, **rec) -> None:
    from ghostbrain.recorder import config as rcfg
    from ghostbrain.recorder import transcribe as tmod

    models = tmp_path / "models"
    models.mkdir(exist_ok=True)
    (models / model).write_bytes(b"x")
    monkeypatch.delenv("GHOSTBRAIN_WHISPER_MODEL", raising=False)
    monkeypatch.setattr(tmod, "DEFAULT_MODEL_DIR", models)
    monkeypatch.setattr(rcfg, "load_recorder_block", lambda: rec)


def test_begin_from_config_respects_the_toggle(wav: Path, tmp_path: Path, monkeypatch) -> None:
    _config(monkeypatch, tmp_path, "ggml-large-v3-turbo-q5_0.bin", live_transcription=False)
    assert live.begin_from_config(wav, server_factory=lambda _m: FakeServer()) is None


def test_begin_from_config_uses_the_configured_language(wav: Path, tmp_path: Path, monkeypatch) -> None:
    _config(monkeypatch, tmp_path, "ggml-large-v3-turbo-q5_0.bin", transcription_language="af")
    session = live.begin_from_config(wav, server_factory=lambda _m: FakeServer())
    assert session is not None
    assert session._language == "af"


def test_begin_from_config_forces_english_for_en_models(wav: Path, tmp_path: Path, monkeypatch) -> None:
    _config(monkeypatch, tmp_path, "ggml-small.en.bin", transcription_language="af")
    session = live.begin_from_config(wav, server_factory=lambda _m: FakeServer())
    assert session is not None
    assert session._language == "en"
