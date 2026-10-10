"""The sidecar shuts down when its parent (the Electron app) goes away.

Unit tests drive ``parent_watch`` with a pipe standing in for stdin; the
subprocess tests run the real ``python -m ghostbrain.api`` in a sandbox
(HOME / USERPROFILE / GHOSTBRAIN_STATE_DIR / VAULT_PATH under tmp_path,
scheduler off) and always kill every process they started.
"""
from __future__ import annotations

import json
import os
import select
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from ghostbrain.api import parent_watch

REPO_ROOT = Path(__file__).resolve().parents[3]

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals / ppid")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _sandbox_env(tmp_path: Path, **extra: str) -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("GHOSTBRAIN_") and k != "VAULT_PATH"
    }
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env.update(
        HOME=str(home),
        USERPROFILE=str(home),
        GHOSTBRAIN_STATE_DIR=str(tmp_path / "state"),
        VAULT_PATH=str(tmp_path / "vault"),
        GHOSTBRAIN_SCHEDULER_ENABLED="0",
        GHOSTBRAIN_ACCOUNTS_LIVE_SEED="0",
    )
    env.update(extra)
    return env


def _readline(stream, timeout: float) -> str:
    ready, _, _ = select.select([stream], [], [], timeout)
    if not ready:
        raise AssertionError(f"no output within {timeout}s")
    return stream.readline()


def _parse_banner(line: str) -> dict[str, str]:
    assert line.startswith("READY "), line
    return dict(part.split("=", 1) for part in line.split()[1:])


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _wait_dead(pid: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.1)
    return False


def _wait_listening(port: int, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), 0.2).close()
            return
        except OSError:
            time.sleep(0.1)
    raise AssertionError(f"port {port} never accepted connections")


