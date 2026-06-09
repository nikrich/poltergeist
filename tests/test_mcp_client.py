# tests/test_mcp_client.py
import httpx
import pytest

from ghostbrain.mcp.client import SidecarClient, SidecarNotRunning


def _client(handler, descriptor):
    """Build a SidecarClient whose HTTP layer is a MockTransport."""
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    return SidecarClient(loader=lambda: descriptor, http_client=http)


DESCRIPTOR = {"port": 51234, "token": "secret-tok", "pid": 1, "version": "1.0.0"}


def test_answer_posts_with_bearer_token():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = request.read().decode()
        return httpx.Response(200, json={"answer": "hi", "sources": []})

    out = _client(handler, DESCRIPTOR).answer("why?", limit=5)
    assert out == {"answer": "hi", "sources": []}
    assert seen["method"] == "POST"
    assert seen["url"] == "http://127.0.0.1:51234/v1/answer"
    assert seen["auth"] == "Bearer secret-tok"
    assert '"q": "why?"' in seen["body"] or '"q":"why?"' in seen["body"]
    assert "5" in seen["body"]


def test_search_posts_to_search_endpoint():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://127.0.0.1:51234/v1/search"
        return httpx.Response(200, json={"items": [], "total": 0, "query": "x"})

    out = _client(handler, DESCRIPTOR).search("x", limit=10)
    assert out["total"] == 0


def test_get_note_gets_with_path_query():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/v1/notes"
        assert request.url.params.get("path") == "20-contexts/sanlam/x.md"
        return httpx.Response(200, json={"path": "p", "title": "t", "body": "b", "frontmatter": {}})

    out = _client(handler, DESCRIPTOR).get_note("20-contexts/sanlam/x.md")
    assert out["title"] == "t"


def test_no_descriptor_raises_not_running():
    client = SidecarClient(loader=lambda: None, http_client=httpx.Client())
    with pytest.raises(SidecarNotRunning):
        client.answer("q", limit=1)


def test_connection_refused_raises_not_running():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(SidecarNotRunning):
        _client(handler, DESCRIPTOR).search("x", limit=1)
