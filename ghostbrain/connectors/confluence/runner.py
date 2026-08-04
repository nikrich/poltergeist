"""In-process runner for the Confluence connector."""
from __future__ import annotations

from pathlib import Path

from ghostbrain.connectors._runner import RunResult, run_connector
from ghostbrain.connectors.confluence import ConfluenceConnector


def _build(routing: dict, queue_dir: Path, state_dir: Path) -> ConfluenceConnector | None:
    confluence_cfg = routing.get("confluence") or {}
    spaces = dict(confluence_cfg.get("spaces") or {})
    # Confluence shares Atlassian sites with Jira when not configured explicitly.
    sites = list(
        confluence_cfg.get("sites")
        or (routing.get("jira") or {}).get("sites")
        or []
    )
    if not sites or not spaces:
        return None
    return ConfluenceConnector(
        config={"sites": sites, "spaces": spaces},
        queue_dir=queue_dir,
        state_dir=state_dir,
    )


def run() -> RunResult:
    return run_connector("confluence", build=_build)
