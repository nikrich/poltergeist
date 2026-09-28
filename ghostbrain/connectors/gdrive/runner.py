"""In-process runner for the Google Drive connector."""
from __future__ import annotations

from pathlib import Path

from ghostbrain import accounts
from ghostbrain.connectors._runner import RunResult, run_connector
from ghostbrain.connectors.gdrive import GdriveConnector


def _build(routing: dict, queue_dir: Path, state_dir: Path) -> GdriveConnector | None:
    accts = accounts.list_accounts("gdrive")
    if not accts:
        return None
    return GdriveConnector(config={"accounts": [a.id for a in accts]},
                           queue_dir=queue_dir, state_dir=state_dir)


def run() -> RunResult:
    return run_connector("gdrive", build=_build)
