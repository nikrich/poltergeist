"""WhisperServer: a warm whisper.cpp server for chunked transcription."""
from __future__ import annotations

import json
import os
import signal
import sys
import textwrap
from pathlib import Path

import pytest

from ghostbrain.recorder import chunker
from ghostbrain.recorder import whisper_server as ws

# 0.5 s of a loud square wave — anything but silence.
SPEECH = (b"\x00\x20" * 40 + b"\x00\xe0" * 40) * 100

# A stand-in for `whisper-server`: same flags, same /health and /inference
# contract, deterministic output. FAKE_MODE in the env switches failure modes.
FAKE_SERVER = textwrap.dedent(
    """
    #!{python}
    import json, os, sys
    from http.server import BaseHTTPRequestHandler, HTTPServer
    args = sys.argv[1:]
    port = int(args[args.index("--port") + 1])
    prefix = args[args.index("--request-path") + 1]
    mode = os.environ.get("FAKE_MODE", "ok")
    if mode == "exit":
        sys.exit(3)
    calls = {{"n": 0}}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            if self.path == prefix + "/health":
                if mode == "never_healthy":
                    self.send_response(503); self.end_headers(); return
                self.send_response(200); self.end_headers()
                self.wfile.write(b'{{"status":"ok"}}')
            else:
                self.send_response(404); self.end_headers()
        def do_POST(self):
            n = int(self.headers["Content-Length"])
            body = self.rfile.read(n)
            if self.path != prefix + "/inference":
                self.send_response(404); self.end_headers(); return
            calls["n"] += 1
            auto = b"name=\\"language\\"\\r\\n\\r\\nauto" in body
            forced = None
            for code, name in (("af", "afrikaans"), ("en", "english")):
                if b"name=\\"language\\"\\r\\n\\r\\n" + code.encode() in body:
                    forced = name
            detect = os.environ.get("FAKE_DETECT")
            if forced:
                lang = forced
            elif detect:
                lang = detect
            else:
                lang = "afrikaans" if auto and calls["n"] % 2 == 0 else "english"
            out = {{
                "language": lang,
                "segments": [
                    {{"start": 0.0, "end": 1.5, "text": " hello there"}},
                    {{"start": 1.5, "end": 2.0, "text": " [BLANK_AUDIO]"}},
                    {{"start": 2.0, "end": 2.1, "text": " ."}},
                ],
            }}
            data = json.dumps(out).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    HTTPServer(("127.0.0.1", port), H).serve_forever()
    """
).lstrip()


@pytest.fixture
def fake_binary(tmp_path: Path) -> Path:
    path = tmp_path / "whisper-server"
    path.write_text(FAKE_SERVER.format(python=sys.executable))
    path.chmod(0o755)
    return path


@pytest.fixture
def model(tmp_path: Path) -> Path:
    path = tmp_path / "ggml-large-v3-turbo-q5_0.bin"
    path.write_bytes(b"x")
    return path


@pytest.fixture
def pid_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "state" / "whisper-server.pid"
    monkeypatch.setattr(ws, "PID_FILE", path)
    return path


def test_start_transcribe_stop(fake_binary: Path, model: Path, pid_file: Path) -> None:
    server = ws.WhisperServer(model, binary=str(fake_binary))
    server.start(timeout_s=10)
    try:
        assert pid_file.exists()
        segments = server.transcribe(SPEECH, language="auto", offset_s=10.0)
    finally:
        server.stop()
    # Noise markers are dropped; times are shifted onto the recording timeline.
    assert segments == [ws.Segment(t0=10.0, t1=11.5, text="hello there", lang="en")]
    assert not pid_file.exists()


def test_language_names_map_to_codes(fake_binary: Path, model: Path, pid_file: Path) -> None:
    with ws.WhisperServer(model, binary=str(fake_binary)) as server:
        server.start(timeout_s=10)
        langs = [server.transcribe(SPEECH)[0].lang for _ in range(2)]
    assert langs == ["en", "af"]


