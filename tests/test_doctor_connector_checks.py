from __future__ import annotations

from pathlib import Path

from ghostbrain.api import claude_settings as cs
from ghostbrain.api.repo.connector_probe import ProbeResult
from ghostbrain.doctor import checks_connectors as cc


def test_connectors_flags_on_but_empty(monkeypatch):
    monkeypatch.setattr(cc, "_routing", lambda: {
        "github": {"orgs": {}},
        "slack": {"workspaces": {"acme": {"context": "work"}}},
        "gmail": {"accounts": {}},
    })
    states = {"github": "on", "slack": "on", "gmail": "off"}
    monkeypatch.setattr(cc, "_probe", lambda cid: ProbeResult(states.get(cid, "off")))
    r = cc.check_connectors()
    assert r.status == "fail"
    assert r.data["on_but_empty"] == ["github"]
    assert r.data["configured"] == ["slack"]
    assert "github" in r.summary


def test_connectors_all_good(monkeypatch):
    monkeypatch.setattr(cc, "_routing", lambda: {"slack": {"workspaces": {"acme": {"context": "work"}}}})
    monkeypatch.setattr(cc, "_probe", lambda cid: ProbeResult("on"))
    r = cc.check_connectors()
    assert r.status == "ok"
    assert r.data["configured"] == ["slack"]


def test_connectors_none_configured_is_warn(monkeypatch):
    monkeypatch.setattr(cc, "_routing", lambda: {"github": {"orgs": {}}})
    monkeypatch.setattr(cc, "_probe", lambda cid: ProbeResult("off"))
    assert cc.check_connectors().status == "warn"


def test_claude_hook_missing_stale_and_ok(monkeypatch, tmp_path: Path):
    p = tmp_path / "settings.json"
    monkeypatch.setattr(cs, "settings_path", lambda: p)
    r = cc.check_claude_hook()
    assert r.status == "fail"
    assert r.fix.command == "setup install-hook"

    p.write_text('{"hooks": {"SessionEnd": [{"matcher": "*", "hooks": [{"type": "command", "command": "/gone/session-end.sh"}]}]}}')
    r = cc.check_claude_hook()
    assert r.status == "fail"
    assert "/gone/session-end.sh" in r.detail

    script = tmp_path / "ok.sh"
    script.write_text("")
    p.write_text('{"hooks": {"SessionEnd": [{"matcher": "*", "hooks": [{"type": "command", "command": "%s"}]}]}}' % script)
    assert cc.check_claude_hook().status == "ok"


def test_cli_shim(monkeypatch):
    monkeypatch.setattr(cc.shutil, "which", lambda n: None)
    r = cc.check_cli_shim()
    assert r.status == "warn"
    assert r.fix.command == "setup cli-shim"
    monkeypatch.setattr(cc.shutil, "which", lambda n: "/usr/local/bin/poltergeist")
    assert cc.check_cli_shim().status == "ok"
