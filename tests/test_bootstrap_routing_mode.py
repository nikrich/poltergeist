from __future__ import annotations

from pathlib import Path

import yaml

import ghostbrain.bootstrap as bootstrap_mod


def test_fresh_vault_files_notes_live(tmp_path: Path):
    root = bootstrap_mod.bootstrap(tmp_path / "vault")
    cfg = yaml.safe_load((root / "90-meta" / "config.yaml").read_text())
    assert cfg["worker"]["routing_mode"] == "live"


def test_existing_config_is_not_rewritten(tmp_path: Path):
    root = bootstrap_mod.bootstrap(tmp_path / "vault")
    cfg_file = root / "90-meta" / "config.yaml"
    cfg_file.write_text(cfg_file.read_text().replace("routing_mode: live", "routing_mode: review_only"))
    bootstrap_mod.bootstrap(tmp_path / "vault")
    assert "routing_mode: review_only" in cfg_file.read_text()
