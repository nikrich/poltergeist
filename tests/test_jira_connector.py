"""Tests for the Jira connector. AtlassianClient HTTP is mocked."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest


_ISSUE_RAW = {
    "key": "ASCP-1234",
    "id": "10001",
    "fields": {
        "summary": "Add cashback to quote domain",
        "status": {"name": "In Progress",
                   "statusCategory": {"key": "indeterminate"}},
        "priority": {"name": "Medium"},
        "issuetype": {"name": "Story"},
        "assignee": {"accountId": "abc", "displayName": "Jannik"},
        "reporter": {"accountId": "def", "displayName": "Reporter"},
        "labels": ["capstone"],
        "project": {"key": "ASCP"},
        "created": "2026-05-01T08:00:00.000+0000",
        "updated": "2026-05-07T10:00:00.000+0000",
        "description": {
            "type": "doc",
            "content": [{
                "type": "paragraph",
                "content": [{"type": "text", "text": "Add a cashback field..."}],
            }],
        },
    },
}


@pytest.fixture(autouse=True)
def _atlassian_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATLASSIAN_EMAIL", "u@example.com")
    monkeypatch.setenv("ATLASSIAN_TOKEN_SFT", "test-token")


def test_fetch_normalizes_issue_into_event(vault: Path, tmp_path: Path) -> None:
    from ghostbrain.connectors.jira import JiraConnector

    connector = JiraConnector(
        config={"sites": ["sft.atlassian.net"]},
        queue_dir=tmp_path / "q",
        state_dir=tmp_path / "s",
    )

    with patch(
        "ghostbrain.connectors.jira.AtlassianClient.get",
        return_value={"issues": [_ISSUE_RAW]},
    ):
        events = connector.fetch(datetime(2026, 5, 1, tzinfo=timezone.utc))

    assert len(events) == 1
    ev = events[0]
    assert ev["id"] == "jira:sft:ASCP-1234"
    assert ev["source"] == "jira"
    assert ev["type"] == "ticket"
    assert ev["subtype"] == "in progress"
    assert ev["title"] == "ASCP-1234 Add cashback to quote domain"
    assert "Add a cashback field" in ev["body"]
    assert ev["url"] == "https://sft.atlassian.net/browse/ASCP-1234"
    assert ev["metadata"]["site"] == "sft.atlassian.net"
    assert ev["metadata"]["siteSlug"] == "sft"
    assert ev["metadata"]["project"] == "ASCP"
    assert ev["metadata"]["status"] == "In Progress"
    assert ev["metadata"]["priority"] == "Medium"
    assert ev["metadata"]["labels"] == ["capstone"]


def test_fetch_returns_empty_for_zero_sites(vault: Path, tmp_path: Path) -> None:
    from ghostbrain.connectors.jira import JiraConnector
    connector = JiraConnector(
        config={"sites": []},
        queue_dir=tmp_path / "q", state_dir=tmp_path / "s",
    )
    assert connector.fetch(datetime(2026, 5, 1, tzinfo=timezone.utc)) == []


def test_fetch_falls_back_to_legacy_search(vault: Path, tmp_path: Path) -> None:
    """If the new /search/jql endpoint errors, the connector should retry
    against the classic /search."""
    from ghostbrain.connectors.jira import JiraConnector

    connector = JiraConnector(
        config={"sites": ["sft.atlassian.net"]},
        queue_dir=tmp_path / "q", state_dir=tmp_path / "s",
    )

    call_count = {"n": 0}

    def fake_get(self, path, **kw):  # noqa: ARG001
        call_count["n"] += 1
        if "jql" in path and "/search/jql" in path:
            raise RuntimeError("410 Gone (fake)")
        return {"issues": [_ISSUE_RAW]}

    with patch(
        "ghostbrain.connectors.jira.AtlassianClient.get",
        autospec=True,
        side_effect=fake_get,
    ):
        events = connector.fetch(datetime(2026, 5, 1, tzinfo=timezone.utc))

    assert len(events) == 1
    assert call_count["n"] == 2  # tried both endpoints


def test_adf_to_text_handles_nested_doc() -> None:
    from ghostbrain.connectors.jira import _adf_to_text

    doc = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [
                {"type": "text", "text": "Hello "},
                {"type": "text", "text": "world"},
            ]},
            {"type": "paragraph", "content": [
                {"type": "text", "text": "Second line"},
            ]},
        ],
    }
    out = _adf_to_text(doc)
    assert "Hello world" in out
    assert "Second line" in out
