"""`setup deps [--only NAME ...]` — install the macOS recorder dependencies via Homebrew.

Only installs what is missing. BlackHole is a cask whose installer prompts for
the macOS password; brew handles that prompt when run from a terminal, which is
why the doctor marks it `interactive` and the skill hands it to the user.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

# doctor name -> (brew name, is_cask). Order is install order.
PACKAGES: dict[str, tuple[str, bool]] = {
    "ffmpeg": ("ffmpeg", False),
    "whisper-cpp": ("whisper-cpp", False),
    "switchaudio-osx": ("switchaudio-osx", False),
    "blackhole": ("blackhole-2ch", True),
}

_BINARY_FOR = {
    "ffmpeg": "ffmpeg",
    "whisper-cpp": "whisper-cli",
    "switchaudio-osx": "SwitchAudioSource",
}


def _platform() -> str:
    return sys.platform


def _brew() -> str | None:
    return (shutil.which("brew") or next(
        (p for p in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew") if os.path.exists(p)), None))


def _is_installed(name: str) -> bool:
    if name == "blackhole":
        from ghostbrain.doctor.checks_recorder import BLACKHOLE_DEVICE, _outputs

        outputs = _outputs()
        return outputs is not None and BLACKHOLE_DEVICE in outputs
    return shutil.which(_BINARY_FOR[name]) is not None


def _run(cmd: list[str]) -> int:
    """Stream brew's output so a long install is visibly alive."""
    return subprocess.call(cmd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ghostbrain-api setup deps")
    parser.add_argument("--only", action="append", default=[], metavar="NAME",
                        help="install just this dependency (repeatable): " + ", ".join(PACKAGES))
    args = parser.parse_args([] if argv is None else argv)

    for name in args.only:
        if name not in PACKAGES:
            print(f"unknown dependency: {name!r}; choose from {', '.join(PACKAGES)}", file=sys.stderr)
            return 2
    if _platform() != "darwin":
        print("setup deps is macOS only (Homebrew); see docs/install/ for your platform", file=sys.stderr)
        return 1
    brew = _brew()
    if brew is None:
        print("Homebrew is not installed. Install it from https://brew.sh (needs your password), then re-run.",
              file=sys.stderr)
        return 1

    wanted = args.only or list(PACKAGES)
    for name, (formula, is_cask) in PACKAGES.items():  # keep canonical order regardless of --only order
        if name not in wanted:
            continue
        if _is_installed(name):
            print(f"{name}: already installed")
            continue
        cmd = [brew, "install"] + (["--cask"] if is_cask else []) + [formula]
        print(f"{name}: {' '.join(cmd[1:])}")
        if _run(cmd) != 0:
            print(f"brew install {formula} failed; fix the error above and re-run", file=sys.stderr)
            return 1
        print(f"{name}: installed")
    return 0
