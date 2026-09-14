from __future__ import annotations

import json
from pathlib import Path

import pytest

from ghostbrain.doctor import checks_app as ca
from ghostbrain.doctor import desktop_config


def test_desktop_config_path_per_platform(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(desktop_config, "_platform", lambda: "darwin")
    assert desktop_config.path() == Path.home() / "Library" / "Application Support" / "ghostbrain-desktop" / "config.json"
    monkeypatch.setattr(desktop_config, "_platform", lambda: "linux")
    assert desktop_config.path() == Path.home() / ".config" / "ghostbrain-desktop" / "config.json"
    monkeypatch.setattr(desktop_config, "_platform", lambda: "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    assert desktop_config.path() == tmp_path / "AppData" / "Roaming" / "ghostbrain-desktop" / "config.json"


def test_desktop_config_load_tolerates_missing_and_garbage(monkeypatch, tmp_path: Path):
    p = tmp_path / "config.json"
    monkeypatch.setattr(desktop_config, "path", lambda: p)
    assert desktop_config.load() == {}
    p.write_text("{not json")
    assert desktop_config.load() == {}
    p.write_text(json.dumps({"schedulerEnabled": True}))
    assert desktop_config.load() == {"schedulerEnabled": True}


def test_app_not_installed(monkeypatch):
    monkeypatch.setattr(ca, "_app_installed", lambda: False)
    r = ca.check_app()
    assert r.status == "fail"
    assert "Poltergeist.app" in r.summary
    assert r.fix.kind == "manual"


def test_app_installed_but_not_running(monkeypatch):
    monkeypatch.setattr(ca, "_app_installed", lambda: True)
    monkeypatch.setattr(ca, "_app_process_running", lambda: False)
    monkeypatch.setattr(ca, "_descriptor", lambda: None)
    r = ca.check_app()
    assert r.status == "fail"
    assert "open Poltergeist" in r.fix.command


def test_app_running_but_sidecar_unpublished_is_the_relaunch_race(monkeypatch):
    monkeypatch.setattr(ca, "_app_installed", lambda: True)
    monkeypatch.setattr(ca, "_app_process_running", lambda: True)
    monkeypatch.setattr(ca, "_descriptor", lambda: None)
    r = ca.check_app()
    assert r.status == "fail"
    assert "quit" in r.fix.command.lower() and "reopen" in r.fix.command.lower()


def test_app_healthy(monkeypatch):
    monkeypatch.setattr(ca, "_app_installed", lambda: True)
    monkeypatch.setattr(ca, "_app_process_running", lambda: True)
    monkeypatch.setattr(ca, "_descriptor", lambda: {"port": 4242, "token": "t", "pid": 1})
    monkeypatch.setattr(ca, "_health_ok", lambda port, token: True)
    r = ca.check_app()
    assert r.status == "ok"
    assert r.data == {"port": 4242}


def test_vault_missing_marker_and_desktop_mismatch(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path / "vault"))
    monkeypatch.setattr(desktop_config, "load", lambda: {})
    r = ca.check_vault()
    assert r.status == "fail"
    assert r.fix.command == "setup bootstrap"

    (tmp_path / "vault" / "90-meta").mkdir(parents=True)
    (tmp_path / "vault" / "90-meta" / "routing.yaml").write_text("contexts: [personal]\n")
    assert ca.check_vault().status == "ok"

    monkeypatch.setattr(desktop_config, "load", lambda: {"vaultPath": str(tmp_path / "other")})
    r = ca.check_vault()
    assert r.status == "warn"
    assert "other" in r.detail


def test_contexts_empty_vs_present(monkeypatch):
    monkeypatch.setattr(ca, "_contexts", lambda: ())
    assert ca.check_contexts().status == "fail"
    monkeypatch.setattr(ca, "_contexts", lambda: ("personal", "work"))
    r = ca.check_contexts()
    assert r.status == "ok"
    assert r.data["contexts"] == ["personal", "work"]


def test_claude_cli(monkeypatch):
    monkeypatch.setattr(ca.shutil, "which", lambda n: None)
    r = ca.check_claude_cli()
    assert r.status == "fail"
    assert "claude.ai" in r.fix.command or "npm install -g @anthropic-ai/claude-code" in r.fix.command
    monkeypatch.setattr(ca.shutil, "which", lambda n: "/usr/local/bin/claude")
    monkeypatch.setattr(ca, "_claude_version", lambda: "2.1.0")
    assert ca.check_claude_cli().status == "ok"


def test_scheduler_from_desktop_config(monkeypatch):
    monkeypatch.setattr(desktop_config, "load", lambda: {"schedulerEnabled": False})
    r = ca.check_scheduler()
    assert r.status == "fail"
    assert "Run scheduler in-app" in r.fix.command
    monkeypatch.setattr(desktop_config, "load", lambda: {"schedulerEnabled": True})
    assert ca.check_scheduler().status == "ok"
    monkeypatch.setattr(desktop_config, "load", lambda: {})
    assert ca.check_scheduler().status == "warn"


def test_routing_mode_counts_inbox(monkeypatch, tmp_path: Path):
    vault = tmp_path / "vault"
    monkeypatch.setenv("VAULT_PATH", str(vault))
    (vault / "90-meta").mkdir(parents=True)
    (vault / "00-inbox" / "raw").mkdir(parents=True)
    (vault / "90-meta" / "config.yaml").write_text("worker:\n  routing_mode: review_only\n")
    for i in range(3):
        (vault / "00-inbox" / "raw" / f"n{i}.md").write_text("x")
    r = ca.check_routing_mode()
    assert r.status == "warn"
    assert r.data == {"mode": "review_only", "inbox_count": 3}
    assert r.fix.command == "setup go-live"
    (vault / "90-meta" / "config.yaml").write_text("worker:\n  routing_mode: live\n")
    assert ca.check_routing_mode().status == "ok"
