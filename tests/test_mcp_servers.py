"""Config store for user MCP servers opted into chat (~/ghostbrain/mcp-servers.json)."""
from __future__ import annotations

import json

import pytest

from ghostbrain.llm import mcp_servers


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "mcp-servers.json"
    monkeypatch.setattr(mcp_servers, "config_path", lambda: path)
    return path


GOOD = {
    "name": "mempalace",
    "command": "npx",
    "args": ["-y", "mempalace-mcp"],
    "env": {"KEY": "secret"},
    "enabled": True,
    "tools": "",
}


def test_load_missing_file_is_empty(store):
    assert mcp_servers.load() == []


def test_save_load_round_trip(store):
    saved = mcp_servers.save([GOOD])
    assert saved[0]["name"] == "mempalace"
    loaded = mcp_servers.load()
    assert loaded == saved
    assert loaded[0]["env"] == {"KEY": "secret"}


def test_save_normalizes_defaults(store):
    saved = mcp_servers.save([{"name": "x", "command": "bin", "enabled": False}])
    assert saved[0]["args"] == []
    assert saved[0]["env"] == {}
    assert saved[0]["tools"] == ""


def test_corrupt_file_is_empty(store):
    store.write_text("{nope")
    assert mcp_servers.load() == []


def test_load_enabled_filters(store):
    mcp_servers.save([GOOD, {**GOOD, "name": "other", "enabled": False}])
    assert [s["name"] for s in mcp_servers.load_enabled()] == ["mempalace"]


@pytest.mark.parametrize(
    "patch,fragment",
    [
        ({"name": "Bad Name"}, "name"),
        ({"name": "poltergeist"}, "reserved"),
        ({"name": ""}, "name"),
        ({"command": ""}, "command"),
        ({"args": "not-a-list"}, "args"),
        ({"env": {"K": 1}}, "env"),
    ],
)
def test_validate_rejects(patch, fragment):
    errors = mcp_servers.validate({**GOOD, **patch})
    assert errors and fragment in " ".join(errors).lower()


def test_validate_accepts_good():
    assert mcp_servers.validate(GOOD) == []


def test_save_rejects_invalid(store):
    with pytest.raises(ValueError, match="reserved"):
        mcp_servers.save([{**GOOD, "name": "poltergeist"}])
    assert mcp_servers.load() == []


def test_save_rejects_duplicate_names(store):
    with pytest.raises(ValueError, match="duplicate"):
        mcp_servers.save([GOOD, {**GOOD}])


def test_redact_strips_env_values(store):
    mcp_servers.save([GOOD])
    red = mcp_servers.redact(mcp_servers.load())
    assert "env" not in red[0]
    assert red[0]["envKeys"] == ["KEY"]
    # original untouched
    assert mcp_servers.load()[0]["env"] == {"KEY": "secret"}
