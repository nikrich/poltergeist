"""The `llm:` block of <vault>/90-meta/config.yaml and per-provider tier defaults."""
from __future__ import annotations

from dataclasses import dataclass, field

from ghostbrain.llm.client import LLMError
from ghostbrain.llm.providers import PROVIDER_IDS

TIER_DEFAULTS: dict[str, dict[str, str]] = {
    "claude": {"fast": "haiku", "balanced": "sonnet", "quality": "opus"},
    # Codex's model catalog differs per account and changes often ("gpt-5" is
    # rejected on ChatGPT accounts). No default: the CLI's own current model is
    # used and the tiers map to reasoning effort; `llm.models` pins a model.
    "codex": {},
    "gemini": {"fast": "gemini-2.5-flash", "balanced": "gemini-2.5-pro", "quality": "gemini-2.5-pro"},
    "openai_http": {},
}
DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"
DEFAULT_API_KEY_ENV = "OPENAI_API_KEY"


@dataclass
class LlmConfig:
    provider: str = "claude"
    models: dict[str, str | None] = field(default_factory=lambda: {"fast": None, "balanced": None, "quality": None})
    base_url: str = DEFAULT_BASE_URL
    api_key_env: str = DEFAULT_API_KEY_ENV


def load_llm_config(cfg: dict | None = None) -> LlmConfig:
    if cfg is None:
        from ghostbrain.recorder.config import load_config_yaml

        cfg = load_config_yaml()
    block = cfg.get("llm") if isinstance(cfg.get("llm"), dict) else {}
    provider = str(block.get("provider") or "claude").strip().lower()
    if provider not in PROVIDER_IDS:
        raise LLMError(f"llm.provider {provider!r} is not one of {', '.join(PROVIDER_IDS)}")
    raw_models = block.get("models") if isinstance(block.get("models"), dict) else {}
    models = {t: (str(raw_models[t]).strip() if raw_models.get(t) else None) for t in ("fast", "balanced", "quality")}
    http = block.get("openai_http") if isinstance(block.get("openai_http"), dict) else {}
    return LlmConfig(
        provider=provider,
        models=models,
        base_url=str(http.get("base_url") or DEFAULT_BASE_URL).rstrip("/"),
        api_key_env=str(http.get("api_key_env") or DEFAULT_API_KEY_ENV),
    )


def effective_models(provider_id: str, cfg: LlmConfig) -> dict[str, str]:
    out = dict(TIER_DEFAULTS.get(provider_id, {}))
    out.update({t: m for t, m in cfg.models.items() if m})
    return out
