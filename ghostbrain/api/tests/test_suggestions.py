"""GET /v1/suggestions."""
from fastapi.testclient import TestClient


def test_returns_list(client: TestClient, auth_headers: dict[str, str]):
    res = client.get("/v1/suggestions", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)


def test_suggestions_have_required_fields(
    client: TestClient, auth_headers: dict[str, str]
):
    data = client.get("/v1/suggestions", headers=auth_headers).json()
    for item in data:
        assert {"id", "icon", "title", "body"}.issubset(item.keys())
