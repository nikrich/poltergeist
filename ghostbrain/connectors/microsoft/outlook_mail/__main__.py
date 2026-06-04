"""CLI: python -m ghostbrain.connectors.microsoft.outlook_mail
or ghostbrain-outlook-mail-fetch."""
from __future__ import annotations

import logging

from ghostbrain.connectors.microsoft.outlook_mail.runner import run


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = run()
    if result.skipped_reason:
        print(f"outlook_mail: skipped ({result.skipped_reason})")
    elif result.ok:
        print(f"outlook_mail: queued {result.queued} event(s)")
    else:
        print(f"outlook_mail: FAILED — {result.error}")


if __name__ == "__main__":
    main()
