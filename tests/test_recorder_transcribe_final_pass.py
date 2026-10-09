"""Final pass: chunked, per-chunk language detection via the warm server,
with whisper-cli as the fallback."""
from __future__ import annotations

import math
import struct
from pathlib import Path

import pytest

from ghostbrain.recorder import chunker, live
from ghostbrain.recorder import transcribe as tmod
from ghostbrain.recorder.whisper_server import Segment, WhisperServerError

SR = chunker.SAMPLE_RATE


class FakeServer:
    def __init__(self, *, fail_on: int | None = None, fail_start: bool = False):
        self.fail_on = fail_on
        self.fail_start = fail_start
        self.calls = 0
        self.languages: list[str] = []
        self.spans: list[tuple[float, float]] = []
        self.running = False

    def start(self, timeout_s: float = 60.0) -> None:
        if self.fail_start:
            raise WhisperServerError("no whisper-server")
        self.running = True

    def alive(self) -> bool:
        return self.running

    def stop(self) -> None:
        self.running = False

    def transcribe(
        self, pcm: bytes, *, language: str = "auto", offset_s: float = 0.0,
        allowed: tuple[str, ...] | None = None,
    ):
        self.calls += 1
        self.languages.append(language)
        self.spans.append((round(offset_s, 2), round(offset_s + len(pcm) / 2 / SR, 2)))
        if self.calls == self.fail_on:
            raise WhisperServerError("crashed")
        lang = "af" if self.calls % 2 == 0 else "en"
        return [Segment(t0=offset_s, t1=offset_s + 1, text=f"part {self.calls}", lang=lang)]


@pytest.fixture
def model_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "models"
    d.mkdir()
    monkeypatch.delenv("GHOSTBRAIN_WHISPER_MODEL", raising=False)
    monkeypatch.setattr(tmod, "DEFAULT_MODEL_DIR", d)
    monkeypatch.setattr(tmod, "_configured_language", lambda: "auto")
    monkeypatch.setattr(tmod.shutil, "which", lambda name: f"/bin/{name}")
    return d


@pytest.fixture(autouse=True)
def _no_sessions():
    yield
    live.stop_all()


def _wav(tmp_path: Path, seconds: float = 40.0) -> Path:
    one = b"".join(
        struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / SR))) for i in range(SR)
    )
    pcm = one * int(seconds)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(pcm), b"WAVE", b"fmt ", 16, 1, 1,
        SR, SR * 2, 2, 16, b"data", len(pcm),
    )
    wav = tmp_path / "meeting.wav"
    wav.write_bytes(header + pcm)
    return wav


def _fake_cli(monkeypatch: pytest.MonkeyPatch, text: str = "whole file\n") -> list[list[str]]:
    calls: list[list[str]] = []

    class Proc:
        returncode = 0
        stderr = ""

    def run(cmd, **_kw):
        calls.append(cmd)
        Path(cmd[cmd.index("-of") + 1] + ".txt").write_text(text)
        return Proc()

    monkeypatch.setattr(tmod.subprocess, "run", run)
    return calls


def test_chunked_pass_writes_one_line_per_segment(tmp_path: Path, model_dir: Path) -> None:
    (model_dir / tmod.DEFAULT_MODEL).write_bytes(b"x")
    server = FakeServer()
    txt = tmod.transcribe(_wav(tmp_path), server_factory=lambda: server)
    lines = txt.read_text().splitlines()
    assert lines == [f"part {i}" for i in range(1, server.calls + 1)]
    assert server.calls >= 2  # 40s of audio in ≤30s chunks
    assert set(server.languages) == {"auto"}
    assert not server.running


def test_fixed_language_reaches_the_server(tmp_path: Path, model_dir: Path) -> None:
    (model_dir / tmod.DEFAULT_MODEL).write_bytes(b"x")
    server = FakeServer()
    tmod.transcribe(_wav(tmp_path), language="af", server_factory=lambda: server)
    assert set(server.languages) == {"af"}


def test_english_only_model_forces_english(tmp_path: Path, model_dir: Path, monkeypatch) -> None:
    (model_dir / "ggml-small.en.bin").write_bytes(b"x")
    server = FakeServer()
    tmod.transcribe(_wav(tmp_path), language="af", server_factory=lambda: server)
    assert set(server.languages) == {"en"}


