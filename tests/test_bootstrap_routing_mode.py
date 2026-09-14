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


def test_seeded_llm_block_keeps_the_per_role_models(tmp_path: Path):
    """The rewritten `llm:` template dropped router/extractor/digest/profile
    model, silently downgrading new vaults from opus to the sonnet code
    default for every judgement role."""
    root = bootstrap_mod.bootstrap(tmp_path / "vault")
    cfg = yaml.safe_load((root / "90-meta" / "config.yaml").read_text())
    llm = cfg["llm"]
    assert isinstance(llm, dict)
    assert llm["router_model"] == "haiku"
    assert llm["extractor_model"] == "opus"
    assert llm["digest_model"] == "opus"
    assert llm["profile_model"] == "opus"
    # No leftover `{}` placeholder from the empty-block template.
    assert set(llm) == {"router_model", "extractor_model", "digest_model", "profile_model"}
