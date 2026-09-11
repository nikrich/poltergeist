"""`setup bootstrap` — create the vault tree (same as the bootstrap subcommand)."""
from __future__ import annotations

import ghostbrain.bootstrap as bootstrap_mod


def main(argv: list[str] | None = None) -> int:
    root = bootstrap_mod.bootstrap()
    print(f"vault ready at {root}")
    return 0
