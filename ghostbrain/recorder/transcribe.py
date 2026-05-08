"""Wrap whisper-cli (whisper.cpp) to transcribe a WAV file."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger("ghostbrain.recorder.transcribe")

DEFAULT_MODEL_DIR = Path.home() / "ghostbrain" / "recorder" / "models"
DEFAULT_MODEL = "ggml-medium.en.bin"
DEFAULT_TIMEOUT_S = 30 * 60  # 30 min for a long meeting; whisper is fast on Apple Silicon


class TranscribeError(RuntimeError):
    pass


def transcribe(
    wav_path: Path,
    *,
    model_path: Path | None = None,
    threads: int | None = None,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> Path:
    """Run whisper-cli on a WAV file and return the path to the .txt output.

    The .txt lands next to the .wav (whisper-cli's default output naming).
    """
    binary = shutil.which("whisper-cli")
    if binary is None:
        raise TranscribeError(
            "`whisper-cli` not found on PATH. Install via `brew install whisper-cpp`."
        )

    if not wav_path.exists():
        raise TranscribeError(f"WAV not found: {wav_path}")

    model = _resolve_model(model_path)
    output_base = wav_path.with_suffix("")  # whisper-cli appends .txt itself

    cmd = [
        binary,
        "-m", str(model),
        "-f", str(wav_path),
        "-otxt",
        "-of", str(output_base),
        "-l", "en",
    ]
    if threads:
        cmd.extend(["-t", str(threads)])

    log.info("transcribing %s with %s", wav_path.name, model.name)
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as e:
        raise TranscribeError(f"whisper-cli timed out after {timeout_s}s") from e
    if proc.returncode != 0:
        raise TranscribeError(
            f"whisper-cli exited {proc.returncode}: "
            f"{(proc.stderr or '').strip()[:300]}"
        )

    txt_path = output_base.with_suffix(".txt")
    if not txt_path.exists():
        raise TranscribeError(f"whisper-cli ran but no .txt at {txt_path}")
    return txt_path


def _resolve_model(model_path: Path | None) -> Path:
    if model_path is not None:
        if not model_path.exists():
            raise TranscribeError(f"model not found at {model_path}")
        return model_path

    env_path = os.environ.get("GHOSTBRAIN_WHISPER_MODEL")
    if env_path:
        p = Path(env_path).expanduser()
        if p.exists():
            return p
        raise TranscribeError(f"GHOSTBRAIN_WHISPER_MODEL set but {p} missing")

    default = DEFAULT_MODEL_DIR / DEFAULT_MODEL
    if default.exists():
        return default
    raise TranscribeError(
        f"No whisper model found. Drop a ggml-*.bin file at "
        f"{DEFAULT_MODEL_DIR}/ or set GHOSTBRAIN_WHISPER_MODEL."
    )
