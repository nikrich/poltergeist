"""In-process runner for the WhatsApp connector (macOS only)."""
from __future__ import annotations

import sys
from pathlib import Path

from ghostbrain.connectors._runner import RunResult, run_connector
from ghostbrain.connectors.whatsapp import WhatsAppConnector, allowlist, store


def _build(routing: dict, queue_dir: Path, state_dir: Path) -> WhatsAppConnector | None:
    if sys.platform != "darwin":
        return None
    # Opt-in first: never touch WhatsApp's store (or trip Full Disk Access)
    # until the user has picked at least one chat.
    if not allowlist.load(state_dir):
        return None
    path = store.default_store_path()
    if not path.exists():
        return None
    cfg = dict(routing.get("whatsapp") or {})
    cfg["store_path"] = str(path)
    return WhatsAppConnector(config=cfg, queue_dir=queue_dir, state_dir=state_dir)


def run() -> RunResult:
    return run_connector("whatsapp", build=_build)
