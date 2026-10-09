"""A warm ``whisper-server`` (whisper.cpp) for chunked transcription.

Live transcription posts a short chunk every few seconds; reloading a
~550 MB model per chunk with ``whisper-cli`` would cost a second or more and
spike memory each time. Instead one server is started per recording, keeps
the model resident, and is stopped after the final pass.

The pid is written to ``PID_FILE`` so a sidecar that crashed mid-meeting can
reap the leftover server on its next start (:func:`kill_orphan`).
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Self

import requests

from ghostbrain.paths import state_dir
from ghostbrain.recorder.chunker import pcm_to_wav
from ghostbrain.recorder.transcribe import _NOISE_TOKEN_RE

log = logging.getLogger("ghostbrain.recorder.whisper_server")

# None = ``<state_dir>/whisper-server.pid``, resolved per call so the
# GHOSTBRAIN_STATE_DIR in effect at the time wins (tests override it).
PID_FILE: Path | None = None
BINARY = "whisper-server"
# What a whisper-server's command line contains (orphan identity check).
_PROCESS_MARKER = "whisper-server"

# whisper.cpp reports the detected language by name.
_LANG_CODES = {"english": "en", "afrikaans": "af", "dutch": "nl"}


class WhisperServerError(RuntimeError):
    pass


@dataclass(frozen=True)
class Segment:
    """One transcribed span, timed on the recording's timeline (seconds)."""

    t0: float
    t1: float
    text: str
    lang: str

    def to_dict(self) -> dict:
        return {"t0": self.t0, "t1": self.t1, "text": self.text, "lang": self.lang}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class WhisperServer:
    def __init__(self, model: Path, *, binary: str | None = None, threads: int | None = None):
        self.model = model
        self._binary = binary
        self._threads = threads
        self._proc: subprocess.Popen | None = None
        self._port: int | None = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc) -> None:
        self.stop()

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc else None

    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self, *, timeout_s: float = 60.0) -> None:
        binary = self._binary or shutil.which(BINARY)
        if binary is None:
            raise WhisperServerError(
                "`whisper-server` not found on PATH. Install via `brew install whisper-cpp`."
            )
        self._port = _free_port()
        cmd = [
            binary,
            "-m", str(self.model),
            "--host", "127.0.0.1",
            "--port", str(self._port),
            "-l", "auto",
            # Same reason as transcribe.py: carried-over context causes
            # "Okay. Okay. Okay." loops.
            "-mc", "0",
        ]
        if self._threads:
            cmd += ["-t", str(self._threads)]
        log.info("starting whisper-server on :%d with %s", self._port, self.model.name)
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        _write_pid(self._proc.pid)

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                code = self._proc.returncode
                self.stop()
                raise WhisperServerError(f"whisper-server exited during startup (code {code})")
            try:
                if requests.get(self._url("/health"), timeout=1).status_code == 200:
                    return
            except requests.RequestException:
                pass
            time.sleep(0.2)
        self.stop()
        raise WhisperServerError(f"whisper-server not ready after {timeout_s:.0f}s")

    def transcribe(
        self, pcm: bytes, *, language: str = "auto", offset_s: float = 0.0,
        timeout_s: float = 120.0,
    ) -> list[Segment]:
        """Transcribe one chunk; segment times are shifted by ``offset_s``."""
        if not self.alive():
            raise WhisperServerError("whisper-server is not running")
        try:
            resp = requests.post(
                self._url("/inference"),
                files={"file": ("chunk.wav", pcm_to_wav(pcm), "audio/wav")},
                data={"response_format": "verbose_json", "language": language},
                timeout=timeout_s,
            )
            resp.raise_for_status()
            body = resp.json()
        except (requests.RequestException, ValueError) as e:
            raise WhisperServerError(f"inference failed: {e}") from e

        lang_name = str(body.get("language") or language).lower()
        lang = _LANG_CODES.get(lang_name, lang_name)
        out: list[Segment] = []
        for seg in body.get("segments") or []:
            text = str(seg.get("text") or "").strip()
            # Skip silence markers and punctuation-only fragments (" .").
            if not any(c.isalnum() for c in text) or _NOISE_TOKEN_RE.match(text):
                continue
            out.append(Segment(
                t0=round(offset_s + float(seg.get("start") or 0.0), 2),
                t1=round(offset_s + float(seg.get("end") or 0.0), 2),
                text=text,
                lang=lang,
            ))
        return out

    def stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        _clear_pid()

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self._port}{path}"


def _pid_file() -> Path:
    return PID_FILE or state_dir() / "whisper-server.pid"


def _write_pid(pid: int) -> None:
    path = _pid_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"pid": pid}), encoding="utf-8")
    except OSError as e:
        log.warning("could not write %s: %s", path, e)


def _clear_pid() -> None:
    try:
        _pid_file().unlink(missing_ok=True)
    except OSError:
        pass


def _is_whisper_server(pid: int) -> bool:
    """True when ``pid`` is alive AND is a whisper-server (pids get recycled)."""
    if sys.platform == "win32":
        cmd = ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"]
    else:
        cmd = ["ps", "-p", str(pid), "-o", "command="]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return _PROCESS_MARKER in out


def kill_orphan() -> bool:
    """Reap a whisper-server left behind by a crashed sidecar. Returns True
    if one was killed. Call once at sidecar start, before any recording."""
    try:
        pid = int(json.loads(_pid_file().read_text(encoding="utf-8"))["pid"])
    except (OSError, ValueError, KeyError, TypeError):
        _clear_pid()
        return False
    killed = False
    if _is_whisper_server(pid):
        try:
            os.kill(pid, signal.SIGTERM)
            killed = True
            log.info("killed orphan whisper-server pid=%d", pid)
        except OSError:
            pass
    _clear_pid()
    return killed
