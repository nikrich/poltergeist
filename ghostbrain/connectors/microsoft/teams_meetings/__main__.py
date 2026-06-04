"""CLI: python -m ghostbrain.connectors.microsoft.teams_meetings
or ghostbrain-teams-meetings-fetch."""
from __future__ import annotations

import logging

from ghostbrain.connectors.microsoft.teams_meetings.runner import run


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = run()
    if result.skipped_reason:
        print(f"teams_meetings: skipped ({result.skipped_reason})")
    elif result.ok:
        print(f"teams_meetings: queued {result.queued} event(s)")
    else:
        print(f"teams_meetings: FAILED — {result.error}")


if __name__ == "__main__":
    main()
