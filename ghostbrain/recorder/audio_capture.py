"""ffmpeg subprocess wrapper for meeting audio capture.

Captures BlackHole 2ch (system audio) + the default Mac microphone,
mixes them, writes 16-kHz mono WAV that whisper.cpp likes.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("ghostbrain.recorder.audio_capture")


@dataclass
class CaptureHandle:
    pid: int
    wav_path: Path


def list_avfoundation_inputs() -> dict[str, int]:
    """Return ``{device_name: index}`` for current avfoundation audio inputs."""
    binary = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    proc = subprocess.run(
        [binary, "-f", "avfoundation", "-list_devices", "true", "-i", ""],
        capture_output=True, text=True, timeout=10,
    )
    out = (proc.stderr or "") + (proc.stdout or "")

    devices: dict[str, int] = {}
    in_audio_section = False
    for line in out.splitlines():
        if "AVFoundation audio devices" in line:
            in_audio_section = True
            continue
        if in_audio_section and "AVFoundation video devices" in line:
            break
        m = re.match(r".*\[(\d+)\]\s+(.+)\s*$", line)
        if m and in_audio_section:
            devices[m.group(2).strip()] = int(m.group(1))
    return devices


def find_indexes() -> tuple[int, int]:
    """Return ``(blackhole_index, mic_index)`` discovered from avfoundation.

    BlackHole is the system-audio capture device; mic falls back to
    MacBook Pro Microphone if present, else the first non-BlackHole input.
    """
    devices = list_avfoundation_inputs()
    blackhole_idx = next(
        (i for n, i in devices.items() if "blackhole" in n.lower()),
        None,
    )
    if blackhole_idx is None:
        raise RuntimeError(
            "BlackHole audio device not found. Install with "
            "`brew install --cask blackhole-2ch` and approve the kernel "
            "extension in System Settings → Privacy & Security."
        )

    mic_idx = next(
        (i for n, i in devices.items() if "macbook" in n.lower() and "microphone" in n.lower()),
        None,
    )
    if mic_idx is None:
        mic_idx = next(
            (i for n, i in devices.items()
             if "blackhole" not in n.lower()
             and "microphone" in n.lower() or "airpod" in n.lower()),
            None,
        )
    if mic_idx is None:
        raise RuntimeError(f"No mic input found among: {list(devices.keys())}")

    return blackhole_idx, mic_idx


def start_capture(wav_path: Path, *, log_path: Path | None = None) -> CaptureHandle:
    """Start ffmpeg, return its PID + the wav path. Caller must persist
    the PID to outlive process restarts (state file)."""
    binary = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    blackhole_idx, mic_idx = find_indexes()
    wav_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        binary, "-y",
        "-f", "avfoundation", "-i", f":{blackhole_idx}",
        "-f", "avfoundation", "-i", f":{mic_idx}",
        "-filter_complex", "amix=inputs=2:duration=longest:dropout_transition=0",
        "-ac", "1", "-ar", "16000",
        str(wav_path),
    ]
    log.info("starting ffmpeg: BH=:%d mic=:%d → %s",
             blackhole_idx, mic_idx, wav_path.name)

    out_target = open(log_path, "ab") if log_path else subprocess.DEVNULL
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=out_target,
            stderr=out_target,
            close_fds=True,
            start_new_session=True,
        )
    finally:
        if log_path:
            try:
                out_target.close()  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass

    return CaptureHandle(pid=proc.pid, wav_path=wav_path)


def stop_capture(pid: int, *, grace_s: float = 5.0) -> bool:
    """SIGINT the ffmpeg PID so it flushes the WAV header. Returns True
    on a clean exit, False if the process didn't stop within grace."""
    if not is_running(pid):
        return True
    try:
        os.kill(pid, signal.SIGINT)
    except ProcessLookupError:
        return True
    deadline = time.time() + grace_s
    while time.time() < deadline:
        if not is_running(pid):
            return True
        time.sleep(0.2)
    # Last resort.
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    time.sleep(1.0)
    return not is_running(pid)


def is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
