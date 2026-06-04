"""Tests for the Teams chat connector. GraphClient + gate are injected."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock


def _conn(tmp_path, client, *, gate=None):
    from ghostbrain.connectors.microsoft.teams_chat.connector import TeamsChatConnector
    return TeamsChatConnector(
        config={"max_messages_per_run": 100, "relevance_gate": gate is not None},
        queue_dir=tmp_path / "q",
        state_dir=tmp_path / "s",
        client=client,
        relevance_gate=gate,
    )


def _chat_msg(mid, body, created="2026-06-04T09:00:00Z", mtype="message"):
    return {
        "id": mid,
        "messageType": mtype,
        "createdDateTime": created,
        "body": {"content": body, "contentType": "text"},
        "from": {"user": {"id": "u1", "displayName": "Alice"}},
    }


def test_normalize_chat_message_shape(tmp_path) -> None:
    from ghostbrain.connectors.microsoft.teams_chat.connector import _normalize_message
    ev = _normalize_message(
        chat={"id": "c1", "chatType": "oneOnOne", "topic": None,
              "webUrl": "https://teams/c1"},
        msg=_chat_msg("m1", "hello there"),
    )
    assert ev["id"] == "microsoft:chat:c1:m1"
    assert ev["source"] == "teams_chat"
    assert ev["type"] == "chat_message"
    assert ev["body"] == "hello there"
    assert ev["metadata"]["chatType"] == "oneOnOne"


def test_fetch_drops_system_messages(tmp_path) -> None:
    client = MagicMock()
    client.get_all.side_effect = [
        # /me/chats
        [{"id": "c1", "chatType": "group", "topic": "Team", "webUrl": "u",
          "lastUpdatedDateTime": "2026-06-04T10:00:00Z"}],
        # /me/chats/c1/messages
        [
            _chat_msg("m1", "real message"),
            _chat_msg("sys", "joined", mtype="systemEventMessage"),
        ],
    ]
    conn = _conn(tmp_path, client)
    events = conn.fetch(datetime(2026, 6, 3, tzinfo=timezone.utc))
    assert [e["id"] for e in events] == ["microsoft:chat:c1:m1"]


def test_fetch_filters_messages_by_since(tmp_path) -> None:
    client = MagicMock()
    client.get_all.side_effect = [
        [{"id": "c1", "chatType": "oneOnOne", "webUrl": "u",
          "lastUpdatedDateTime": "2026-06-04T10:00:00Z"}],
        [
            _chat_msg("old", "old", created="2026-06-01T09:00:00Z"),
            _chat_msg("new", "new", created="2026-06-04T09:00:00Z"),
        ],
    ]
    conn = _conn(tmp_path, client)
    events = conn.fetch(datetime(2026, 6, 3, tzinfo=timezone.utc))
    assert [e["id"] for e in events] == ["microsoft:chat:c1:new"]


def test_health_check_false_without_token(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "ghostbrain.connectors.microsoft.teams_chat.connector.have_token",
        lambda cfg: False,
    )
    conn = _conn(tmp_path, MagicMock())
    assert conn.health_check() is False
