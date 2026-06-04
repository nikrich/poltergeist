"""Tests for the Graph HTTP client. `requests` is mocked — no network."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _resp(status, json_body):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_body
    return r


def test_get_returns_json_body() -> None:
    from ghostbrain.connectors.microsoft.graph.client import GraphClient

    c = GraphClient("tok")
    with patch("requests.get", return_value=_resp(200, {"value": [1, 2]})) as g:
        out = c.get("/me/messages", params={"$top": 5})
    assert out == {"value": [1, 2]}
    # Bearer header was sent.
    _, kwargs = g.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer tok"


def test_get_401_raises_microsoft_auth_error() -> None:
    from ghostbrain.connectors.microsoft.graph.auth import MicrosoftAuthError
    from ghostbrain.connectors.microsoft.graph.client import GraphClient

    c = GraphClient("tok")
    with patch("requests.get", return_value=_resp(401, {})):
        with pytest.raises(MicrosoftAuthError):
            c.get("/me/messages")


def test_get_all_follows_next_link() -> None:
    from ghostbrain.connectors.microsoft.graph.client import GraphClient

    page1 = _resp(200, {
        "value": [{"id": "a"}],
        "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/messages?$skip=1",
    })
    page2 = _resp(200, {"value": [{"id": "b"}]})

    c = GraphClient("tok")
    with patch("requests.get", side_effect=[page1, page2]):
        items = c.get_all("/me/messages")
    assert [i["id"] for i in items] == ["a", "b"]


def test_get_all_respects_max_items() -> None:
    from ghostbrain.connectors.microsoft.graph.client import GraphClient

    page1 = _resp(200, {
        "value": [{"id": "a"}, {"id": "b"}],
        "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/messages?$skip=2",
    })
    c = GraphClient("tok")
    with patch("requests.get", side_effect=[page1]) as g:
        items = c.get_all("/me/messages", max_items=2)
    assert len(items) == 2
    # Stopped after the first page because max_items was reached.
    assert g.call_count == 1
