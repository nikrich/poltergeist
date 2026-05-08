"""Wraps `SwitchAudioSource` to flip macOS system audio output.

Used by the recorder daemon to switch to a Multi-Output Device (e.g.
"Ghost Brain") containing BlackHole at meeting start, then restore the
user's normal output device at meeting end.
"""

from __future__ import annotations

import logging
import shutil
import subprocess

log = logging.getLogger("ghostbrain.recorder.audio_switcher")


class AudioSwitcherError(RuntimeError):
    pass


def _binary() -> str:
    path = shutil.which("SwitchAudioSource")
    if path is None:
        raise AudioSwitcherError(
            "SwitchAudioSource not on PATH. Install with "
            "`brew install switchaudio-osx`."
        )
    return path


def current_output() -> str:
    """Return the name of the currently active system output device."""
    proc = subprocess.run(
        [_binary(), "-c", "-t", "output"],
        capture_output=True, text=True, timeout=5,
    )
    if proc.returncode != 0:
        raise AudioSwitcherError(
            f"SwitchAudioSource -c failed: {(proc.stderr or '').strip()}"
        )
    return (proc.stdout or "").strip()


def list_outputs() -> list[str]:
    proc = subprocess.run(
        [_binary(), "-a", "-t", "output"],
        capture_output=True, text=True, timeout=5,
    )
    if proc.returncode != 0:
        return []
    return [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]


def switch_to(name: str) -> None:
    """Switch system output to ``name``. Raises if the device doesn't exist
    or the switch fails."""
    proc = subprocess.run(
        [_binary(), "-s", name, "-t", "output"],
        capture_output=True, text=True, timeout=5,
    )
    if proc.returncode != 0:
        raise AudioSwitcherError(
            f"SwitchAudioSource -s '{name}' failed: "
            f"{(proc.stderr or proc.stdout or '').strip()}"
        )
    log.info("system output → %s", name)
