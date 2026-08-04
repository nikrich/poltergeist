"""In-process runner for the Slack connector."""
from __future__ import annotations

from pathlib import Path

from ghostbrain.connectors._runner import RunResult, run_connector
from ghostbrain.connectors.slack import SlackConnector


def _build(routing: dict, queue_dir: Path, state_dir: Path) -> SlackConnector | None:
    slack_cfg = routing.get("slack") or {}
    workspaces = slack_cfg.get("workspaces") or {}
    if not workspaces:
        return None
    return SlackConnector(
        config={"workspaces": workspaces},
        queue_dir=queue_dir,
        state_dir=state_dir,
    )


def run() -> RunResult:
    return run_connector("slack", build=_build)
