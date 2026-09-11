from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

from ghostbrain.api import claude_settings as cs
from ghostbrain.doctor.fixes import hook


def _entry(cmd: str) -> dict:
    return {"matcher": "*", "hooks": [{"type": "command", "command": cmd, "async": True}]}


def test_install_adds_entry_once(tmp_path: Path):
    cmd = f'"{tmp_path / "bin"}" session-end'
    (tmp_path / "bin").write_text("")
    doc = hook.install({}, cmd)
    assert doc["hooks"]["SessionEnd"] == [_entry(cmd)]
    assert hook.install(doc, cmd)["hooks"]["SessionEnd"] == [_entry(cmd)]


def test_install_drops_stale_poltergeist_entries_keeps_others(tmp_path: Path):
    ok_bin = tmp_path / "bin"
    ok_bin.write_text("")
    doc = {"hooks": {"SessionEnd": [
        _entry("/Users/dev/development/ghost-brain/orchestration/hooks/session-end.sh"),
        _entry("/usr/local/bin/my-other-hook.sh"),
    ], "PreToolUse": [_entry("keep")]}, "theme": "dark"}
    new = hook.install(doc, f'"{ok_bin}" session-end')
    cmds = cs.session_end_commands(new)
    assert cmds == ["/usr/local/bin/my-other-hook.sh", f'"{ok_bin}" session-end']
    assert new["hooks"]["PreToolUse"] == [_entry("keep")]
    assert new["theme"] == "dark"


def test_main_writes_settings_and_is_idempotent(tmp_path: Path, monkeypatch, capsys):
    p = tmp_path / ".claude" / "settings.json"
    monkeypatch.setattr(cs, "settings_path", lambda: p)
    monkeypatch.setattr(hook, "hook_command", lambda: '"/App/ghostbrain-api" session-end')
    assert hook.main([]) == 0
    assert cs.session_end_commands(json.loads(p.read_text())) == ['"/App/ghostbrain-api" session-end']
    assert hook.main([]) == 0
    assert "already" in capsys.readouterr().out


def test_main_refuses_invalid_json(tmp_path: Path, monkeypatch, capsys):
    p = tmp_path / "settings.json"
    p.write_text("{broken")
    monkeypatch.setattr(cs, "settings_path", lambda: p)
    assert hook.main([]) == 1
    assert "not valid JSON" in capsys.readouterr().err
    assert p.read_text() == "{broken"


def test_hook_command_frozen_uses_the_bundled_executable(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/Applications/Poltergeist.app/x/ghostbrain-api")
    assert hook.hook_command() == shlex.join(["/Applications/Poltergeist.app/x/ghostbrain-api", "session-end"])


def test_hook_command_source_install_uses_the_module_form(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    python = tmp_path / "python"
    python.write_text("")
    monkeypatch.setattr(sys, "executable", str(python))
    assert hook.hook_command() == shlex.join([str(python), "-m", "ghostbrain.api", "session-end"])
    assert hook.hook_command().endswith("-m ghostbrain.api session-end")