def test_falls_back_to_whisper_cli_without_a_server(tmp_path: Path, model_dir: Path, monkeypatch) -> None:
    (model_dir / tmod.DEFAULT_MODEL).write_bytes(b"x")
    calls = _fake_cli(monkeypatch)
    txt = tmod.transcribe(_wav(tmp_path), server_factory=lambda: FakeServer(fail_start=True))
    assert txt.read_text() == "whole file\n"
    assert calls[0][calls[0].index("-l") + 1] == "auto"


def test_falls_back_to_whisper_cli_when_the_server_dies_mid_pass(
    tmp_path: Path, model_dir: Path, monkeypatch,
) -> None:
    (model_dir / tmod.DEFAULT_MODEL).write_bytes(b"x")
    calls = _fake_cli(monkeypatch)
    txt = tmod.transcribe(_wav(tmp_path), server_factory=lambda: FakeServer(fail_on=2))
    assert txt.read_text() == "whole file\n"
    assert len(calls) == 1


def test_whisper_cmd_takes_the_language() -> None:
    cmd = tmod._whisper_cmd("/bin/w", Path("/m.bin"), Path("/w.wav"), Path("/w"), language="af")
    assert cmd[cmd.index("-l") + 1] == "af"


@pytest.mark.parametrize(
    ("name", "expected"),
    [("ggml-large-v3-turbo-q5_0.bin", True), ("ggml-medium.en.bin", False), ("ggml-small.en.bin", False)],
)
def test_is_multilingual(name: str, expected: bool) -> None:
    assert tmod.is_multilingual(Path(name)) is expected


def _seed_live_chunks(wav: Path, chunks: list[tuple[float, float, str | None]]) -> None:
    import json

    with live.live_path(wav).open("w") as f:
        for start, end, lang in chunks:
            f.write(json.dumps({
                "type": "chunk", "start": int(start * SR), "end": int(end * SR), "lang": lang,
            }) + "\n")


def test_final_pass_follows_live_language_runs(tmp_path: Path, model_dir: Path) -> None:
    (model_dir / tmod.DEFAULT_MODEL).write_bytes(b"x")
    wav = _wav(tmp_path, seconds=40)
    # Live heard English, then Afrikaans; a silent chunk inherits its run.
    _seed_live_chunks(wav, [(0, 6, "en"), (6, 10, None), (10, 16, "af"), (16, 20, "af")])
    server = FakeServer()
    tmod.transcribe(wav, server_factory=lambda: server)

    for (t0, t1), lang in zip(server.spans, server.languages, strict=True):
        if t1 <= 10:
            assert lang == "en"
        elif t0 >= 10 and t1 <= 20:
            assert lang == "af"
        else:
            # Audio live never covered: short chunks, auto-detected.
            assert t0 >= 20
            assert lang == "auto"
            assert t1 - t0 <= chunker.LIVE.max_s
    # Chunks never straddle a language switch.
    assert all(not (t0 < 10 < t1) and not (t0 < 20 < t1) for t0, t1 in server.spans)
    assert server.spans[-1][1] == 40


def test_without_live_data_the_final_pass_uses_short_auto_chunks(tmp_path: Path, model_dir: Path) -> None:
    (model_dir / tmod.DEFAULT_MODEL).write_bytes(b"x")
    server = FakeServer()
    tmod.transcribe(_wav(tmp_path, seconds=30), server_factory=lambda: server)
    assert set(server.languages) == {"auto"}
    assert all(t1 - t0 <= chunker.LIVE.max_s for t0, t1 in server.spans)


def test_a_fixed_language_ignores_live_runs(tmp_path: Path, model_dir: Path) -> None:
    (model_dir / tmod.DEFAULT_MODEL).write_bytes(b"x")
    wav = _wav(tmp_path, seconds=40)
    _seed_live_chunks(wav, [(0, 10, "en"), (10, 20, "af")])
    server = FakeServer()
    tmod.transcribe(wav, language="en", server_factory=lambda: server)
    assert set(server.languages) == {"en"}
    assert max(t1 - t0 for t0, t1 in server.spans) > chunker.LIVE.max_s  # long chunks


def test_final_pass_removes_a_leftover_live_file(tmp_path: Path, model_dir: Path) -> None:
    # A session owned by a sidecar that has since exited leaves live.jsonl behind.
    (model_dir / tmod.DEFAULT_MODEL).write_bytes(b"x")
    wav = _wav(tmp_path, seconds=20)
    _seed_live_chunks(wav, [(0, 10, "en")])
    tmod.transcribe(wav, server_factory=lambda: FakeServer())
    assert not live.live_path(wav).exists()
