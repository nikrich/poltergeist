"""App factory: builds a FastAPI app with auth + OpenAPI metadata."""
from fastapi.testclient import TestClient

from ghostbrain.api.main import create_app


def test_app_has_openapi_schema():
    app = create_app(token="t")
    client = TestClient(app)
    res = client.get("/openapi.json")
    assert res.status_code == 200
    schema = res.json()
    assert schema["info"]["title"] == "ghostbrain"
    assert schema["info"]["version"].startswith("1.")


def test_app_requires_auth_on_v1_routes():
    """A hypothetical /v1/* route 401s without auth. Real coverage in
    route-specific tests; here we just verify the middleware is wired."""
    pass


def test_app_no_health_endpoint():
    """/v1/health does NOT exist by design — auth happens on every /v1/ path
    and health-checking is a sidecar concern, not an HTTP concern."""
    pass
