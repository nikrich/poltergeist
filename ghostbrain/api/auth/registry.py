"""Maps connector id -> AuthProvider instance. Providers registered in
Milestone D. Raising KeyError for unknown ids yields a 404 in the router."""
from __future__ import annotations

from ghostbrain.api.auth.providers.base import AuthProvider

_PROVIDERS: dict[str, AuthProvider] = {}


def register(connector_id: str, provider: AuthProvider) -> None:
    _PROVIDERS[connector_id] = provider


def provider_for(connector_id: str) -> AuthProvider:
    return _PROVIDERS[connector_id]  # KeyError -> 404
