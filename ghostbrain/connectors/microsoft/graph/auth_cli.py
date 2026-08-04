"""Microsoft Graph device-code sign-in CLI.

Usage:
    ghostbrain-microsoft-auth

Runs the one-time device-code flow and caches the token in the OS keychain.
Reads optional client_id/tenant_id from vault/90-meta/routing.yaml:microsoft.
"""

from __future__ import annotations

import logging
import sys

from ghostbrain.connectors.microsoft.graph.auth import (
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
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        username = run_device_flow(_load_microsoft_config())
    except MicrosoftAuthError as e:
        print(f"auth error: {e}", file=sys.stderr)
        raise SystemExit(1)
    except Exception as e:  # noqa: BLE001
        print(f"unexpected error: {e}", file=sys.stderr)
        raise SystemExit(2)
    print(f"OK — signed in as {username}; token cached.")


if __name__ == "__main__":
    main()
