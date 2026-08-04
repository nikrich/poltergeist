"""Auth middleware: rejects missing/wrong tokens, allows OpenAPI introspection."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ghostbrain.api.auth import make_auth_middleware

TOKEN = "test-token-1234"


def _make_app() -> FastAPI:
    app = FastAPI()
    app.middleware("http")(make_auth_middleware(TOKEN))

    @app.get("/v1/echo")
    def echo():
        return {"ok": True}

    return app


def test_missing_auth_header_returns_401():
    client = TestClient(_make_app())
    res = client.get("/v1/echo")
    assert res.status_code == 401


def test_wrong_token_returns_401():
    client = TestClient(_make_app())
    res = client.get("/v1/echo", headers={"Authorization": "Bearer wrong"})
    assert res.status_code == 401


def test_correct_token_passes():
    client = TestClient(_make_app())
    res = client.get("/v1/echo", headers={"Authorization": f"Bearer {TOKEN}"})
    assert res.status_code == 200
    assert res.json() == {"ok": True}


def test_openapi_endpoint_skips_auth():
    client = TestClient(_make_app())
    res = client.get("/openapi.json")
    assert res.status_code == 200


def test_docs_endpoint_skips_auth():
    client = TestClient(_make_app())
    res = client.get("/docs")
    assert res.status_code == 200
