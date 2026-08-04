"""Slack token import CLI.

Usage:
    ghostbrain-slack-token-add <workspace_slug> <xoxp-token>

Saves the token to ``~/.ghostbrain/state/slack.<slug>.token`` with 0600
permissions. Verifies it works by calling ``auth.test`` once.
"""

from __future__ import annotations

import argparse
import logging
import sys

from ghostbrain.connectors.slack.auth import SlackAuthError, save_token


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Save a Slack User OAuth Token (xoxp-...) for a workspace.",
    )
    parser.add_argument(
        "workspace",
        help="Workspace slug — must match a key in routing.yaml:slack.workspaces.",
    )
    parser.add_argument(
        "token",
        help="User OAuth Token from your Slack app's OAuth & Permissions page.",
    )
    parser.add_argument(
        "--no-verify", action="store_true",
        help="Skip the auth.test call (offline-only).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        path = save_token(args.workspace, args.token)
    except SlackAuthError as e:
        print(f"auth error: {e}", file=sys.stderr)
        raise SystemExit(1)

    if not args.no_verify:
        try:
            from slack_sdk import WebClient
            ident = WebClient(token=args.token).auth_test().data
            print(
                f"OK — connected as @{ident.get('user')} on team "
                f"{ident.get('team')!r}; token saved to {path}"
            )
        except Exception as e:  # noqa: BLE001
            print(f"warning: token saved but auth.test failed: {e}",
                  file=sys.stderr)
            print(f"path: {path}")
            return
    else:
        print(f"OK — token saved to {path}")


if __name__ == "__main__":
    main()
