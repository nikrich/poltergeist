"""In-process runner for the Slack connector."""
from __future__ import annotations

from pathlib import Path

from ghostbrain import accounts
from ghostbrain.connectors._runner import RunResult, run_connector
from ghostbrain.connectors.slack import SlackConnector


def workspaces_config() -> dict[str, dict]:
    return {a.id: dict(a.options) for a in accounts.list_accounts("slack")}


def _build(routing: dict, queue_dir: Path, state_dir: Path) -> SlackConnector | None:
    workspaces = workspaces_config()
    if not workspaces:
        return None
    return SlackConnector(config={"workspaces": workspaces}, queue_dir=queue_dir, state_dir=state_dir)


def run() -> RunResult:
    return run_connector("slack", build=_build)
