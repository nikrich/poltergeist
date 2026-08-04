"""In-process runner for the GitHub connector. Called by the scheduler."""
from __future__ import annotations

from pathlib import Path

from ghostbrain.connectors._runner import RunResult, run_connector
from ghostbrain.connectors.github import GitHubConnector


def _build(routing: dict, queue_dir: Path, state_dir: Path) -> GitHubConnector | None:
    orgs = list((routing.get("github") or {}).get("orgs") or {})
    if not orgs:
        return None
    return GitHubConnector(
        config={"orgs": orgs},
        queue_dir=queue_dir,
        state_dir=state_dir,
    )


def run() -> RunResult:
    return run_connector("github", build=_build)
