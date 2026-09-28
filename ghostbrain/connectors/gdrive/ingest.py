"""One Drive file → vault: convert, build the event, upsert. Shared by the
hourly sync and the backfill. Account-level failures (auth, rate limit, API
disabled) propagate; anything else about one file is counted as 'failed'."""
from __future__ import annotations

import logging

from ghostbrain.connectors.gdrive import convert, drive, store
from ghostbrain.connectors.gdrive.auth import GdriveAuthError
from ghostbrain.connectors.gdrive.event import build_event

log = logging.getLogger("ghostbrain.connectors.gdrive.ingest")

OUTCOMES = ("imported", "updated", "skipped", "failed", "tooLarge")
_ACCOUNT_LEVEL = (GdriveAuthError, drive.DriveRateLimited, drive.DriveApiDisabled)


def is_routing_fallback(result) -> bool:
    """True when the pipeline parked the note in needs_review because the LLM
    router failed (router ``method == "fallback"``) — same test as Gmail's
    backfill uses to pause on an unavailable AI router."""
    return (isinstance(result, dict)
            and result.get("method") == "fallback"
            and result.get("context") == "needs_review")


def ingest_file(services: drive.Services, account: str, file: dict, folders: dict) -> tuple[str, bool]:
    """(outcome, routing_fallback) for one file."""
    try:
        converted = convert.convert(services, file)
        folder = drive.folder_path(services.drive, file, folders)
        outcome, result = store.upsert(build_event(file, account=account, result=converted, folder=folder))
        return outcome, outcome == "imported" and is_routing_fallback(result)
    except convert.TooLarge:
        log.info("gdrive: skipping %s (%s) — over the download cap", file.get("name"), file.get("id"))
        return "tooLarge", False
    except _ACCOUNT_LEVEL:
        raise
    except Exception:  # one bad file never stops the run
        log.exception("gdrive: failed to ingest %s (%s)", file.get("name"), file.get("id"))
        return "failed", False
