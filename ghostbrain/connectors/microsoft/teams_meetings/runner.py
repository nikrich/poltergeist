"""In-process runner for the Teams meetings connector."""
from __future__ import annotations

from pathlib import Path

from ghostbrain import accounts
from ghostbrain.connectors._runner import RunResult, run_connector
from ghostbrain.connectors.microsoft.teams_meetings import TeamsMeetingsConnector


def _accounts() -> list[dict]:
    """Registry microsoft accounts. None registered -> one entry meaning the
    first cached MSAL sign-in, so a single-account setup keeps syncing even
    when seeding the registry from the cache didn't happen."""
    accts = accounts.list_accounts("microsoft")
    if not accts:
        return [{"username": None, "tenant_id": None}]
    return [{"username": a.id, "tenant_id": a.options.get("tenant_id")} for a in accts]


def _build(routing: dict, queue_dir: Path, state_dir: Path):
    ms = routing.get("microsoft") or {}
    cfg = ms.get("teams_meetings")
    if cfg is None:
        return None
    macos_accounts = ((routing.get("calendar") or {}).get("macos") or {}).get("accounts") or {}
    cfg = {
        **cfg,
        "client_id": ms.get("client_id"),
        "tenant_id": ms.get("tenant_id"),
        "scopes": ms.get("scopes"),
        "accounts": _accounts(),
        "macos_calendars": dict(macos_accounts),
    }
    return TeamsMeetingsConnector(config=cfg, queue_dir=queue_dir, state_dir=state_dir)


def run() -> RunResult:
    return run_connector("teams_meetings", build=_build)
