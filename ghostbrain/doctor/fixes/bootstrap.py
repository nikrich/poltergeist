"""`setup bootstrap` — create the vault tree (same as the bootstrap subcommand)."""
from __future__ import annotations

import sys

import ghostbrain.bootstrap as bootstrap_mod


def main(argv: list[str] | None = None) -> int:
    try:
        root = bootstrap_mod.bootstrap()
        print(f"vault ready at {root}")
        return 0
    except Exception as e:  # noqa: BLE001 — catch all exceptions for one-line error reporting
        print(f"bootstrap failed: {e}", file=sys.stderr)
        return 1
