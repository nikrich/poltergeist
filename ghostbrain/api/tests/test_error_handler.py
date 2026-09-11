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


def test_unauthenticated_request_is_401_not_500_and_still_carries_a_request_id():
    """auth is registered before install_error_handling in create_app(), but
    Starlette's add_middleware inserts at index 0 and build_middleware_stack
    wraps in reverse, so the LAST-registered app.middleware("http") call ends
    up OUTERMOST — here that's the request-id middleware, not auth. This
    doesn't break anything because auth returns a 401 JSONResponse instead of
    raising, so it never reaches install_error_handling's except clause; the
    request-id middleware still wraps around it and stamps X-Request-ID on
    the 401 on its way back out, which this test locks in."""
    app = create_app("tok")
    router = APIRouter()

    @router.get("/v1/boom")
    def boom():
        raise ValueError("kaboom")

    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/v1/boom")  # no Authorization header
    assert r.status_code == 401
    assert r.json() == {"detail": "Unauthorized"}
    assert "X-Request-ID" in r.headers
