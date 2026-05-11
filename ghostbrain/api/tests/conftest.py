"""Shared fixtures: temp vault, temp state dir, app factory wired to them."""
from __future__ import annotations

import json
import os
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
