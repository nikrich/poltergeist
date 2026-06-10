"""Refactor-safety net for the Atlassian import feature.

The import endpoints reuse the confluence/jira conversion code, which Task 1
extracts from the connector classes into module-level functions. These golden
tests pin the scheduled-sync output EXACTLY (full-dict equality) so the
extraction cannot change connector behaviour. They are written and committed
BEFORE the refactor and must stay green, unmodified, after it.

If the body literal below mismatches on the first run (markdownify whitespace),
print the actual event and adjust the literal NOW — before the refactor —
never after.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

PAGE_RAW = {
    "id": "1234567",
    "title": "ASCP architecture overview",
    "space": {"key": "DIG"},
    "version": {
        "number": 5,
        "when": "2026-05-07T09:30:00.000Z",
        "by": {"accountId": "u1", "displayName": "Jannik"},
    },
    "body": {
        "storage": {
            "value": "<p>This is the <strong>ASCP</strong> overview.</p>"
                     "<p>It describes <em>microservices</em> and BFFs.</p>",
        },
    },
    "_links": {
        "base": "https://sft.atlassian.net/wiki",
        "webui": "/spaces/DIG/pages/1234567/Overview",
    },
}

EXPECTED_PAGE_EVENT = {
    "id": "confluence:sft:1234567",
    "source": "confluence",
    "type": "page",
    "subtype": "updated",
    "timestamp": "2026-05-07T09:30:00.000Z",
    "actorId": "confluence:u1",
    "title": "ASCP architecture overview",
    "body": "This is the **ASCP** overview.\n\nIt describes *microservices* and BFFs.",
    "url": "https://sft.atlassian.net/wiki/spaces/DIG/pages/1234567/Overview",
    "rawData": PAGE_RAW,
    "metadata": {
        "site": "sft.atlassian.net",
        "siteSlug": "sft",
        "space": "DIG",
        "pageId": "1234567",
        "version": 5,
        "lastModifiedBy": "Jannik",
    },
}

ISSUE_RAW = {
    "key": "DIGISURE-1234",
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
        "project": {"key": "DIGISURE"},
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

EXPECTED_ISSUE_EVENT = {
    "id": "jira:sft:DIGISURE-1234",
    "source": "jira",
    "type": "ticket",
    "subtype": "in progress",
    "timestamp": "2026-05-07T10:00:00.000+0000",
    "actorId": "jira:def",
    "title": "DIGISURE-1234 Add cashback to quote domain",
    "body": "Add a cashback field...",
    "url": "https://sft.atlassian.net/browse/DIGISURE-1234",
    "rawData": ISSUE_RAW,
    "metadata": {
        "site": "sft.atlassian.net",
        "siteSlug": "sft",
        "project": "DIGISURE",
        "key": "DIGISURE-1234",
        "status": "In Progress",
        "statusCategory": "indeterminate",
        "priority": "Medium",
        "assignee": "Jannik",
        "reporter": "Reporter",
        "labels": ["capstone"],
        "issueType": "Story",
    },
}


@pytest.fixture(autouse=True)
def _atlassian_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATLASSIAN_EMAIL", "u@example.com")
    monkeypatch.setenv("ATLASSIAN_TOKEN_SFT", "test-token")


def test_confluence_scheduled_sync_output_is_pinned(tmp_path) -> None:
    from ghostbrain.connectors.confluence import ConfluenceConnector

    connector = ConfluenceConnector(
        config={"sites": ["sft.atlassian.net"], "spaces": {"DIG": "sanlam"}},
        queue_dir=tmp_path / "q",
        state_dir=tmp_path / "s",
    )
    with patch(
        "ghostbrain.connectors.confluence.AtlassianClient.get",
        return_value={"results": [PAGE_RAW]},
    ):
        events = connector.fetch(datetime(2026, 5, 6, tzinfo=timezone.utc))
    assert events == [EXPECTED_PAGE_EVENT]


def test_jira_scheduled_sync_output_is_pinned(tmp_path) -> None:
    from ghostbrain.connectors.jira import JiraConnector

    connector = JiraConnector(
        config={"sites": ["sft.atlassian.net"]},
        queue_dir=tmp_path / "q",
        state_dir=tmp_path / "s",
    )
    with patch(
        "ghostbrain.connectors.jira.AtlassianClient.get",
        return_value={"issues": [ISSUE_RAW]},
    ):
        events = connector.fetch(datetime(2026, 5, 1, tzinfo=timezone.utc))
    assert events == [EXPECTED_ISSUE_EVENT]


def test_normalize_page_function_matches_pinned_output() -> None:
    from ghostbrain.connectors.confluence import normalize_page

    assert normalize_page(
        PAGE_RAW, host="sft.atlassian.net", space_map={"DIG": "sanlam"}
    ) == EXPECTED_PAGE_EVENT


def test_normalize_page_drops_unmonitored_space() -> None:
    from ghostbrain.connectors.confluence import normalize_page

    assert normalize_page(
        PAGE_RAW, host="sft.atlassian.net", space_map={"OTHER": "personal"}
    ) is None


def test_normalize_issue_function_matches_pinned_output() -> None:
    from ghostbrain.connectors.jira import normalize_issue

    assert normalize_issue(ISSUE_RAW, host="sft.atlassian.net") == EXPECTED_ISSUE_EVENT
