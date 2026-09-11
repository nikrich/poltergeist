"""GET /v1/doctor."""
from __future__ import annotations

from fastapi.testclient import TestClient

from ghostbrain import doctor
from ghostbrain.api.main import create_app
from ghostbrain.doctor import CheckResult


def test_doctor_route_returns_check_document(monkeypatch):
    monkeypatch.setattr(doctor, "CHECKS", [])

    @doctor.register("vault")
    def _v() -> CheckResult:
        return CheckResult(id="vault", status="ok", summary="/tmp/vault")

    client = TestClient(create_app("tok"))
    r = client.get("/v1/doctor", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"platform", "version", "checks"}
    assert body["checks"][0]["id"] == "vault"
