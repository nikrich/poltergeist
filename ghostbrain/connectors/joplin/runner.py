"""In-process runner for the Joplin connector. Called by the scheduler."""
from __future__ import annotations

from pathlib import Path

from ghostbrain.connectors._runner import RunResult, run_connector
from ghostbrain.connectors.joplin import JoplinConnector


def _build(routing: dict, queue_dir: Path, state_dir: Path) -> JoplinConnector | None:
    joplin_cfg = routing.get("joplin") or {}
    if not joplin_cfg.get("token"):
        return None
    return JoplinConnector(
        config=joplin_cfg,
        queue_dir=queue_dir,
        state_dir=state_dir,
    )


def run() -> RunResult:
    return run_connector("joplin", build=_build)
