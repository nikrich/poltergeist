"""`ghostbrain-api setup <fix> [args]` — apply one first-run fix."""
from __future__ import annotations

import importlib
import sys
from collections.abc import Callable

FIXES: dict[str, str] = {
    "deps": "ghostbrain.doctor.fixes.deps:main",
    "fetch-model": "ghostbrain.doctor.fixes.models:main",
    "cli-shim": "ghostbrain.doctor.fixes.cli_shim:main",
    "go-live": "ghostbrain.doctor.fixes.go_live:main",
    "install-hook": "ghostbrain.doctor.fixes.hook:main",
    "audio-device": "ghostbrain.doctor.fixes.audio_device:main",
    "bootstrap": "ghostbrain.doctor.fixes.bootstrap:main",
}


def _load(target: str) -> Callable[[list[str]], int]:
    mod_name, func_name = target.split(":")
    return getattr(importlib.import_module(mod_name), func_name)


def _usage() -> str:
    return "usage: ghostbrain-api setup <fix> [args]\navailable: " + ", ".join(sorted(FIXES))


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(_usage(), file=sys.stderr)
        return 2
    name, rest = argv[0], argv[1:]
    if name not in FIXES:
        print(f"unknown fix: {name!r}\n{_usage()}", file=sys.stderr)
        return 2
    rc = _load(FIXES[name])(rest)
    return rc if isinstance(rc, int) and not isinstance(rc, bool) else 0
