"""Voice-note transcripts via the local whisper pipeline, cached per stanza id.

WhatsApp stores voice notes as .opus; whisper wants 16 kHz mono WAV, so each
note goes through ffmpeg first. Transcripts are cached so rebuilding a day
never re-transcribes; failures retry on later runs up to MAX_ATTEMPTS.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from ghostbrain.connectors.whatsapp.store import Message

log = logging.getLogger("ghostbrain.connectors.whatsapp.voice")

NOT_DOWNLOADED = "[voice note — not downloaded]"
PENDING = "[voice note — transcription pending]"
FAILED = "[voice note — transcription failed]"
MAX_ATTEMPTS = 3
TRANSCRIBE_TIMEOUT_S = 300


def _ffmpeg_binary() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    # The packaged sidecar's PATH often lacks Homebrew.
    for p in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if Path(p).exists():
            return p
    return None


def _ffmpeg_to_wav(src: Path, dst: Path) -> None:
    binary = _ffmpeg_binary()
    if binary is None:
        raise FileNotFoundError("ffmpeg not found")
    subprocess.run(
        [binary, "-nostdin", "-loglevel", "error", "-y", "-i", str(src),
         "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(dst)],
        check=True, timeout=120, capture_output=True,
    )


def _whisper(wav: Path, *, timeout_s: int) -> Path:
    from ghostbrain.recorder.transcribe import transcribe

    return transcribe(wav, timeout_s=timeout_s)


def _recording_live() -> bool:
    from ghostbrain.recorder import live

    return live.current() is not None


def _key(stanza_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", stanza_id)


def _voice(text: str) -> str:
    return f"🎙 {text}" if text else "🎙 (no speech)"


class VoiceTranscriber:
    def __init__(self, cache_dir: Path, *, budget: int,
                 transcribe: Callable[..., Path] | None = None,
                 to_wav: Callable[[Path, Path], None] | None = None,
                 recording_live: Callable[[], bool] | None = None) -> None:
        self.cache_dir = cache_dir
        self.budget = budget
        self._transcribe = transcribe or _whisper
        self._to_wav = to_wav or _ffmpeg_to_wav
        self._recording_live = recording_live or _recording_live

    def line_for(self, msg: Message) -> tuple[str, bool]:
        if msg.media_path is None or not msg.media_path.exists():
            return NOT_DOWNLOADED, False
        key = _key(msg.stanza_id)
        cached = self.cache_dir / f"{key}.txt"
        if cached.exists():
            return _voice(cached.read_text(encoding="utf-8").strip()), False
        failed = self.cache_dir / f"{key}.failed"
        attempts = int(failed.read_text() or 0) if failed.exists() else 0
        if attempts >= MAX_ATTEMPTS:
            return FAILED, False
        # Never compete with a live meeting recording for whisper/CPU.
        if self.budget <= 0 or self._recording_live():
            return PENDING, True
        self.budget -= 1
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            text = self._run(msg.media_path)
        except Exception as e:  # noqa: BLE001 — a voice note must never block the day note
            attempts += 1
            log.warning("voice transcription failed (attempt %d) for %s: %s", attempts, key, e)
            failed.write_text(str(attempts))
            return (FAILED, False) if attempts >= MAX_ATTEMPTS else (PENDING, True)
        cached.write_text(text, encoding="utf-8")
        failed.unlink(missing_ok=True)
        return _voice(text), False

    def _run(self, src: Path) -> str:
        with tempfile.TemporaryDirectory(prefix="gb-wa-voice-") as d:
            wav = Path(d) / "voice.wav"
            self._to_wav(src, wav)
            txt = self._transcribe(wav, timeout_s=TRANSCRIBE_TIMEOUT_S)
            return txt.read_text(encoding="utf-8").strip()
