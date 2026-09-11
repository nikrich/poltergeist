"""GET /health — used by ghostbrain.doctor.checks_app._health_ok."""
from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from ghostbrain.api.main import API_VERSION, create_app
from ghostbrain.doctor import checks_app


def test_health_route_returns_ok():
    client = TestClient(create_app("tok"))
    r = client.get("/health", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["version"] == API_VERSION


def test_health_ok_check_talks_to_the_real_route(monkeypatch):
    client = TestClient(create_app("tok"))

    def _fake_get(url, headers=None, timeout=None):
        # url is "http://127.0.0.1:{port}/health"; route through the
        # TestClient by path only, ignoring the fake host/port.
        path = "/" + url.split("/", 3)[-1]
        return client.get(path, headers=headers)

    monkeypatch.setattr(httpx, "get", _fake_get)
    assert checks_app._health_ok(0, "tok") is True
    assert checks_app._health_ok(0, "wrong-token") is False
