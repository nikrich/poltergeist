"""Microsoft Graph delegated (device-code) auth.

Device-code sign-ins cache tokens in the OS keychain
(``msal-extensions`` encrypted persistence) at
``~/.ghostbrain/state/microsoft/token_cache.bin``. The cache can hold
several accounts (one per sign-in, possibly in different tenants); all
three microsoft connectors share it via the union of scopes below.
Scheduled fetches only ever call ``get_token`` (silent), selecting one
cached account by username (or the first cached account when none is
given); the interactive device-code flow lives in ``auth_cli.py``.
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

# Placeholder username_from_result returns when the sign-in's username is
# unknown; never registered as an account.
UNKNOWN_USERNAME = "your account"


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


def resolve_scopes(config: dict) -> list[str]:
    """Delegated Graph scopes to request. Defaults to the full union, but can
    be narrowed via ``microsoft.scopes`` — useful when only some scopes have
    tenant consent (e.g. transcripts-only until mail/chat are approved).
    Token cache lookups must use the same scope set that was consented, so
    both sign-in and silent refresh read this."""
    scopes = (config or {}).get("scopes")
    if scopes:
        return [str(s) for s in scopes]
    return list(SCOPES)


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


def _build_app(config: dict, tenant_id: str | None = None):
    import msal

    client_id, default_tenant = resolve_app_config(config)
    authority = f"https://login.microsoftonline.com/{tenant_id or default_tenant}"
    return msal.PublicClientApplication(
        client_id, authority=authority, token_cache=_build_token_cache()
    )


def get_token(config: dict, username: str | None = None, tenant_id: str | None = None) -> str:
    """Access token for ``username`` (or the first cached account when None)
    from the shared cache. Raises MicrosoftAuthError when that account has no
    usable cached sign-in."""
    app = _build_app(config, tenant_id)
    accounts = app.get_accounts(username=username) if username else app.get_accounts()
    if not accounts:
        who = username or "any account"
        raise MicrosoftAuthError(
            f"No cached Microsoft sign-in for {who}. Reconnect it in the app "
            "or run: ghostbrain-microsoft-auth"
        )
    result = app.acquire_token_silent(resolve_scopes(config), account=accounts[0])
    if not result or "access_token" not in result:
        raise MicrosoftAuthError(
            f"Cached Microsoft sign-in for {accounts[0].get('username')} could not be "
            "refreshed. Reconnect it in the app or re-run: ghostbrain-microsoft-auth"
        )
    return result["access_token"]


def have_token(config: dict, username: str | None = None, tenant_id: str | None = None) -> bool:
    """Cheap health-check predicate: True if get_token would succeed."""
    try:
        get_token(config, username, tenant_id)
        return True
    except MicrosoftAuthError:
        return False


def cached_usernames(config: dict) -> list[str]:
    """Usernames of every account in the shared MSAL cache."""
    app = _build_app(config)
    return [a["username"] for a in app.get_accounts() if a.get("username")]


def remove_cached_account(config: dict, username: str) -> bool:
    """Drop ``username`` from the shared cache. True if it was present."""
    app = _build_app(config)
    found = app.get_accounts(username=username)
    for acc in found:
        app.remove_account(acc)
    return bool(found)


def username_from_result(result: dict, app) -> str:
    """Username of the account a device-code ``result`` signed in: the id
    token's preferred_username, else the newest cached account, else a
    placeholder."""
    claims = result.get("id_token_claims") or {}
    if claims.get("preferred_username"):
        return str(claims["preferred_username"])
    accounts = app.get_accounts()
    if accounts and accounts[-1].get("username"):
        return str(accounts[-1]["username"])
    return UNKNOWN_USERNAME


def run_device_flow(config: dict, tenant_id: str | None = None) -> str:
    """Interactive device-code sign-in that ADDS an account to the shared
    cache (existing accounts stay). Returns the new account's username.
    Called only from auth_cli.py."""
    app = _build_app(config, tenant_id)
    flow = app.initiate_device_flow(scopes=resolve_scopes(config))
    if "user_code" not in flow:
        raise MicrosoftAuthError(f"Could not start device flow: {flow}")
    print(flow["message"])
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise MicrosoftAuthError(
            f"Auth failed: {result.get('error_description', result)}"
        )
    return username_from_result(result, app)
