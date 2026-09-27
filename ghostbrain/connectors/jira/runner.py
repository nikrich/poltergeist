"""In-process runner for the Jira connector."""
from __future__ import annotations

from pathlib import Path

from ghostbrain import accounts
from ghostbrain.connectors._runner import RunResult, run_connector
from ghostbrain.connectors.jira import JiraConnector


def sites() -> list[str]:
    return [a.id for a in accounts.list_accounts("jira")]


def _build(routing: dict, queue_dir: Path, state_dir: Path) -> JiraConnector | None:
    hosts = sites()
    if not hosts:
        return None
    return JiraConnector(config={"sites": hosts}, queue_dir=queue_dir, state_dir=state_dir)


def run() -> RunResult:
    return run_connector("jira", build=_build)
