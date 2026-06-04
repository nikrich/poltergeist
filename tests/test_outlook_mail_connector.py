"""Tests for the Outlook mail connector. GraphClient + gate are injected."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock


def _conn(tmp_path, client, *, gate=None, denylist=None):
    from ghostbrain.connectors.microsoft.outlook_mail.connector import (
        OutlookMailConnector,
    )
    return OutlookMailConnector(
        config={
            "unread_lookback_hours": 24,
            "denylist_domains": denylist or [],
            "relevance_gate": gate is not None,
            "max_messages_per_run": 50,
        },
        queue_dir=tmp_path / "q",
        state_dir=tmp_path / "s",
        client=client,
        relevance_gate=gate,
    )


def _msg(mid, sender, subject="Hi", read=False):
    return {
        "id": mid,
        "subject": subject,
        "isRead": read,
        "receivedDateTime": "2026-06-04T09:00:00Z",
        "bodyPreview": "preview text",
        "from": {"emailAddress": {"address": sender, "name": "Someone"}},
        "toRecipients": [{"emailAddress": {"address": "me@sanlam.com"}}],
        "webLink": "https://outlook/x",
    }


def test_normalize_message_shape(tmp_path) -> None:
    from ghostbrain.connectors.microsoft.outlook_mail.connector import _normalize_message
    ev = _normalize_message(_msg("a1", "boss@sanlam.com"), body_cap=4000)
    assert ev["id"] == "microsoft:mail:a1"
    assert ev["source"] == "outlook_mail"
    assert ev["type"] == "email"
    assert ev["metadata"]["from_domain"] == "sanlam.com"
    assert ev["actorId"] == "microsoft:boss@sanlam.com"


def test_fetch_applies_denylist(tmp_path) -> None:
    client = MagicMock()
    client.get_all.return_value = [
        _msg("a", "ok@sanlam.com"),
        _msg("b", "spam@noisy.com"),
    ]
    conn = _conn(tmp_path, client, denylist=["noisy.com"])
    events = conn.fetch(datetime(2026, 6, 3, tzinfo=timezone.utc))
    assert [e["metadata"]["from_address"] for e in events] == ["ok@sanlam.com"]


def test_fetch_applies_relevance_gate(tmp_path) -> None:
    client = MagicMock()
    client.get_all.return_value = [
        _msg("a", "boss@sanlam.com", subject="Project update"),
        _msg("b", "newsletter@sanlam.com", subject="Weekly digest"),
    ]

    def gate(ev):
        return ("digest" not in ev["title"].lower(), "r")

    conn = _conn(tmp_path, client, gate=gate)
    events = conn.fetch(datetime(2026, 6, 3, tzinfo=timezone.utc))
    assert [e["id"] for e in events] == ["microsoft:mail:a"]


def test_health_check_false_without_token(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "ghostbrain.connectors.microsoft.outlook_mail.connector.have_token",
        lambda cfg: False,
    )
    conn = _conn(tmp_path, MagicMock())
    assert conn.health_check() is False
