"""Resolve filesystem paths used across the project."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_VAULT_PATH = Path.home() / "ghostbrain" / "vault"


def vault_path() -> Path:
    """Return the configured vault root.

    Reads `VAULT_PATH` env var if set, otherwise falls back to
    `~/ghostbrain/vault/`. Returned path is absolute and expanded.
    """
    raw = os.environ.get("VAULT_PATH")
    if raw:
        return Path(raw).expanduser().resolve()
    return DEFAULT_VAULT_PATH.resolve()


def queue_dir() -> Path:
    return vault_path() / "90-meta" / "queue"


def audit_dir() -> Path:
    return vault_path() / "90-meta" / "audit"


def state_dir() -> Path:
    """Connector state lives outside the vault to avoid syncing it."""
    raw = os.environ.get("GHOSTBRAIN_STATE_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".ghostbrain" / "state").resolve()
