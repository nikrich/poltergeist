"""GET /v1/llm/providers — probe every provider adapter for the settings UI.

Separate from routes/llm.py (POST /v1/llm/run): both mount at the same
`/v1/llm` prefix, contributing different sub-paths.
"""
from __future__ import annotations

import dataclasses

from fastapi import APIRouter

from ghostbrain.api.repo.settings import cached_probe, probe_cache_key
from ghostbrain.llm.providers import PROVIDER_IDS, get_provider
from ghostbrain.llm.providers.base import ProviderProbe
from ghostbrain.llm.providers.config import LlmConfig, load_llm_config

router = APIRouter(prefix="/v1/llm", tags=["llm"])


def _probe_all(refresh: bool = False) -> dict[str, ProviderProbe]:
    cfg = load_llm_config()
    out: dict[str, ProviderProbe] = {}
    for pid in PROVIDER_IDS:
        one = LlmConfig(provider=pid, models=cfg.models, base_url=cfg.base_url, api_key_env=cfg.api_key_env)
        try:
            # Shares require_provider()'s 60s cache: four CLI spawns / HTTP
            # round trips on every settings render is real latency, and the
            # active provider's probe is usually already warm.
            out[pid] = cached_probe(
                probe_cache_key(pid, one), lambda one=one: get_provider(one).probe(), refresh=refresh
            )
        except Exception as e:  # noqa: BLE001 — one misbehaving provider must not break the rest
            out[pid] = ProviderProbe(False, str(e))
    return out


def _active() -> str:
    return load_llm_config().provider


@router.get("/providers")
def list_providers(refresh: bool = False) -> dict:
    """``refresh=1`` bypasses the probe cache — the settings panel's explicit
    "re-check" button, after the user has just installed or signed into a CLI."""
    return {"active": _active(), "providers": {k: dataclasses.asdict(v) for k, v in _probe_all(refresh).items()}}
