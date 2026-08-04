"""GET/PUT /v1/chat/mcp-servers — user MCP servers opted into chat."""
import json

import pytest

from ghostbrain.llm import mcp_servers


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "mcp-servers.json"
    monkeypatch.setattr(mcp_servers, "config_path", lambda: path)
    return path


@pytest.fixture
def claude_json(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(
        "ghostbrain.api.routes.mcp_servers.claude_config_path",
        lambda: home / ".claude.json",
    )
    return home / ".claude.json"


SAVED = {
    "name": "mempalace",
    "command": "npx",
    "args": ["-y", "mempalace-mcp"],
    "env": {"KEY": "secret"},
    "enabled": True,
    "tools": "",
}


def test_get_empty(client, auth_headers, store, claude_json):
    r = client.get("/v1/chat/mcp-servers", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == {"servers": [], "available": []}


def test_get_lists_available_from_claude_json(client, auth_headers, store, claude_json):
    claude_json.write_text(json.dumps({
        "mcpServers": {
            "mempalace": {"command": "npx", "args": ["-y", "mempalace-mcp"]},
            "Bad Name": {"command": "x"},
            "remote": {"type": "sse", "url": "https://x"},
        }
    }))
    r = client.get("/v1/chat/mcp-servers", headers=auth_headers)
    body = r.json()
    assert body["available"] == [
        {"name": "mempalace", "command": "npx", "args": ["-y", "mempalace-mcp"]}
    ]


def test_available_skips_already_saved(client, auth_headers, store, claude_json):
    mcp_servers.save([SAVED])
    claude_json.write_text(json.dumps({"mcpServers": {"mempalace": {"command": "npx"}}}))
    body = client.get("/v1/chat/mcp-servers", headers=auth_headers).json()
    assert body["available"] == []
    assert body["servers"][0]["name"] == "mempalace"


def test_put_saves_and_redacts(client, auth_headers, store, claude_json):
    r = client.put("/v1/chat/mcp-servers", headers=auth_headers, json={"servers": [SAVED]})
    assert r.status_code == 200
    body = r.json()["servers"][0]
    assert body["envKeys"] == ["KEY"]
    assert "env" not in body
    # values persisted on disk though
    assert mcp_servers.load()[0]["env"] == {"KEY": "secret"}


def test_get_redacts_env(client, auth_headers, store, claude_json):
    mcp_servers.save([SAVED])
    body = client.get("/v1/chat/mcp-servers", headers=auth_headers).json()
    assert body["servers"][0]["envKeys"] == ["KEY"]
    assert "env" not in body["servers"][0]


def test_put_env_null_preserves_stored_env(client, auth_headers, store, claude_json):
    mcp_servers.save([SAVED])
    updated = {**SAVED, "env": None, "enabled": False}
    r = client.put("/v1/chat/mcp-servers", headers=auth_headers, json={"servers": [updated]})
    assert r.status_code == 200
    stored = mcp_servers.load()[0]
    assert stored["env"] == {"KEY": "secret"}
    assert stored["enabled"] is False


def test_put_reserved_name_422(client, auth_headers, store, claude_json):
    r = client.put(
        "/v1/chat/mcp-servers",
        headers=auth_headers,
        json={"servers": [{**SAVED, "name": "poltergeist"}]},
    )
    assert r.status_code == 422
    assert "reserved" in json.dumps(r.json())
