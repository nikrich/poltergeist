"""In-process runner for the Gmail connector."""
from __future__ import annotations

from pathlib import Path

from ghostbrain.connectors._runner import RunResult, run_connector
from ghostbrain.connectors.gmail import GmailConnector


def _build(routing: dict, queue_dir: Path, state_dir: Path) -> GmailConnector | None:
    gmail_cfg = routing.get("gmail") or {}
    accounts = gmail_cfg.get("accounts") or {}
    if not accounts:
        return None
    return GmailConnector(
        config={
            "accounts": accounts,
            "denylist_domains": gmail_cfg.get("denylist_domains") or [],
            "relevance_gate": gmail_cfg.get("relevance_gate", True),
            "relevance_model": gmail_cfg.get("relevance_model"),
        },
        queue_dir=queue_dir,
        state_dir=state_dir,
    )


def run() -> RunResult:
    return run_connector("gmail", build=_build)
