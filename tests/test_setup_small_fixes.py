from __future__ import annotations

import os
from pathlib import Path

from ghostbrain.doctor.fixes import bootstrap as bs
from ghostbrain.doctor.fixes import cli_shim, go_live


def test_cli_shim_writes_exec_wrapper_to_first_writable_dir(tmp_path: Path, monkeypatch, capsys):
    unwritable = tmp_path / "usr-local-bin"
    local = tmp_path / "local-bin"
    monkeypatch.setattr(cli_shim, "CANDIDATES", lambda: [unwritable, local])
    monkeypatch.setattr(cli_shim, "_writable", lambda d: d == local)
    monkeypatch.setattr(cli_shim, "binary_path", lambda: "/Applications/P.app/ghostbrain-api")
    monkeypatch.setenv("PATH", "/usr/bin")
    assert cli_shim.main([]) == 0
    shim = local / "poltergeist"
    assert shim.read_text() == '#!/bin/sh\nexec "/Applications/P.app/ghostbrain-api" "$@"\n'
    assert os.access(shim, os.X_OK)
    assert "add" in capsys.readouterr().out  # PATH hint because local is not on PATH


def test_cli_shim_is_idempotent(tmp_path: Path, monkeypatch, capsys):
    d = tmp_path / "bin"
    monkeypatch.setattr(cli_shim, "CANDIDATES", lambda: [d])
    monkeypatch.setattr(cli_shim, "_writable", lambda _d: True)
    monkeypatch.setattr(cli_shim, "binary_path", lambda: "/x/ghostbrain-api")
    assert cli_shim.main([]) == 0
    assert cli_shim.main([]) == 0
    assert "already" in capsys.readouterr().out


def test_go_live_replaces_only_the_mode_line_and_counts_inbox(tmp_path: Path, monkeypatch, capsys):
    vault = tmp_path / "vault"
    monkeypatch.setenv("VAULT_PATH", str(vault))
    (vault / "90-meta").mkdir(parents=True)
    (vault / "00-inbox" / "raw").mkdir(parents=True)
    (vault / "00-inbox" / "raw" / "a.md").write_text("x")
    cfg = vault / "90-meta" / "config.yaml"
    cfg.write_text("worker:\n  poll_interval_seconds: 5\n  # keep this comment\n  routing_mode: review_only\n\nprofile:\n  x: 1\n")
    assert go_live.main([]) == 0
    text = cfg.read_text()
    assert "  routing_mode: live\n" in text
    assert "# keep this comment" in text
    assert "poll_interval_seconds: 5" in text
    assert "1 item" in capsys.readouterr().out
    assert go_live.main([]) == 0  # idempotent


def test_go_live_adds_key_when_absent(tmp_path: Path, monkeypatch):
    vault = tmp_path / "vault"
    monkeypatch.setenv("VAULT_PATH", str(vault))
    (vault / "90-meta").mkdir(parents=True)
    cfg = vault / "90-meta" / "config.yaml"
    cfg.write_text("worker:\n  poll_interval_seconds: 5\n")
    assert go_live.main([]) == 0
    assert "  routing_mode: live\n" in cfg.read_text()


def test_bootstrap_alias(tmp_path: Path, monkeypatch, capsys):
    vault = tmp_path / "vault"
    monkeypatch.setenv("VAULT_PATH", str(vault))
    assert bs.main([]) == 0
    assert (vault / "90-meta" / "routing.yaml").exists()
    assert str(vault) in capsys.readouterr().out


def test_go_live_only_touches_the_worker_block(tmp_path: Path, monkeypatch):
    vault = tmp_path / "vault"
    monkeypatch.setenv("VAULT_PATH", str(vault))
    (vault / "90-meta").mkdir(parents=True)
    cfg = vault / "90-meta" / "config.yaml"
    cfg.write_text("other:\n  routing_mode: keep_me\n\nworker:\n  poll_interval_seconds: 5\n")
    assert go_live.main([]) == 0
    text = cfg.read_text()
    assert "  routing_mode: keep_me\n" in text
    assert "worker:\n  routing_mode: live\n" in text or "worker:\n  poll_interval_seconds: 5\n  routing_mode: live\n" in text


def test_cli_shim_refuses_when_target_is_a_directory(tmp_path: Path, monkeypatch, capsys):
    d = tmp_path / "bin"
    (d / "poltergeist").mkdir(parents=True)
    monkeypatch.setattr(cli_shim, "CANDIDATES", lambda: [d])
    monkeypatch.setattr(cli_shim, "_writable", lambda _d: True)
    monkeypatch.setattr(cli_shim, "binary_path", lambda: "/x/ghostbrain-api")
    assert cli_shim.main([]) == 1
    assert "is a directory" in capsys.readouterr().err


def test_go_live_fails_with_one_line_error(tmp_path: Path, monkeypatch, capsys):
    vault = tmp_path / "vault"
    monkeypatch.setenv("VAULT_PATH", str(vault))
    (vault / "90-meta").mkdir(parents=True)
    cfg = vault / "90-meta" / "config.yaml"
    cfg.mkdir()  # Create config as a directory to cause a read error
    assert go_live.main([]) == 1
    assert "go-live failed" in capsys.readouterr().err
