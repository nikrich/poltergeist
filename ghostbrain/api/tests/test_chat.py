"""Chat routes: CRUD + SSE message streaming (agent faked)."""
from __future__ import annotations

import json

import pytest


def sse_events(body: str) -> list[dict]:
    return [
        json.loads(line[len("data: "):])
        for line in body.splitlines()
        if line.startswith("data: ")
    ]


def test_crud_roundtrip(client, tmp_chats_dir, auth_headers):
    created = client.post("/v1/chat", headers=auth_headers).json()
    assert created["title"] == "new chat"

    listed = client.get("/v1/chat", headers=auth_headers).json()
    assert [c["id"] for c in listed] == [created["id"]]

    got = client.get(f"/v1/chat/{created['id']}", headers=auth_headers).json()
    assert got["messages"] == []

    renamed = client.patch(
        f"/v1/chat/{created['id']}", json={"title": "my chat"}, headers=auth_headers
    ).json()
    assert renamed["title"] == "my chat"

    assert (
        client.delete(f"/v1/chat/{created['id']}", headers=auth_headers).status_code
        == 200
    )
    assert client.get(f"/v1/chat/{created['id']}", headers=auth_headers).status_code == 404


def test_missing_conversation_404s(client, tmp_chats_dir, auth_headers):
    assert client.get("/v1/chat/nope", headers=auth_headers).status_code == 404
    assert (
        client.patch("/v1/chat/nope", json={"title": "x"}, headers=auth_headers).status_code
        == 404
    )
    assert client.delete("/v1/chat/nope", headers=auth_headers).status_code == 404
    assert (
        client.post(
            "/v1/chat/nope/messages", json={"text": "hi"}, headers=auth_headers
        ).status_code
        == 404
    )


def test_send_message_streams_sse(client, tmp_chats_dir, auth_headers, monkeypatch):
    def fake_turn(prompt, *, session_id=None, **kw):
        yield {"type": "session", "session_id": "s-1"}
        yield {"type": "delta", "text": "hel"}
        yield {"type": "delta", "text": "lo"}
        yield {"type": "done", "text": "hello", "session_id": "s-1"}

    monkeypatch.setattr("ghostbrain.api.repo.chat.agent.run_chat_turn", fake_turn)

    conv = client.post("/v1/chat", headers=auth_headers).json()
    resp = client.post(
        f"/v1/chat/{conv['id']}/messages", json={"text": "say hello"}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = sse_events(resp.text)
    assert [e["type"] for e in events] == ["session", "delta", "delta", "done"]

    # persisted side effects
    got = client.get(f"/v1/chat/{conv['id']}", headers=auth_headers).json()
    assert got["claude_session_id"] == "s-1"
    assert [m["role"] for m in got["messages"]] == ["user", "assistant"]
    assert got["messages"][1]["text"] == "hello"


def test_send_message_validates_text(client, tmp_chats_dir, auth_headers):
    conv = client.post("/v1/chat", headers=auth_headers).json()
    resp = client.post(
        f"/v1/chat/{conv['id']}/messages", json={"text": ""}, headers=auth_headers
    )
    assert resp.status_code == 422


def test_stop_turn_idle_returns_false(client, tmp_chats_dir, auth_headers):
    """POST /{id}/stop on an idle conversation returns {"stopped": false}."""
    conv = client.post("/v1/chat", headers=auth_headers).json()
    resp = client.post(f"/v1/chat/{conv['id']}/stop", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"stopped": False}


def test_stop_turn_active_returns_true(client, tmp_chats_dir, auth_headers, monkeypatch):
    """When the turn is in-flight, cancel() is called and returns {"stopped": true}."""
    import ghostbrain.api.repo.chat as repo_chat

    monkeypatch.setattr(repo_chat.agent, "cancel_turn", lambda conv_id: True)

    conv = client.post("/v1/chat", headers=auth_headers).json()
    resp = client.post(f"/v1/chat/{conv['id']}/stop", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"stopped": True}


def test_export_route(client, tmp_chats_dir, auth_headers, monkeypatch):
    conv = client.post("/v1/chat", headers=auth_headers).json()
    monkeypatch.setattr(
        "ghostbrain.api.routes.chat.repo_chat_export.export_conversation",
        lambda conv_id: {"jot_id": "j1", "path": "p", "routingStatus": "routed",
                         "context": "codeship", "project": None, "title": "t"},
    )
    r = client.post(f"/v1/chat/{conv['id']}/export-jot", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["jot_id"] == "j1"


def test_export_route_maps_errors(client, tmp_chats_dir, auth_headers):
    assert (
        client.post("/v1/chat/nope/export-jot", headers=auth_headers).status_code == 404
    )
