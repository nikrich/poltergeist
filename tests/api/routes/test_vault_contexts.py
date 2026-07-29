"""GET /v1/vault/contexts: the renderer's source for context dropdowns.

Context lists were hardcoded in the desktop UI (settings/jots screens), which
shipped the original author's personal contexts to every install. The UI now
fetches them; this endpoint must reflect routing.yaml.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ghostbrain.api.main import create_app


@pytest.fixture
def client(vault: Path) -> TestClient:
    app = create_app(token="test-token-1234567890")
    c = TestClient(app)
    c.headers.update({"Authorization": "Bearer test-token-1234567890"})
    return c


def _write_routing(vault: Path, body: str) -> None:
    f = vault / "90-meta" / "routing.yaml"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(body, encoding="utf-8")


def test_returns_configured_contexts_in_order(client: TestClient, vault: Path) -> None:
    _write_routing(vault, "contexts:\n  - work\n  - home\n  - side-hustle\n")
    r = client.get("/v1/vault/contexts")
    assert r.status_code == 200
    assert r.json() == {"contexts": ["work", "home", "side-hustle"]}


def test_falls_back_when_routing_yaml_missing(client: TestClient) -> None:
    r = client.get("/v1/vault/contexts")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["contexts"], list)
    assert body["contexts"], "fallback context list must not be empty"


def test_requires_auth(vault: Path) -> None:
    app = create_app(token="test-token-1234567890")
    c = TestClient(app)
    assert c.get("/v1/vault/contexts").status_code in (401, 403)
