"""`setup cli-shim` — write a `poltergeist` wrapper that execs this binary.

Mirrors desktop/src/main/cli-shim.ts so the CLI can install itself when the
user never opened Settings → background → "command line tool".
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def CANDIDATES() -> list[Path]:  # noqa: N802, RUF100 — monkeypatched as a function in tests
    return [Path("/usr/local/bin"), Path.home() / ".local" / "bin"]


def binary_path() -> str:
    if getattr(sys, "frozen", False):
        return sys.executable
    candidate = Path(sys.executable).parent / "ghostbrain-api"
    return str(candidate) if candidate.is_file() else sys.executable


def _writable(d: Path) -> bool:
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    return os.access(d, os.W_OK)


def main(argv: list[str] | None = None) -> int:
    try:
        script = f'#!/bin/sh\nexec "{binary_path()}" "$@"\n'
        for d in CANDIDATES():
            if not _writable(d):
                continue
            d.mkdir(parents=True, exist_ok=True)
            target = d / "poltergeist"
            if target.is_dir():
                print(f"{target} is a directory; remove it and re-run", file=sys.stderr)
                return 1
            if target.exists() and target.read_text() == script:
                print(f"already installed at {target}")
            else:
                target.write_text(script)
                target.chmod(0o755)
                print(f"installed {target}")
            if str(d) not in os.environ.get("PATH", "").split(os.pathsep):
                print(f"{d} is not on your PATH; add it to your shell profile: export PATH=\"{d}:$PATH\"")
            return 0
        print("no writable install directory (tried /usr/local/bin and ~/.local/bin)", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"cli-shim failed: {e}", file=sys.stderr)
        return 1
