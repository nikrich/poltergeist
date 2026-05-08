"""Gmail OAuth CLI.

Usage:
    ghostbrain-gmail-auth <account_email>

Runs the one-time browser consent flow and saves a refresh token to
``~/.ghostbrain/state/gmail.<slug>.token``.
"""

from __future__ import annotations

import argparse
import logging
import sys

from ghostbrain.connectors.gmail.auth import GmailAuthError, run_oauth_flow


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run OAuth consent flow for a Gmail account.",
    )
    parser.add_argument("account", help="Gmail account email address.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        path = run_oauth_flow(args.account)
    except GmailAuthError as e:
        print(f"auth error: {e}", file=sys.stderr)
        raise SystemExit(1)
    except Exception as e:  # noqa: BLE001
        print(f"unexpected error: {e}", file=sys.stderr)
        raise SystemExit(2)
    print(f"OK — token saved to {path}")


if __name__ == "__main__":
    main()
