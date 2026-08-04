"""Tests for the Confluence connector. AtlassianClient HTTP is mocked."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest


_PAGE_RAW = {
    "id": "1234567",
    "title": "Service architecture overview",
    "space": {"key": "Helix"},
    "version": {
        "number": 5,
        "when": "2026-05-07T09:30:00.000Z",
        "by": {"accountId": "u1", "displayName": "Priya"},
    },
    "body": {
        "storage": {
            "value": "<p>This is the <strong>Helix</strong> overview.</p>"
                     "<p>It describes <em>microservices</em> and BFFs.</p>",
        },
    },
    "_links": {
        "base": "https://acme.atlassian.net/wiki",
        "webui": "/spaces/Helix/pages/1234567/Overview",
    },
}


@pytest.fixture(autouse=True)
def _atlassian_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATLASSIAN_EMAIL", "u@example.com")
    monkeypatch.setenv("ATLASSIAN_TOKEN_ACME", "test-token")


def test_fetch_normalizes_page_with_html_stripped(vault: Path, tmp_path: Path) -> None:
    from ghostbrain.connectors.confluence import ConfluenceConnector

    connector = ConfluenceConnector(
        config={
            "sites": ["acme.atlassian.net"],
            "spaces": {"Helix": "work"},
        },
        queue_dir=tmp_path / "q",
        state_dir=tmp_path / "s",
    )

    with patch(
        "ghostbrain.connectors.confluence.AtlassianClient.get",
        return_value={"results": [_PAGE_RAW]},
    ):
        events = connector.fetch(datetime(2026, 5, 6, tzinfo=timezone.utc))

    assert len(events) == 1
    ev = events[0]
    assert ev["id"] == "confluence:acme:1234567"
    assert ev["source"] == "confluence"
    assert ev["type"] == "page"
    assert ev["title"] == "Service architecture overview"
    assert "<strong>" not in ev["body"]
    assert "Helix" in ev["body"]
    assert ev["url"].endswith("/spaces/Helix/pages/1234567/Overview")
    assert ev["metadata"]["space"] == "Helix"
    assert ev["metadata"]["pageId"] == "1234567"
    assert ev["metadata"]["version"] == 5


def test_pages_in_unknown_space_are_dropped(vault: Path, tmp_path: Path) -> None:
    from ghostbrain.connectors.confluence import ConfluenceConnector

    connector = ConfluenceConnector(
        config={
            "sites": ["acme.atlassian.net"],
            "spaces": {"Helix": "work"},  # only Helix is monitored
        },
        queue_dir=tmp_path / "q",
        state_dir=tmp_path / "s",
    )

    other_page = {**_PAGE_RAW, "id": "9999", "space": {"key": "RANDOM"}}
    with patch(
        "ghostbrain.connectors.confluence.AtlassianClient.get",
        return_value={"results": [_PAGE_RAW, other_page]},
    ):
        events = connector.fetch(datetime(2026, 5, 6, tzinfo=timezone.utc))

    assert [ev["metadata"]["space"] for ev in events] == ["Helix"]


def test_fetch_returns_empty_when_no_spaces(vault: Path, tmp_path: Path) -> None:
    from ghostbrain.connectors.confluence import ConfluenceConnector
    connector = ConfluenceConnector(
        config={"sites": ["acme.atlassian.net"], "spaces": {}},
        queue_dir=tmp_path / "q", state_dir=tmp_path / "s",
    )
    assert connector.fetch(datetime(2026, 5, 6, tzinfo=timezone.utc)) == []


def test_strip_html_handles_entities() -> None:
    from ghostbrain.connectors.confluence import _strip_html

    html = "<p>Tom &amp; Jerry &lt;love&gt; &quot;cheese&quot;.</p>"
    assert _strip_html(html) == 'Tom & Jerry <love> "cheese".'


def test_router_path_routes_jira_event(vault: Path) -> None:
    """Cross-check: the router knows how to path-route Jira/Confluence events."""
    from ghostbrain.worker.router import route_event

    routing = {
        "jira": {"sites": {"acme.atlassian.net": "work"}},
        "confluence": {"spaces": {"Helix": "work"}},
    }

    jira_event = {
        "id": "jira:acme:Helix-1",
        "source": "jira", "type": "ticket",
        "title": "Helix-1 Test",
        "metadata": {"site": "acme.atlassian.net", "key": "Helix-1"},
    }
    decision = route_event(jira_event, routing=routing)
    assert decision.context == "work"
    assert decision.method == "path"

    conf_event = {
        "id": "confluence:acme:42",
        "source": "confluence", "type": "page",
        "title": "Doc",
        "metadata": {"site": "acme.atlassian.net", "space": "Helix", "pageId": "42"},
    }
    decision = route_event(conf_event, routing=routing)
    assert decision.context == "work"
    assert decision.method == "path"
