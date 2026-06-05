"""In-process runner for the Teams chat connector."""
from __future__ import annotations

from pathlib import Path

from ghostbrain.connectors._runner import RunResult, run_connector
from ghostbrain.connectors.microsoft.teams_chat import TeamsChatConnector


def _build(routing: dict, queue_dir: Path, state_dir: Path):
    ms = routing.get("microsoft") or {}
    cfg = ms.get("teams_chat")
    if cfg is None:
        return None
    cfg = {
        **cfg,
        "client_id": ms.get("client_id"),
        "tenant_id": ms.get("tenant_id"),
        "scopes": ms.get("scopes"),
    }
    return TeamsChatConnector(config=cfg, queue_dir=queue_dir, state_dir=state_dir)


def run() -> RunResult:
    return run_connector("teams_chat", build=_build)
