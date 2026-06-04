"""CLI: python -m ghostbrain.connectors.microsoft.teams_chat
or ghostbrain-teams-chat-fetch."""
from __future__ import annotations

import logging

from ghostbrain.connectors.microsoft.teams_chat.runner import run


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = run()
    if result.skipped_reason:
        print(f"teams_chat: skipped ({result.skipped_reason})")
    elif result.ok:
        print(f"teams_chat: queued {result.queued} event(s)")
    else:
        print(f"teams_chat: FAILED — {result.error}")


if __name__ == "__main__":
    main()
