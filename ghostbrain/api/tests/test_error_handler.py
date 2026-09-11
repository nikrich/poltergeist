from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.testclient import TestClient

from ghostbrain.api.main import create_app


def test_unhandled_exception_is_logged_with_request_id(caplog):
    app = create_app("tok")
    router = APIRouter()

    @router.get("/v1/boom")
    def boom():
        raise ValueError("kaboom")

    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR, logger="ghostbrain.api"):
        r = client.get("/v1/boom", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 500
    body = r.json()
    assert body["detail"] == "Internal error"
    rid = body["requestId"]
    assert r.headers["X-Request-ID"] == rid
    assert any("kaboom" in rec.getMessage() or "kaboom" in (rec.exc_text or "") for rec in caplog.records)
    assert any(rid in rec.getMessage() for rec in caplog.records)
