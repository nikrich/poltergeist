from __future__ import annotations

import json
from pathlib import Path

import pytest

from ghostbrain.api import claude_settings as cs


def test_load_missing_is_empty_and_invalid_raises(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(cs, "settings_path", lambda: tmp_path / "settings.json")
    assert cs.load() == {}
    (tmp_path / "settings.json").write_text("{nope")
    with pytest.raises(ValueError):
        cs.load()


def test_write_atomic_roundtrip(tmp_path: Path, monkeypatch):
    p = tmp_path / ".claude" / "settings.json"
    monkeypatch.setattr(cs, "settings_path", lambda: p)
    cs.write_atomic({"hooks": {}})
    assert json.loads(p.read_text()) == {"hooks": {}}
    assert not list(p.parent.glob(".settings.*"))


def test_session_end_commands_and_existence(tmp_path: Path):
    script = tmp_path / "session-end.sh"
    script.write_text("#!/bin/sh\n")
    doc = {"hooks": {"SessionEnd": [
        {"matcher": "*", "hooks": [{"type": "command", "command": f"{script} --flag"}]},
        {"matcher": "*", "hooks": [{"type": "command", "command": "/nonexistent/hook.sh"}]},
    ]}}
    cmds = cs.session_end_commands(doc)
    assert cmds == [f"{script} --flag", "/nonexistent/hook.sh"]
    assert cs.hook_command_exists(cmds[0]) is True
    assert cs.hook_command_exists(cmds[1]) is False
    assert cs.session_end_commands({}) == []
