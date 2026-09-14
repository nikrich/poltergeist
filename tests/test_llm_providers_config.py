from __future__ import annotations

from pathlib import Path

import pytest

from ghostbrain.llm.client import LLMError
from ghostbrain.llm.providers import config as pcfg, get_provider


def _write(vault: Path, text: str) -> None:
    (vault / "90-meta").mkdir(parents=True, exist_ok=True)
    (vault / "90-meta" / "config.yaml").write_text(text)


def test_defaults_to_claude_when_block_absent(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    _write(tmp_path, "worker:\n  routing_mode: live\n")
    cfg = pcfg.load_llm_config()
    assert cfg.provider == "claude"
    assert pcfg.effective_models("claude", cfg) == {"fast": "haiku", "balanced": "sonnet", "quality": "opus"}


def test_overrides_and_openai_http_fields(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    _write(tmp_path, "llm:\n  provider: codex\n  models:\n    quality: gpt-5-pro\n  openai_http:\n    base_url: http://127.0.0.1:1234/v1\n    api_key_env: LMSTUDIO_KEY\n")
    cfg = pcfg.load_llm_config()
    assert cfg.provider == "codex"
    # codex has no default model names (the CLI's own default runs); only the override shows.
    assert pcfg.effective_models("codex", cfg) == {"quality": "gpt-5-pro"}
    assert cfg.base_url == "http://127.0.0.1:1234/v1" and cfg.api_key_env == "LMSTUDIO_KEY"


def test_unknown_provider_is_rejected(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    _write(tmp_path, "llm:\n  provider: bard\n")
    with pytest.raises(LLMError, match="bard"):
        pcfg.load_llm_config()


def test_get_provider_returns_claude_adapter_with_overrides(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    _write(tmp_path, "llm:\n  provider: claude\n  models:\n    fast: sonnet\n")
    p = get_provider()
    assert p.id == "claude" and p.models()["fast"] == "sonnet"


def test_bootstrap_seeds_commented_llm_block(tmp_path: Path):
    import ghostbrain.bootstrap as bootstrap_mod

    root = bootstrap_mod.bootstrap(tmp_path / "vault")
    text = (root / "90-meta" / "config.yaml").read_text()
    assert "llm:" in text and "# provider: claude" in text and "openai_http" in text


def test_agent_provider_delegates_to_get_provider_for_non_claude(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    _write(tmp_path, "llm:\n  provider: openai_http\n")
    from ghostbrain.llm import agent

    p = agent._provider()
    assert p.id == "openai_http"


def test_agent_provider_keeps_claude_tier_overrides(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    _write(tmp_path, "llm:\n  provider: claude\n  models:\n    fast: sonnet\n")
    from ghostbrain.llm import agent

    p = agent._provider()
    assert p.models()["fast"] == "sonnet"