def test_start_fails_cleanly_when_the_process_exits(
    fake_binary: Path, model: Path, pid_file: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_MODE", "exit")
    server = ws.WhisperServer(model, binary=str(fake_binary))
    with pytest.raises(ws.WhisperServerError, match="exited"):
        server.start(timeout_s=5)
    assert not pid_file.exists()


def test_start_times_out_when_never_healthy(
    fake_binary: Path, model: Path, pid_file: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_MODE", "never_healthy")
    server = ws.WhisperServer(model, binary=str(fake_binary))
    with pytest.raises(ws.WhisperServerError, match="not ready"):
        server.start(timeout_s=1.5)
    assert not server.alive()
    assert not pid_file.exists()


def test_missing_binary(model: Path, pid_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ws.shutil, "which", lambda _name: None)
    with pytest.raises(ws.WhisperServerError, match="whisper-server"):
        ws.WhisperServer(model).start()


def test_transcribe_after_crash_raises(fake_binary: Path, model: Path, pid_file: Path) -> None:
    server = ws.WhisperServer(model, binary=str(fake_binary))
    server.start(timeout_s=10)
    assert server.pid is not None
    os.kill(server.pid, signal.SIGKILL)
    server._proc.wait(timeout=5)
    with pytest.raises(ws.WhisperServerError):
        server.transcribe(SPEECH)
    server.stop()


def test_kill_orphan_reaps_a_leftover_server(fake_binary: Path, model: Path, pid_file: Path) -> None:
    server = ws.WhisperServer(model, binary=str(fake_binary))
    server.start(timeout_s=10)
    proc = server._proc
    try:
        # Simulate a sidecar crash: the object is gone but the pid file remains.
        assert ws.kill_orphan() is True
        proc.wait(timeout=5)
        assert not pid_file.exists()
    finally:
        server.stop()  # never leak the fake server if an assert fails


def test_kill_orphan_ignores_a_recycled_pid(pid_file: Path) -> None:
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    # Our own pid is alive but is not a whisper-server.
    pid_file.write_text(json.dumps({"pid": os.getpid()}))
    assert ws.kill_orphan() is False
    assert not pid_file.exists()


def test_routes_sit_behind_a_random_secret_prefix(fake_binary: Path, model: Path, pid_file: Path) -> None:
    import requests

    with ws.WhisperServer(model, binary=str(fake_binary)) as server:
        server.start(timeout_s=10)
        other = ws.WhisperServer(model, binary=str(fake_binary))
        assert server._prefix != other._prefix
        assert len(server._prefix) > 16
        # Another local process that found the port still gets nothing.
        bare = f"http://127.0.0.1:{server._port}"
        assert requests.get(bare + "/health", timeout=5).status_code == 404
        assert requests.post(bare + "/inference", data=b"x", timeout=5).status_code == 404
        assert server.transcribe(SPEECH)


def test_auto_outside_allowed_languages_is_retried(
    fake_binary: Path, model: Path, pid_file: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Whisper often hears Afrikaans as Dutch: with en/af allowed, a "dutch"
    # detection is re-decoded as Afrikaans.
    monkeypatch.setenv("FAKE_DETECT", "dutch")
    with ws.WhisperServer(model, binary=str(fake_binary)) as server:
        server.start(timeout_s=10)
        segs = server.transcribe(SPEECH, allowed=("en", "af"))
        assert [s.lang for s in segs] == ["af"]
        # Without a restriction the detection stands.
        assert server.transcribe(SPEECH)[0].lang == "nl"


def test_silence_is_never_sent_to_the_server(fake_binary: Path, model: Path, pid_file: Path) -> None:
    # Whisper hallucinates "Thank you." on silence; skip it entirely.
    with ws.WhisperServer(model, binary=str(fake_binary)) as server:
        server.start(timeout_s=10)
        server._port = 9  # any request would now fail loudly
        assert server.transcribe(b"\x00\x00" * chunker.SAMPLE_RATE) == []
