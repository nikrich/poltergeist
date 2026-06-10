"""Shared fixtures: temp vault, temp state dir, app factory wired to them."""
from __future__ import annotations

import json
import os
import yaml
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from ghostbrain.api.main import create_app

TEST_TOKEN = "test-token-1234567890"


@pytest.fixture
def tmp_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a clean temp vault and point VAULT_PATH at it."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "10-daily").mkdir()
    (vault / "20-contexts").mkdir()
    (vault / "60-dashboards").mkdir()
    (vault / "80-profile").mkdir()
    (vault / "90-meta").mkdir()
    (vault / "90-meta" / "queue").mkdir()
    (vault / "90-meta" / "queue" / "pending").mkdir()
    (vault / "90-meta" / "audit").mkdir()
    monkeypatch.setenv("VAULT_PATH", str(vault))
    return vault


@pytest.fixture
def tmp_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a clean temp state dir and point GHOSTBRAIN_STATE_DIR at it."""
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(state))
    return state


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_TOKEN}"}


@pytest.fixture
def client(tmp_vault: Path, tmp_state_dir: Path) -> Iterator[TestClient]:
    app = create_app(token=TEST_TOKEN)
    with TestClient(app) as c:
        yield c


def write_note(vault: Path, relative_path: str, body: str = "# Note\n\nbody.\n") -> Path:
    """Helper: write a markdown file at vault/<relative_path>, creating dirs."""
    p = vault / relative_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return p


def write_state(state_dir: Path, connector_id: str, data: dict) -> Path:
    """Helper: write state.json for a connector (legacy schema; kept for compat)."""
    p = state_dir / connector_id / "state.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data))
    return p


def write_last_run(state_dir: Path, key: str, iso_ts: str) -> Path:
    """Helper: write <key>.last_run as a flat text file containing an ISO timestamp."""
    p = state_dir / f"{key}.last_run"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(iso_ts)
    return p


@pytest.fixture
def tmp_chats_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point GHOSTBRAIN_CHATS_DIR at a clean temp dir."""
    chats = tmp_path / "chats"
    monkeypatch.setenv("GHOSTBRAIN_CHATS_DIR", str(chats))
    return chats


def write_import_routing(vault: Path, *, jira: bool = True, confluence: bool = True) -> Path:
    """Write a routing.yaml mirroring the real shape: dicts keyed by host/space."""
    routing: dict = {"version": 1}
    if jira:
        routing["jira"] = {"sites": {"sft.atlassian.net": "sanlam"}}
    if confluence:
        routing["confluence"] = {
            "sites": {"sft.atlassian.net": "sanlam"},
            "spaces": {"DIG": "sanlam", "SPE": "sanlam"},
        }
    p = vault / "90-meta" / "routing.yaml"
    p.write_text(yaml.safe_dump(routing))
    return p


def write_live_config(vault: Path) -> Path:
    """routing_mode live so write_note also writes the context copy."""
    p = vault / "90-meta" / "config.yaml"
    p.write_text(yaml.safe_dump({"worker": {"routing_mode": "live"}}))
    return p


@pytest.fixture
def fake_atlassian(monkeypatch: pytest.MonkeyPatch):
    """Replace AtlassianClient + auth_for_site in the import-repo namespace.

    Register URL-path prefixes on ``registry.routes`` (payload dict, or a
    callable ``(path, params) -> dict`` that may raise); the longest matching
    prefix wins. Every GET is recorded on ``registry.calls`` as
    ``(host, path, params)``.
    """
    from ghostbrain.api.repo import import_atlassian as repo

    class Registry:
        def __init__(self) -> None:
            self.routes: dict[str, object] = {}
            self.calls: list[tuple[str, str, dict | None]] = []

    registry = Registry()

    class FakeClient:
        def __init__(self, host: str, email: str, token: str) -> None:
            self.host = host

        def get(self, path: str, params: dict | None = None, **_kw) -> dict:
            registry.calls.append((self.host, path, params))
            match = max(
                (p for p in registry.routes if path.startswith(p)),
                key=len,
                default=None,
            )
            if match is None:
                raise AssertionError(f"unexpected atlassian GET {path}")
            payload = registry.routes[match]
            return payload(path, params) if callable(payload) else payload  # type: ignore[operator]

    monkeypatch.setattr(repo, "AtlassianClient", FakeClient)
    monkeypatch.setattr(repo, "auth_for_site", lambda host: ("u@example.com", "tok"))
    return registry
