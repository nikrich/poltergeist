"""Read/write the user-facing slice of <vault>/90-meta/config.yaml.

Updates are merge-only: we load the full YAML, mutate the target subtree,
and write the whole document back. Comments are lost (PyYAML doesn't
round-trip them), but every other setting is preserved.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

import yaml

from ghostbrain.llm.client import LLMError
from ghostbrain.llm.providers import PROVIDER_IDS, get_provider
from ghostbrain.recorder import config as rcfg

# Defaults are owned by ghostbrain.recorder.config; this is a view for the
# handful of keys the UI edits.
_DEFAULTS = {
    "enabled": rcfg.RECORDER_DEFAULTS["enabled"],
    "excluded_titles": list(rcfg.RECORDER_DEFAULTS["excluded_titles"]),
    "manual_context": rcfg.RECORDER_DEFAULTS["manual_context"],
    "capture_backend": rcfg.RECORDER_DEFAULTS["capture_backend"],
    "capture_slides": rcfg.RECORDER_DEFAULTS["capture_slides"],
    "slide_fps": rcfg.RECORDER_DEFAULTS["slide_fps"],
    "slide_fallback": rcfg.RECORDER_DEFAULTS["slide_fallback"],
}


def _config_path() -> Path:
    return rcfg.config_path()


def _load_yaml() -> dict:
    return rcfg.load_config_yaml()


def _write_yaml_atomic(data: dict) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".config.", suffix=".yaml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
        os.replace(tmp, path)
    except Exception:
        try:
            Path(tmp).unlink(missing_ok=True)
        except OSError:
            pass
        raise


def effective_capture_backend(raw: dict | None = None, *, platform: str | None = None) -> str:
    plat = platform or sys.platform
    if plat == "darwin":
        from ghostbrain.recorder.audio import resolve_capture_backend
        return resolve_capture_backend(raw if raw is not None else rcfg.load_recorder_block())
    if plat == "win32":
        return "wasapi"
    return "unsupported"


def get_recorder_settings() -> dict:
    config = _load_yaml()
    raw = (config.get("recorder") or {}) if isinstance(config.get("recorder"), dict) else {}
    out: dict = {}
    out["enabled"] = bool(raw.get("enabled", _DEFAULTS["enabled"]))
    excluded = raw.get("excluded_titles") or _DEFAULTS["excluded_titles"]
    out["excluded_titles"] = [str(x) for x in excluded if isinstance(x, (str, int))]
    out["manual_context"] = str(raw.get("manual_context") or _DEFAULTS["manual_context"])
    out["capture_backend"] = rcfg.capture_backend_from(raw)
    out["capture_slides"] = rcfg.capture_slides_from(raw)
    out["slide_fps"] = rcfg.slide_fps_from(raw)
    out["slide_fallback"] = rcfg.slide_fallback_from(raw)
    out["capture_backend_effective"] = effective_capture_backend(raw)
    return out


def update_recorder_settings(**fields) -> dict:
    """Merge non-None fields into config.recorder. Returns the new settings."""
    config = _load_yaml()
    recorder = config.get("recorder") or {}
    if not isinstance(recorder, dict):
        recorder = {}

    if fields.get("enabled") is not None:
        recorder["enabled"] = bool(fields["enabled"])
    if fields.get("excluded_titles") is not None:
        recorder["excluded_titles"] = [str(x) for x in fields["excluded_titles"]]
    if fields.get("manual_context") is not None:
        recorder["manual_context"] = str(fields["manual_context"])
    if fields.get("capture_backend") is not None:
        value = str(fields["capture_backend"]).strip().lower()
        if value not in rcfg.CAPTURE_BACKENDS:
            raise ValueError(f"capture_backend must be one of {rcfg.CAPTURE_BACKENDS}")
        recorder["capture_backend"] = value
    if fields.get("capture_slides") is not None:
        recorder["capture_slides"] = bool(fields["capture_slides"])
    if fields.get("slide_fps") is not None:
        recorder["slide_fps"] = min(5, max(1, int(fields["slide_fps"])))
    if fields.get("slide_fallback") is not None:
        value = str(fields["slide_fallback"]).strip().lower()
        if value not in rcfg.SLIDE_FALLBACKS:
            raise ValueError(f"slide_fallback must be one of {rcfg.SLIDE_FALLBACKS}")
        recorder["slide_fallback"] = value

    config["recorder"] = recorder
    _write_yaml_atomic(config)
    return get_recorder_settings()


class ProviderUnavailable(RuntimeError):
    """Active LLM provider failed its probe; message is the user-facing reason."""


def get_llm_settings() -> dict:
    from ghostbrain.llm.providers.config import effective_models, load_llm_config

    cfg = load_llm_config(_load_yaml())
    return {
        "provider": cfg.provider,
        "models": cfg.models,
        "base_url": cfg.base_url,
        "api_key_env": cfg.api_key_env,
        "effective_models": effective_models(cfg.provider, cfg),
    }


def update_llm_settings(**fields) -> dict:
    config = _load_yaml()
    block = config.get("llm") if isinstance(config.get("llm"), dict) else {}
    if fields.get("provider") is not None:
        p = str(fields["provider"]).strip().lower()
        if p not in PROVIDER_IDS:
            raise ValueError(f"unknown provider {p!r}; expected one of {', '.join(PROVIDER_IDS)}")
        # llm.models is one global namespace, not per provider, and the
        # settings panel fills it from the local-only tier pickers. Carrying
        # `qwen3` across a switch back to claude would run `claude --model
        # qwen3`, so a provider change drops the overrides and each provider
        # falls back to its own tier defaults. Cleared BEFORE the `models`
        # field below is applied, so a PUT that sets both still wins.
        if p != str(block.get("provider") or "claude").strip().lower():
            block.pop("models", None)
        block["provider"] = p
    if fields.get("models") is not None:
        models = block.get("models") if isinstance(block.get("models"), dict) else {}
        for tier, model in fields["models"].items():
            if tier not in ("fast", "balanced", "quality"):
                raise ValueError(f"unknown tier {tier!r}; expected one of fast, balanced, quality")
            models[tier] = (str(model).strip() or None) if model is not None else None
        block["models"] = models
    http = block.get("openai_http") if isinstance(block.get("openai_http"), dict) else {}
    if fields.get("base_url") is not None:
        http["base_url"] = str(fields["base_url"]).strip().rstrip("/")
    if fields.get("api_key_env") is not None:
        http["api_key_env"] = str(fields["api_key_env"]).strip()
    if http:
        block["openai_http"] = http
    config["llm"] = block
    _write_yaml_atomic(config)
    _probe_cache.clear()
    return get_llm_settings()


# require_provider() caches the last probe result for _PROBE_TTL_S seconds,
# keyed by the config values that determine which provider/models/endpoint
# get probed — a chat/answer turn calls this at least once per request, and
# a subprocess probe on every request would add real latency. The cache is
# invalidated whenever update_llm_settings() writes a new config.
_PROBE_TTL_S = 60.0
_probe_cache: dict[tuple, tuple[float, object]] = {}


def require_provider() -> None:
    from ghostbrain.llm.providers.config import load_llm_config

    cfg = load_llm_config()
    key = (cfg.provider, cfg.base_url, cfg.api_key_env, tuple(sorted(cfg.models.items())))
    now = time.monotonic()
    cached = _probe_cache.get(key)
    if cached is not None and now - cached[0] < _PROBE_TTL_S:
        probe = cached[1]
    else:
        try:
            probe = get_provider().probe()
        except LLMError as e:
            raise ProviderUnavailable(str(e)) from e
        _probe_cache[key] = (now, probe)
    if not probe.ok:
        raise ProviderUnavailable(probe.reason)
