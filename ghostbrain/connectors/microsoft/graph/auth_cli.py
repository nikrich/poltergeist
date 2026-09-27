"""Microsoft Graph device-code sign-in CLI.

Usage:
    ghostbrain-microsoft-auth [--tenant TENANT_ID]

Runs the device-code flow and ADDS the signed-in account to the shared token
cache in the OS keychain (accounts already signed in stay), then registers it
as a ``microsoft`` account. ``--tenant`` signs in against another tenant's
authority. Reads client_id/tenant_id from vault/90-meta/routing.yaml:microsoft.
"""

from __future__ import annotations

import argparse
import logging
import sys

from ghostbrain.connectors.microsoft.graph import auth as ms_auth
from ghostbrain.connectors.microsoft.graph.auth import (
    UNKNOWN_USERNAME,
    MicrosoftAuthError,
    run_device_flow,
)


def _load_microsoft_config() -> dict:
    import yaml

    from ghostbrain.paths import vault_path

    f = vault_path() / "90-meta" / "routing.yaml"
    if not f.exists():
        return {}
    routing = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    return routing.get("microsoft") or {}


def main() -> None:
    parser = argparse.ArgumentParser(prog="ghostbrain-microsoft-auth")
    parser.add_argument(
        "--tenant", default=None,
        help="Tenant ID to sign in against (defaults to microsoft.tenant_id).",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    config = _load_microsoft_config()
    try:
        username = run_device_flow(config, tenant_id=args.tenant)
    except MicrosoftAuthError as e:
        print(f"auth error: {e}", file=sys.stderr)
        raise SystemExit(1)
    except Exception as e:  # noqa: BLE001
        print(f"unexpected error: {e}", file=sys.stderr)
        raise SystemExit(2)
    print(f"OK — signed in as {username}; token cached.")
    if username == UNKNOWN_USERNAME:
        print("warning: could not tell which account signed in; not registering it.",
              file=sys.stderr)
        return
    from ghostbrain import accounts

    # First registered sign-in: also register the accounts already in the
    # cache, or the no-accounts fallback turns off and they stop syncing.
    first_registered = ms_auth.registry_is_empty()
    try:
        accounts.ensure_account(
            "microsoft", username,
            options={"tenant_id": args.tenant} if args.tenant else None,
        )
    except Exception as e:  # noqa: BLE001 — the sign-in itself succeeded
        print(f"warning: could not register {username} as a microsoft account: {e}",
              file=sys.stderr)
    if first_registered:
        ms_auth.adopt_cached_accounts(config)


if __name__ == "__main__":
    main()