def _kill(pid: int | None) -> None:
    if pid is not None and _alive(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


# Stand-in for the Electron main process: spawns the sidecar with a stdin
# pipe only it holds, forwards READY + the sidecar pid, then idles.
_PARENT = """
import subprocess, sys, time
child = subprocess.Popen(
    [sys.executable, "-m", "ghostbrain.api"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=open(sys.argv[1], "w"), text=True,
)
print(f"PID {child.pid} {child.stdout.readline().strip()}", flush=True)
while True:
    time.sleep(60)
"""


# ---------------------------------------------------------------------------
# parent_watch unit tests
# ---------------------------------------------------------------------------


def _pipe_stdin(monkeypatch: pytest.MonkeyPatch) -> int:
    """Replace sys.stdin with the read end of a fresh pipe; return the write fd."""
    r, w = os.pipe()
    monkeypatch.setattr(sys, "stdin", os.fdopen(r, "rb", buffering=0))
    return w


def test_start_returns_none_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(parent_watch.ENV_VAR, raising=False)
    assert parent_watch.start(lambda: None) is None


def test_stdin_eof_fires_callback_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(parent_watch.ENV_VAR, "1")
    w = _pipe_stdin(monkeypatch)
    calls: list[int] = []
    fired = threading.Event()

    def on_gone() -> None:
        calls.append(1)
        fired.set()

    thread = parent_watch.start(on_gone, poll_s=0.05)
    assert thread is not None and thread.daemon
    os.write(w, b"ignored input\n")
    time.sleep(0.2)
    assert calls == []  # data on stdin is not EOF
    os.close(w)
    assert fired.wait(5)
    thread.join(5)
    assert not thread.is_alive()
    assert calls == [1]


@posix_only
def test_ppid_change_fires_callback_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(parent_watch.ENV_VAR, "1")
    w = _pipe_stdin(monkeypatch)  # stdin stays open: only the ppid changes
    real_ppid = os.getppid()
    ppid = [real_ppid]
    monkeypatch.setattr(parent_watch.os, "getppid", lambda: ppid[0])
    calls: list[int] = []
    try:
        thread = parent_watch.start(lambda: calls.append(1), poll_s=0.05)
        assert thread is not None
        time.sleep(0.3)
        assert calls == []
        ppid[0] = 1  # reparented to init/launchd
        thread.join(5)
        assert not thread.is_alive()
        assert calls == [1]
    finally:
        os.close(w)
    # Closing the pipe lets the stdin reader hit EOF and finish too.
    readers = [t for t in threading.enumerate() if t.name == "parent-watch-stdin"]
    for t in readers:
        t.join(5)
    assert not any(t.is_alive() for t in readers)
    assert calls == [1]


def test_parent_gone_handler_stops_recording_then_exits_gracefully() -> None:
    from ghostbrain.api import __main__ as sidecar_main

    class FakeServer:
        should_exit = False

    server = FakeServer()
    exits: list[int] = []
    exited = threading.Event()
    should_exit_when_stopping: list[bool] = []

    def fake_exit(code: int) -> None:
        exits.append(code)
        exited.set()

    def fake_stop_recording() -> bool:
        should_exit_when_stopping.append(server.should_exit)
        return True

    handler = sidecar_main._parent_gone_handler(
        server, hard_exit_after_s=0.3, hard_exit=fake_exit,
        stop_recording=fake_stop_recording,
    )
    handler()
    # The recording is stopped while the server is still up, before uvicorn
    # is asked to exit.
    assert should_exit_when_stopping == [False]
    # Graceful next: uvicorn's main loop sees should_exit and runs the
    # shutdown hooks (scheduler stop, chat reaping, live.stop_all).
    assert server.should_exit is True
    assert exits == []
    # The last-resort exit only fires if the graceful path never finishes.
    assert exited.wait(5)
    assert exits == [1]


def test_parent_gone_handler_still_exits_if_stopping_the_recording_raises() -> None:
    from ghostbrain.api import __main__ as sidecar_main

    class FakeServer:
        should_exit = False

    server = FakeServer()

    def boom() -> bool:
        raise RuntimeError("backend exploded")

    handler = sidecar_main._parent_gone_handler(
        server, hard_exit_after_s=0.01, hard_exit=lambda code: None, stop_recording=boom,
    )
    with pytest.raises(RuntimeError):
        handler()
    assert server.should_exit is True


def test_hard_exit_outlasts_capture_stop_and_graceful_budget() -> None:
    from ghostbrain.api import __main__ as sidecar_main
    from ghostbrain.recorder.audio import darwin_native

    # stop_capture: SIGINT, wait STOP_GRACE_S, then SIGTERM + 1s. The parent-
    # gone path may wait out one in-flight /stop on the lock, then run its
    # own, after a capture probe; then the graceful shutdown, scheduler.stop
    # (10 s) and WhisperServer.stop (5 s + 5 s).
    capture_stop_s = darwin_native.STOP_GRACE_S + 1.0
    budget = (
        2 * capture_stop_s + darwin_native.PROBE_TIMEOUT_S
        + sidecar_main.GRACEFUL_SHUTDOWN_TIMEOUT_S + 10 + 10
    )
    assert sidecar_main.PARENT_GONE_HARD_EXIT_S > budget
    assert sidecar_main._uvicorn_kwargs(object(), 1)["timeout_graceful_shutdown"] == (
        sidecar_main.GRACEFUL_SHUTDOWN_TIMEOUT_S
    )


def test_serve_exits_3_when_uvicorn_never_started() -> None:
    # uvicorn.run() exits STARTUP_FAILURE (3) when startup fails (port taken,
    # lifespan error); server.run() just returns, so _serve must report it.
    from ghostbrain.api import __main__ as sidecar_main

    class FakeServer:
        def __init__(self, started: bool) -> None:
            self._started = started
            self.started = False

        def run(self) -> None:
            self.started = self._started

    assert sidecar_main._serve(FakeServer(started=False)) == 3
    assert sidecar_main._serve(FakeServer(started=True)) == 0


# ---------------------------------------------------------------------------
# real sidecar subprocess tests
# ---------------------------------------------------------------------------


@posix_only
def test_sidecar_exits_gracefully_when_parent_is_killed(tmp_path: Path) -> None:
    stderr_log = tmp_path / "sidecar.stderr"
    parent = subprocess.Popen(
        [sys.executable, "-c", _PARENT, str(stderr_log)],
        cwd=REPO_ROOT,
        env=_sandbox_env(tmp_path, GHOSTBRAIN_PARENT_WATCH="1"),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        text=True,
    )
    child_pid: int | None = None
    try:
        line = _readline(parent.stdout, 90)
        assert line.startswith("PID "), line
        _, pid_s, banner = line.strip().split(" ", 2)
        child_pid = int(pid_s)
        _wait_listening(int(_parse_banner(banner)["port"]))
        # The descriptor lands in the sandboxed HOME, never the real one.
        assert (tmp_path / "home" / "ghostbrain" / "run" / "sidecar.json").exists()

        parent.kill()
        parent.wait(10)

        assert _wait_dead(child_pid, 15), "sidecar outlived its parent"
        log = stderr_log.read_text(encoding="utf-8")
        assert "parent process gone" in log
        # Went through uvicorn's graceful path: the shutdown hooks ran.
        assert "Application shutdown complete." in log
        assert "last-resort" not in log
    finally:
        _kill(child_pid)
        if parent.poll() is None:
            parent.kill()
            parent.wait()


@posix_only
def test_sidecar_without_parent_watch_keeps_running(tmp_path: Path) -> None:
    # A terminal-launched sidecar (no env var, stdin /dev/null) must not
    # mistake the immediate stdin EOF for a dead parent.
    proc = subprocess.Popen(
        [sys.executable, "-m", "ghostbrain.api"],
        cwd=REPO_ROOT,
        env=_sandbox_env(tmp_path),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        _parse_banner(_readline(proc.stdout, 90))
        time.sleep(4)
        assert proc.poll() is None
    finally:
        proc.kill()
        proc.wait()


_FAKE_CAPTURE = """
import struct, sys, time
f = open(sys.argv[1], "wb")
f.write(b"RIFF" + struct.pack("<I", 0xFFFFFFFF) + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16)
        + b"data" + struct.pack("<I", 0xFFFFFFFF))
while True:
    f.write(b"\\0" * 3200)
    f.flush()
    time.sleep(0.1)
"""


@pytest.mark.skipif(sys.platform != "darwin", reason="needs a supported audio backend")
def test_sigterm_exits_despite_open_recording_stream(tmp_path: Path) -> None:
    """Root cause of the 'ignored SIGTERM': during a recording the app holds
    /v1/recorder/levels (and /live) open, and uvicorn without
    timeout_graceful_shutdown waits for those streams forever."""
    env = _sandbox_env(tmp_path)
    recordings = tmp_path / "home" / "ghostbrain" / "recorder" / "recordings"
    recordings.mkdir(parents=True)
    wav = recordings / "fake-manual.wav"
    capture = subprocess.Popen(
        [sys.executable, "-c", _FAKE_CAPTURE, str(wav)], start_new_session=True,
    )
    proc: subprocess.Popen | None = None
    stderr_log = tmp_path / "sidecar.stderr"
    try:
        (recordings.parent / "manual.state").write_text(json.dumps({
            "phase": "recording", "pid": capture.pid, "wavPath": str(wav),
            "startedAt": "2026-10-09T10:00:00Z",
        }))
        with open(stderr_log, "w") as err:
            proc = subprocess.Popen(
                [sys.executable, "-m", "ghostbrain.api"],
                cwd=REPO_ROOT, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=err, text=True,
            )
        banner = _parse_banner(_readline(proc.stdout, 90))
        _wait_listening(int(banner["port"]))

        chunks: list[int] = []
        opened = threading.Event()

        def stream() -> None:
            req = urllib.request.Request(
                f"http://127.0.0.1:{banner['port']}/v1/recorder/levels",
                headers={"Authorization": f"Bearer {banner['token']}"},
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    while True:
                        data = r.read1(256)
                        if not data:
                            return
                        chunks.append(len(data))
                        opened.set()
            except Exception:  # noqa: BLE001 — the server going away ends it
                return

        threading.Thread(target=stream, daemon=True).start()
        assert opened.wait(30), "levels stream never produced data"

        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=20)  # TimeoutExpired == the original bug
        assert "Application shutdown complete." in stderr_log.read_text(encoding="utf-8")
        # A plain SIGTERM is a normal app quit: the app is still alive and
        # the recording keeps going for next-start recovery. Only the
        # parent-gone path stops capture (see the test below).
        assert capture.poll() is None
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait()
        capture.kill()
        capture.wait()


# Fake capture that records how it was stopped: SIGINT (the clean stop that
# lets the real helper finalize its WAV) writes a marker and exits.
_SIGINT_CAPTURE = """
import signal, struct, sys, time
marker = sys.argv[2]

def on_sigint(signum, frame):
    open(marker, "w").write("SIGINT")
    sys.exit(0)

signal.signal(signal.SIGINT, on_sigint)
f = open(sys.argv[1], "wb")
f.write(b"RIFF" + struct.pack("<I", 0xFFFFFFFF) + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16)
        + b"data" + struct.pack("<I", 0xFFFFFFFF))
while True:
    f.write(b"\\0" * 3200)
    f.flush()
    time.sleep(0.1)
"""


@pytest.mark.skipif(sys.platform != "darwin", reason="needs a supported POSIX audio backend")
def test_parent_death_mid_recording_sigints_capture_and_leaves_it_recoverable(
    tmp_path: Path,
) -> None:
    recordings = tmp_path / "home" / "ghostbrain" / "recorder" / "recordings"
    recordings.mkdir(parents=True)
    wav = recordings / "meeting-20261009-100000-manual.wav"
    marker = tmp_path / "capture-stopped-by"
    state_file = recordings.parent / "manual.state"
    capture = subprocess.Popen(
        [sys.executable, "-c", _SIGINT_CAPTURE, str(wav), str(marker)],
        start_new_session=True,
    )
    stderr_log = tmp_path / "sidecar.stderr"
    parent: subprocess.Popen | None = None
    child_pid: int | None = None
    try:
        state_file.write_text(json.dumps({
            "phase": "recording", "pid": capture.pid, "wavPath": str(wav),
            "startedAt": "2026-10-09T10:00:00Z",
        }))
        parent = subprocess.Popen(
            [sys.executable, "-c", _PARENT, str(stderr_log)],
            cwd=REPO_ROOT,
            env=_sandbox_env(tmp_path, GHOSTBRAIN_PARENT_WATCH="1"),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            text=True,
        )
        line = _readline(parent.stdout, 90)
        assert line.startswith("PID "), line
        _, pid_s, banner = line.strip().split(" ", 2)
        child_pid = int(pid_s)
        _wait_listening(int(_parse_banner(banner)["port"]))

        parent.kill()
        parent.wait(10)

        assert _wait_dead(child_pid, 30), "sidecar outlived its parent"
        capture.wait(timeout=5)
        assert marker.read_text() == "SIGINT"
        state = json.loads(state_file.read_text())
        assert state["phase"] == "transcribing"
        assert state["wavPath"] == str(wav)
        log = stderr_log.read_text(encoding="utf-8")
        assert "stopped the recording in progress" in log
        assert "Application shutdown complete." in log
        assert "last-resort" not in log
    finally:
        _kill(child_pid)
        if parent is not None and parent.poll() is None:
            parent.kill()
            parent.wait()
        if capture.poll() is None:
            capture.kill()
        capture.wait()
