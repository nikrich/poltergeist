"""In-process runner for the Jira connector."""
from __future__ import annotations

from pathlib import Path

from ghostbrain.connectors._runner import RunResult, run_connector
from ghostbrain.connectors.jira import JiraConnector


def _build(routing: dict, queue_dir: Path, state_dir: Path) -> JiraConnector | None:
    sites = list((routing.get("jira") or {}).get("sites") or {})
    if not sites:
        return None
    return JiraConnector(
        config={"sites": sites},
        queue_dir=queue_dir,
        state_dir=state_dir,
    )


def run() -> RunResult:
    return run_connector("jira", build=_build)
