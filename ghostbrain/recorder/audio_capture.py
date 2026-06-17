"""ffmpeg subprocess wrapper for meeting audio capture.

Captures BlackHole 2ch (system audio) + the default Mac microphone,
mixes them, writes 16-kHz mono WAV that whisper.cpp likes.
"""

from __future__ import annotations

import json
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


class AudioRoutingError(RuntimeError):
    """Raised when the system output isn't routed through BlackHole, so
    recording would silently capture only the microphone (or nothing).

    Keeping this separate from RuntimeError lets the caller surface a
    specific, actionable message to the user instead of a generic
    "recording failed" toast.
    """


# Names of devices we trust to relay system audio into BlackHole. Direct
# BlackHole, the bootstrap-created "Ghost Brain" multi-output, and the
# generic macOS aggregate-device labels all qualify. The user can extend
# this via GHOSTBRAIN_ALLOWED_AUDIO_OUTPUTS (comma-separated) when they
# have a custom multi-output name.
_BUILTIN_ALLOWED_OUTPUT_PATTERNS: tuple[str, ...] = (
    "blackhole",
    "ghost brain",
    "ghostbrain",
    "multi-output",
    "multi output",
    "aggregate",
)


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


def current_default_output_device() -> str | None:
    """Return the macOS default audio output device name, or None on failure.

    Reads system_profiler's audio data — slower than a raw CoreAudio API
    call but doesn't require pyobjc. Failure is silent: callers treat a
    None result as "couldn't verify" and the routing assert is
    permissive in that case (better to record than block on a probe
    failure).
    """
    binary = shutil.which("system_profiler")
    if binary is None:
        return None
    try:
        result = subprocess.run(
            [binary, "SPAudioDataType", "-json"],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout or "")
    except json.JSONDecodeError:
        return None
    for outer in payload.get("SPAudioDataType") or []:
        for dev in outer.get("_items") or []:
            flag = dev.get("coreaudio_default_audio_output_device")
            if flag in ("spaudio_yes", True, "yes"):
                name = dev.get("_name")
                return str(name) if name else None
    return None


def output_likely_reaches_blackhole(device_name: str | None) -> bool:
    """Heuristic: does this output device pipe audio into BlackHole?

    True for direct BlackHole, the canonical "Ghost Brain" multi-output,
    and any user-extended names listed in GHOSTBRAIN_ALLOWED_AUDIO_OUTPUTS.
    system_profiler doesn't expose aggregate-device subdevice lists in
    JSON, so we can't programmatically prove BlackHole is wired in; this
    is a name-based shortlist plus an env-var escape hatch.
    """
    if not device_name:
        # Couldn't probe — fall open. Better a silent recording than a
        # blocked one when the probe machinery itself is broken.
        return True
    needle = device_name.strip().lower()
    if any(p in needle for p in _BUILTIN_ALLOWED_OUTPUT_PATTERNS):
        return True
    extra = os.environ.get("GHOSTBRAIN_ALLOWED_AUDIO_OUTPUTS", "")
    for entry in extra.split(","):
        entry = entry.strip().lower()
        if entry and entry in needle:
            return True
    return False


def assert_output_routes_to_blackhole() -> None:
    """Raise AudioRoutingError if macOS default output won't reach BlackHole.

    Called at the top of start_capture so a misconfigured output never
    silently produces a 72-minute file of [BLANK_AUDIO]. The message
    embeds the actual current device name and the exact one-line fix.
    """
    name = current_default_output_device()
    if output_likely_reaches_blackhole(name):
        return
    raise AudioRoutingError(
        f"macOS audio output is '{name or 'unknown'}', which does not "
        f"route system audio through BlackHole. Recording would only "
        f"capture the microphone. "
        f"Fix: open the Sound menubar item and switch the Output to "
        f"'Ghost Brain' (or another multi-output device that includes "
        f"BlackHole 2ch). To allow a custom output name, set "
        f"GHOSTBRAIN_ALLOWED_AUDIO_OUTPUTS='<name>' in the environment."
    )


def start_capture(wav_path: Path, *, log_path: Path | None = None) -> CaptureHandle:
    """Start ffmpeg, return its PID + the wav path. Caller must persist
    the PID to outlive process restarts (state file)."""
    assert_output_routes_to_blackhole()
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


def _is_zombie(pid: int) -> bool:
    """True if `pid` is a terminated-but-unreaped process (state 'Z').

    A zombie still occupies a PID slot, so kill(pid, 0) succeeds and signals
    sent to it are no-ops. We can't use os.waitpid() because the PID is often
    a child of a *different* process (the recorder ffmpeg outlives the
    instance that spawned it), so shell out to `ps` for the state column.
    """
    try:
        out = subprocess.run(
            ["ps", "-p", str(pid), "-o", "state="],
            capture_output=True, text=True, timeout=2,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return False  # can't tell — fall open, treat as not-a-zombie
    return out.startswith("Z")


def is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # The PID exists, but a zombie (exited, not yet reaped) also answers
    # kill(pid, 0). Treat zombies as not running so a dead ffmpeg whose parent
    # never wait()ed it can't wedge stop()/status() on a corpse forever.
    return not _is_zombie(pid)
