"""LLM provider adapters. `get_provider()` is filled in by config (Task 3)."""
from __future__ import annotations

PROVIDER_IDS: tuple[str, ...] = ("claude", "codex", "gemini", "openai_http")


def get_provider(cfg=None):
    from ghostbrain.llm.client import LLMError
    from ghostbrain.llm.providers.config import effective_models, load_llm_config

    cfg = cfg or load_llm_config()
    models = effective_models(cfg.provider, cfg)
    if cfg.provider == "claude":
        from ghostbrain.llm.providers.claude_cli import ClaudeCli

        return ClaudeCli(models=models)
    raise LLMError(f"llm.provider {cfg.provider!r} is not implemented yet")
