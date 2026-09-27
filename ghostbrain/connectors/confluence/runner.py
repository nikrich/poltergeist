"""In-process runner for the Confluence connector."""
from __future__ import annotations

from pathlib import Path

from ghostbrain import accounts
from ghostbrain.connectors._runner import RunResult, run_connector
from ghostbrain.connectors.confluence import ConfluenceConnector


def sites() -> list[str]:
    return [a.id for a in accounts.list_accounts("confluence")]


def _build(routing: dict, queue_dir: Path, state_dir: Path) -> ConfluenceConnector | None:
    spaces = dict((routing.get("confluence") or {}).get("spaces") or {})
    hosts = sites()
    if not hosts or not spaces:
        return None
    return ConfluenceConnector(
        config={"sites": hosts, "spaces": spaces}, queue_dir=queue_dir, state_dir=state_dir,
    )


def run() -> RunResult:
    return run_connector("confluence", build=_build)
