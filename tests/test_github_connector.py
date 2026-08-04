"""Tests for the GitHub connector. gh subprocess is mocked."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest


_PR_RAW = {
    "number": 42,
    "title": "feat: ship the worker",
    "body": "Adds the queue worker.",
    "url": "https://github.com/AcmeLabs/x/pull/42",
    "state": "OPEN",
    "isDraft": False,
    "repository": {"nameWithOwner": "AcmeLabs/x"},
    "author": {"login": "nikrich"},
    "labels": [{"name": "feature"}],
    "createdAt": "2026-05-01T08:00:00Z",
    "updatedAt": "2026-05-07T10:00:00Z",
}

_ISSUE_RAW = {
    "number": 7,
    "title": "Bug: extractor returns []",
    "body": "...",
    "url": "https://github.com/AcmeLabs/x/issues/7",
    "state": "OPEN",
    "repository": {"nameWithOwner": "AcmeLabs/x"},
    "author": {"login": "nikrich"},
    "labels": [],
    "createdAt": "2026-05-05T08:00:00Z",
    "updatedAt": "2026-05-07T11:00:00Z",
}


def _run_proc(stdout: str, returncode: int = 0):
    class P:
        pass
    p = P()
    p.stdout = stdout
    p.stderr = ""
    p.returncode = returncode
    return p


def test_fetch_dedups_prs_across_queries(vault: Path, tmp_path: Path) -> None:
    from ghostbrain.connectors.github import GitHubConnector

    connector = GitHubConnector(
        config={"orgs": ["AcmeLabs"]},
        queue_dir=tmp_path / "q",
        state_dir=tmp_path / "s",
        gh_binary="/fake/gh",
    )

    # gh search prs returns the same PR for both authored and review-requested
    # queries; gh search issues returns one issue.
    pr_response = _run_proc(json.dumps([_PR_RAW]))
    issue_response = _run_proc(json.dumps([_ISSUE_RAW]))

    with patch.object(connector, "_run_gh", side_effect=[
        pr_response,    # authored
        pr_response,    # review-requested  (same PR)
        issue_response,  # assigned
    ]):
        events = connector.fetch(datetime(2026, 5, 1, tzinfo=timezone.utc))

    # 1 unique PR + 1 issue (PR appeared twice → deduped)
    assert len(events) == 2
    types = {e["type"] for e in events}
    assert types == {"pr", "issue"}


def test_fetch_returns_empty_when_no_orgs(vault: Path, tmp_path: Path) -> None:
    from ghostbrain.connectors.github import GitHubConnector

    connector = GitHubConnector(
        config={"orgs": []},
        queue_dir=tmp_path / "q",
        state_dir=tmp_path / "s",
        gh_binary="/fake/gh",
    )
    assert connector.fetch(datetime(2026, 5, 1, tzinfo=timezone.utc)) == []


def test_normalize_pr_shape(vault: Path, tmp_path: Path) -> None:
    from ghostbrain.connectors.github import GitHubConnector

    connector = GitHubConnector(
        config={"orgs": ["AcmeLabs"]},
        queue_dir=tmp_path / "q", state_dir=tmp_path / "s",
        gh_binary="/fake/gh",
    )
    ev = connector._normalize_pr(_PR_RAW, origin="authored")
    assert ev["id"] == "github:pr:AcmeLabs/x#42"
    assert ev["source"] == "github"
    assert ev["type"] == "pr"
    assert ev["subtype"] == "opened"
    assert ev["metadata"]["repo"] == "AcmeLabs/x"
    assert ev["metadata"]["org"] == "AcmeLabs"
    assert ev["metadata"]["origin"] == "authored"
    assert ev["title"] == "feat: ship the worker"


def test_normalize_pr_subtype_for_merged(vault: Path, tmp_path: Path) -> None:
    from ghostbrain.connectors.github import GitHubConnector
    connector = GitHubConnector(
        config={"orgs": ["X"]},
        queue_dir=tmp_path / "q", state_dir=tmp_path / "s",
        gh_binary="/fake/gh",
    )
    raw = {**_PR_RAW, "state": "MERGED"}
    ev = connector._normalize_pr(raw, origin="authored")
    assert ev["subtype"] == "merged"


def test_normalize_pr_subtype_for_review_requested(vault: Path, tmp_path: Path) -> None:
    from ghostbrain.connectors.github import GitHubConnector
    connector = GitHubConnector(
        config={"orgs": ["X"]},
        queue_dir=tmp_path / "q", state_dir=tmp_path / "s",
        gh_binary="/fake/gh",
    )
    ev = connector._normalize_pr(_PR_RAW, origin="review-requested")
    assert ev["subtype"] == "review-requested"


def test_health_check_returns_false_on_failed_subprocess(vault: Path, tmp_path: Path) -> None:
    from ghostbrain.connectors.github import GitHubConnector

    connector = GitHubConnector(
        config={"orgs": ["X"]},
        queue_dir=tmp_path / "q", state_dir=tmp_path / "s",
        gh_binary="/fake/gh",
    )
    with patch.object(connector, "_run_gh", return_value=_run_proc("", 1)):
        assert connector.health_check() is False
