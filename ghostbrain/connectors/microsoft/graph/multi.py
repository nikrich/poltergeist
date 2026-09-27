"""Per-account Graph fetch shared by the Outlook / Teams connectors.

``config["accounts"]`` is a list of ``{"username", "tenant_id"}`` built by the
runners from the ``microsoft`` account registry. An entry whose username is
None means "the first cached MSAL sign-in" (the single-account behaviour the
runners fall back to when the registry has no microsoft accounts): its
events are not tagged with an accountId and its health is recorded under
``default``.
"""
from __future__ import annotations

from collections.abc import Callable

from ghostbrain.accounts_health import for_each_account
from ghostbrain.connectors.microsoft.graph.auth import MicrosoftAuthError, get_token, have_token
from ghostbrain.connectors.microsoft.graph.client import GraphClient

DEFAULT_ACCOUNT_ID = "default"
_FALLBACK = {"username": None, "tenant_id": None}


def ms_accounts(config: dict) -> list[dict]:
    """The configured account entries (non-dict junk dropped). A config with
    no ``accounts`` key at all means the first cached sign-in."""
    raw = config.get("accounts")
    if raw is None:
        return [dict(_FALLBACK)]
    return [a for a in raw if isinstance(a, dict)]


def _account_id(acc: dict) -> str:
    return acc.get("username") or DEFAULT_ACCOUNT_ID


def any_token(config: dict) -> bool:
    return any(
        have_token(config, a.get("username"), a.get("tenant_id")) for a in ms_accounts(config)
    )


def fetch_per_account(
    connector: str,
    config: dict,
    fetch_with: Callable[[GraphClient], list[dict]],
) -> list[dict]:
    """Run ``fetch_with(client)`` once per configured account with that
    account's token, tag events with ``metadata.accountId`` (named accounts
    only), and isolate failures per account."""

    def one(acc: dict) -> list[dict]:
        username = acc.get("username") or None
        client = GraphClient(get_token(config, username, acc.get("tenant_id")))
        events = fetch_with(client)
        if username:
            for ev in events:
                ev.setdefault("metadata", {})["accountId"] = username
        return events

    return for_each_account(
        connector, ms_accounts(config), one,
        account_id=_account_id, auth_errors=(MicrosoftAuthError,),
    )
