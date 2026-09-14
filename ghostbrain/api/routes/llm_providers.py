"""GET /v1/llm/providers — probe every provider adapter for the settings UI.

Separate from routes/llm.py (POST /v1/llm/run): both mount at the same
`/v1/llm` prefix, contributing different sub-paths.
"""
from __future__ import annotations

import dataclasses

from fastapi import APIRouter

from ghostbrain.llm.providers import PROVIDER_IDS, get_provider
from ghostbrain.llm.providers.base import ProviderProbe
from ghostbrain.llm.providers.config import LlmConfig, load_llm_config

router = APIRouter(prefix="/v1/llm", tags=["llm"])


def _probe_all() -> dict[str, ProviderProbe]:
    cfg = load_llm_config()
    out: dict[str, ProviderProbe] = {}
    for pid in PROVIDER_IDS:
        try:
            out[pid] = get_provider(
                LlmConfig(provider=pid, models=cfg.models, base_url=cfg.base_url, api_key_env=cfg.api_key_env)
            ).probe()
        except Exception as e:  # noqa: BLE001 — one misbehaving provider must not break the rest
            out[pid] = ProviderProbe(False, str(e))
    return out


def _active() -> str:
    return load_llm_config().provider


@router.get("/providers")
def list_providers() -> dict:
    return {"active": _active(), "providers": {k: dataclasses.asdict(v) for k, v in _probe_all().items()}}
