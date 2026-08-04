"""Calendar OAuth CLI.

Usage:
    ghostbrain-calendar-auth google <account_email>

Runs the one-time browser consent flow and saves a refresh token to
``~/.ghostbrain/state/google_calendar.<slug>.token``.
"""

from __future__ import annotations

import argparse
import logging
import sys

from ghostbrain.connectors.calendar.google.auth import (
    GoogleAuthError,
    run_oauth_flow,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run OAuth consent flow for a calendar provider.",
    )
    parser.add_argument(
        "provider", choices=("google",),
        help="Currently only 'google' is supported.",
    )
    parser.add_argument(
        "account",
        help="Account email (for google) or feed slug (other providers).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.provider == "google":
        try:
            path = run_oauth_flow(args.account)
        except GoogleAuthError as e:
            print(f"auth error: {e}", file=sys.stderr)
            raise SystemExit(1)
        except Exception as e:  # noqa: BLE001
            print(f"unexpected error: {e}", file=sys.stderr)
            raise SystemExit(2)
        print(f"OK — token saved to {path}")
        return

    raise SystemExit(f"unknown provider: {args.provider}")


if __name__ == "__main__":
    main()
