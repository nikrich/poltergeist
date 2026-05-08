"""Tests for the Gmail connector. Google API client is mocked — no
network, no OAuth. Pure logic + normalization."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Pure helpers (no network, no service)
# ---------------------------------------------------------------------------


def test_quote_label_leaves_simple_labels_unquoted() -> None:
    from ghostbrain.connectors.gmail.connector import _quote_label
    assert _quote_label("sanlam") == "sanlam"
    assert _quote_label("sanlam/policies") == "sanlam/policies"
    assert _quote_label("Codeship-Internal") == "Codeship-Internal"


def test_quote_label_quotes_labels_with_spaces() -> None:
    from ghostbrain.connectors.gmail.connector import _quote_label
    assert _quote_label("Sanlam Internal") == '"Sanlam Internal"'


def test_build_query_combines_labels_and_unread() -> None:
    from ghostbrain.connectors.gmail.connector import (
        GmailAccountConfig,
        _build_query,
    )
    acc = GmailAccountConfig(
        email="x@y.com",
        monitored_labels=["sanlam/policies", "codeship"],
        unread_lookback_hours=24,
    )
    q = _build_query(acc)
    assert "label:sanlam/policies" in q
    assert "label:codeship" in q
    assert "is:unread newer_than:1d" in q
    # Two filters joined by OR.
    assert " OR " in q


def test_build_query_unread_only_when_no_labels() -> None:
    from ghostbrain.connectors.gmail.connector import (
        GmailAccountConfig,
        _build_query,
    )
    acc = GmailAccountConfig(email="x@y.com", monitored_labels=[])
    q = _build_query(acc)
    assert q == "is:unread newer_than:1d"


def test_build_query_multi_day_lookback() -> None:
    from ghostbrain.connectors.gmail.connector import (
        GmailAccountConfig,
        _build_query,
    )
    acc = GmailAccountConfig(
        email="x@y.com", monitored_labels=[], unread_lookback_hours=72,
    )
    q = _build_query(acc)
    assert "newer_than:3d" in q


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def _b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode("utf-8")).rstrip(b"=").decode()


def _make_thread(
    *,
    thread_id: str = "t-1",
    subject: str = "Hello",
    from_addr: str = "alex@sanlam.co.za",
    to_addr: str = "jannik@example.com",
    body: str = "Body text here.",
    labels: list[str] | None = None,
    internal_date_ms: int = 1715000000000,
    msg_count: int = 1,
) -> dict:
    labels = labels or ["INBOX", "UNREAD"]
    msgs = []
    for i in range(msg_count):
        msgs.append({
            "id": f"m-{i}",
            "threadId": thread_id,
            "labelIds": labels,
            "snippet": "A snippet…",
            "internalDate": str(internal_date_ms + i),
            "payload": {
                "mimeType": "text/plain",
                "headers": [
                    {"name": "Subject", "value": subject},
                    {"name": "From", "value": f"Alex <{from_addr}>"},
                    {"name": "To", "value": to_addr},
                ],
                "body": {"data": _b64(body)},
            },
        })
    return {"id": thread_id, "messages": msgs}


def test_normalize_thread_pulls_headers_and_body() -> None:
    from ghostbrain.connectors.gmail.connector import _normalize_thread

    raw = _make_thread(subject="Beneficiaries query", body="Need foreign ID")
    ev = _normalize_thread(raw, account="me@example.com")

    assert ev["id"] == "gmail:thread:t-1"
    assert ev["source"] == "gmail"
    assert ev["type"] == "email_thread"
    assert ev["title"] == "Beneficiaries query"
    assert ev["body"] == "Need foreign ID"
    md = ev["metadata"]
    assert md["from_address"] == "alex@sanlam.co.za"
    assert md["from_domain"] == "sanlam.co.za"
    assert md["to"] == ["jannik@example.com"]
    assert md["account"] == "me@example.com"
    assert md["is_unread"] is True


def test_normalize_thread_marks_read_when_unread_label_absent() -> None:
    from ghostbrain.connectors.gmail.connector import _normalize_thread
    raw = _make_thread(labels=["INBOX"])
    ev = _normalize_thread(raw, account="me@example.com")
    assert ev["metadata"]["is_unread"] is False
    assert ev["subtype"] == "read"


def test_normalize_thread_uses_latest_message_for_top_level() -> None:
    from ghostbrain.connectors.gmail.connector import _normalize_thread

    raw = {
        "id": "t-2",
        "messages": [
            {
                "id": "m-old",
                "threadId": "t-2",
                "labelIds": ["INBOX"],
                "snippet": "old",
                "internalDate": "1714000000000",
                "payload": {
                    "mimeType": "text/plain",
                    "headers": [
                        {"name": "Subject", "value": "Original"},
                        {"name": "From", "value": "first@x.com"},
                    ],
                    "body": {"data": _b64("first message")},
                },
            },
            {
                "id": "m-new",
                "threadId": "t-2",
                "labelIds": ["INBOX", "UNREAD"],
                "snippet": "new",
                "internalDate": "1714999999999",
                "payload": {
                    "mimeType": "text/plain",
                    "headers": [
                        {"name": "Subject", "value": "Re: Original"},
                        {"name": "From", "value": "second@x.com"},
                    ],
                    "body": {"data": _b64("reply body")},
                },
            },
        ],
    }
    ev = _normalize_thread(raw, account="me@example.com")
    assert ev["title"] == "Re: Original"
    assert ev["metadata"]["from_address"] == "second@x.com"
    assert ev["metadata"]["msg_count"] == 2
    assert ev["body"] == "reply body"


def test_normalize_thread_handles_multipart_html() -> None:
    from ghostbrain.connectors.gmail.connector import _normalize_thread

    raw = {
        "id": "t-3",
        "messages": [{
            "id": "m-3",
            "threadId": "t-3",
            "labelIds": ["INBOX"],
            "snippet": "html only",
            "internalDate": "1715000000000",
            "payload": {
                "mimeType": "multipart/alternative",
                "headers": [
                    {"name": "Subject", "value": "HTML newsletter"},
                    {"name": "From", "value": "news@x.com"},
                ],
                "parts": [
                    {
                        "mimeType": "text/html",
                        "body": {"data": _b64("<p>Hello <b>world</b></p>")},
                    },
                ],
            },
        }],
    }
    ev = _normalize_thread(raw, account="me@example.com")
    assert "Hello" in ev["body"]
    assert "world" in ev["body"]
    assert "<p>" not in ev["body"]


# ---------------------------------------------------------------------------
# Fetch via mocked service
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_service():
    """A google API client double that records calls and returns canned
    responses set on the fixture."""
    svc = MagicMock()
    return svc


def test_fetch_skips_when_no_accounts(tmp_path: Path) -> None:
    from ghostbrain.connectors.gmail import GmailConnector

    c = GmailConnector(
        config={"accounts": {}},
        queue_dir=tmp_path / "q",
        state_dir=tmp_path / "s",
    )
    assert c.fetch(datetime.now(timezone.utc)) == []


def test_fetch_one_account_normalizes_threads(
    tmp_path: Path,
    fake_service: MagicMock,
) -> None:
    from ghostbrain.connectors.gmail import GmailConnector

    fake_service.users().threads().list().execute.return_value = {
        "threads": [{"id": "t-1"}, {"id": "t-2"}],
    }

    def _get(*, userId, id, format):  # noqa: N803, A002
        return MagicMock(execute=MagicMock(return_value=_make_thread(
            thread_id=id, subject=f"Subject {id}",
        )))
    fake_service.users().threads().get.side_effect = _get

    c = GmailConnector(
        config={"accounts": {"me@example.com": {
            "monitored_labels": ["sanlam"],
        }}},
        queue_dir=tmp_path / "q",
        state_dir=tmp_path / "s",
        service=fake_service,
    )

    events = c.fetch(datetime.now(timezone.utc))
    assert len(events) == 2
    assert {e["metadata"]["thread_id"] for e in events} == {"t-1", "t-2"}
    for e in events:
        assert e["source"] == "gmail"
        assert e["metadata"]["account"] == "me@example.com"


# ---------------------------------------------------------------------------
# Routing fast paths
# ---------------------------------------------------------------------------


def test_router_routes_by_sender_domain() -> None:
    from ghostbrain.worker.router import _fast_route

    event = {
        "source": "gmail",
        "id": "gmail:thread:abc",
        "metadata": {
            "from_domain": "sanlam.co.za",
            "labels": ["INBOX"],
        },
    }
    routing = {"gmail": {"sender_domains": {"sanlam.co.za": "sanlam"}}}
    decision = _fast_route(event, routing)
    assert decision is not None
    assert decision.context == "sanlam"
    assert decision.method == "path"
    assert decision.confidence == 1.0


def test_router_routes_by_label_prefix() -> None:
    from ghostbrain.worker.router import _fast_route

    event = {
        "source": "gmail",
        "id": "gmail:thread:abc",
        "metadata": {
            "from_domain": "alex@gmail.com",
            "labels": ["INBOX", "sanlam/policies"],
        },
    }
    routing = {"gmail": {"label_prefixes": {"sanlam/": "sanlam"}}}
    decision = _fast_route(event, routing)
    assert decision is not None
    assert decision.context == "sanlam"
    assert decision.method == "path"


def test_router_falls_through_to_llm_when_no_gmail_rule_matches() -> None:
    from ghostbrain.worker.router import _fast_route

    event = {
        "source": "gmail",
        "id": "gmail:thread:abc",
        "metadata": {
            "from_domain": "stranger@nowhere.com",
            "labels": ["INBOX"],
        },
    }
    routing = {"gmail": {
        "sender_domains": {"sanlam.co.za": "sanlam"},
        "label_prefixes": {"sanlam/": "sanlam"},
    }}
    assert _fast_route(event, routing) is None


def test_router_sender_domain_beats_label_prefix() -> None:
    """When both rules would match, sender_domain wins because its signal
    is stronger (legit sanlam.co.za email vs. user-applied label)."""
    from ghostbrain.worker.router import _fast_route

    event = {
        "source": "gmail",
        "id": "gmail:thread:abc",
        "metadata": {
            "from_domain": "sanlam.co.za",
            "labels": ["INBOX", "codeship/internal"],
        },
    }
    routing = {"gmail": {
        "sender_domains": {"sanlam.co.za": "sanlam"},
        "label_prefixes": {"codeship/": "codeship"},
    }}
    decision = _fast_route(event, routing)
    assert decision is not None
    assert decision.context == "sanlam"
