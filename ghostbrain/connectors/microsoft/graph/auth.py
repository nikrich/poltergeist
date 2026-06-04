"""Microsoft Graph delegated (device-code) auth.

One device-code sign-in caches a token in the OS keychain
(``msal-extensions`` encrypted persistence) at
``~/.ghostbrain/state/microsoft/token_cache.bin``. All three microsoft
connectors share that cache via the union of scopes below. Scheduled
fetches only ever call ``get_token`` (silent); the interactive device-code
flow lives in ``auth_cli.py``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger("ghostbrain.connectors.microsoft.auth")

# The Graph app identity is NOT baked into the repo. These are not secrets
# (public-client / device-code app, no client secret), but the tenant/app
# identifiers are kept out of source: set microsoft.client_id and
# microsoft.tenant_id in vault/90-meta/routing.yaml, or env MS_GRAPH_CLIENT_ID
# / MS_GRAPH_TENANT_ID.
DEFAULT_CLIENT_ID = ""
DEFAULT_TENANT_ID = ""

# Union of every scope the three connectors need; one consent covers all.
SCOPES = [
    "Mail.Read",
    "Chat.Read",
    "Calendars.Read",
    "OnlineMeetings.Read",
    "OnlineMeetingTranscript.Read.All",
]

GRAPH = "https://graph.microsoft.com/v1.0"


class MicrosoftAuthError(RuntimeError):
    """Raised when Graph credentials are missing, expired beyond refresh,
    or otherwise unusable. Mirrors GmailAuthError."""


def state_dir() -> Path:
    raw = os.environ.get("GHOSTBRAIN_STATE_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".ghostbrain" / "state").resolve()


def cache_location() -> Path:
    return state_dir() / "microsoft" / "token_cache.bin"


def resolve_app_config(config: dict) -> tuple[str, str]:
    """Return (client_id, tenant_id) from routing config or environment.

    Raises MicrosoftAuthError when neither is configured — the app identity is
    not baked into the repo.
    """
    cfg = config or {}
    client_id = str(
        cfg.get("client_id") or DEFAULT_CLIENT_ID
        or os.environ.get("MS_GRAPH_CLIENT_ID", "")
    )
    tenant_id = str(
        cfg.get("tenant_id") or DEFAULT_TENANT_ID
        or os.environ.get("MS_GRAPH_TENANT_ID", "")
    )
    if not client_id or not tenant_id:
        raise MicrosoftAuthError(
            "Microsoft client_id/tenant_id not configured. Set microsoft.client_id "
            "and microsoft.tenant_id in vault/90-meta/routing.yaml (or env "
            "MS_GRAPH_CLIENT_ID / MS_GRAPH_TENANT_ID)."
        )
    return client_id, tenant_id


def _build_token_cache():
    """OS-secure persistent token cache, with a chmod-600 plaintext
    fallback that warns (never a silent downgrade)."""
    from msal_extensions import (
        FilePersistence,
        PersistedTokenCache,
        build_encrypted_persistence,
    )

    loc = cache_location()
    loc.parent.mkdir(parents=True, exist_ok=True)
    try:
        persistence = build_encrypted_persistence(str(loc))
    except Exception as e:  # noqa: BLE001
        log.warning("OS keychain unavailable (%s); using chmod-600 file cache.", e)
        persistence = FilePersistence(str(loc))
        loc.touch(exist_ok=True)
        loc.chmod(0o600)
    return PersistedTokenCache(persistence)


def _build_app(config: dict):
    import msal

    client_id, tenant_id = resolve_app_config(config)
    authority = f"https://login.microsoftonline.com/{tenant_id}"
    return msal.PublicClientApplication(
        client_id, authority=authority, token_cache=_build_token_cache()
    )


def get_token(config: dict) -> str:
    """Return an access token from the cached sign-in. Raises
    MicrosoftAuthError if no usable cached account exists — the interactive
    flow must be run via `ghostbrain-microsoft-auth` first."""
    app = _build_app(config)
    accounts = app.get_accounts()
    if not accounts:
        raise MicrosoftAuthError(
            "No cached Microsoft sign-in. Run: ghostbrain-microsoft-auth"
        )
    result = app.acquire_token_silent(SCOPES, account=accounts[0])
    if not result or "access_token" not in result:
        raise MicrosoftAuthError(
            "Cached Microsoft sign-in could not be refreshed. "
            "Re-run: ghostbrain-microsoft-auth"
        )
    return result["access_token"]


def have_token(config: dict) -> bool:
    """Cheap health-check predicate: True if get_token would succeed."""
    try:
        get_token(config)
        return True
    except MicrosoftAuthError:
        return False


def run_device_flow(config: dict) -> str:
    """Interactive one-time device-code sign-in. Returns the signed-in
    username. Called only from auth_cli.py."""
    app = _build_app(config)
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise MicrosoftAuthError(f"Could not start device flow: {flow}")
    print(flow["message"])
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise MicrosoftAuthError(
            f"Auth failed: {result.get('error_description', result)}"
        )
    accounts = app.get_accounts()
    return accounts[0].get("username", "your account") if accounts else "your account"
