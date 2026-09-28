"""Hourly Google Drive sync. Per account: list files modified since that
account's cursor, keep the ones the user owns or edited, defer anything
edited in the last 30 minutes, ingest the rest. Cursors are per account so
one failing account never makes another skip a window."""
from __future__ import annotations

import collections
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ghostbrain.accounts_health import for_each_account
from ghostbrain.connectors._base import Connector
from ghostbrain.connectors.gdrive import drive, ingest
from ghostbrain.connectors.gdrive.auth import GdriveAuthError, load_credentials
from ghostbrain.paths import state_dir

log = logging.getLogger("ghostbrain.connectors.gdrive")

DEBOUNCE = timedelta(minutes=30)
FIRST_RUN_LOOKBACK = timedelta(days=7)


def cursor_path() -> Path:
    return state_dir() / "gdrive_sync.json"


def _load_cursors() -> dict[str, str]:
    try:
        return json.loads(cursor_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_cursor(account: str, value: datetime) -> None:
    cursors = _load_cursors()
    cursors[account] = value.isoformat()
    cursor_path().parent.mkdir(parents=True, exist_ok=True)
    cursor_path().write_text(json.dumps(cursors, indent=2), encoding="utf-8")


class GdriveConnector(Connector):
    name = "gdrive"
    version = "1.0"

    def __init__(self, config: dict, queue_dir: Path, state_dir: Path, *,
                 services_for: Callable[[str], drive.Services] | None = None,
                 now: Callable[[], datetime] | None = None) -> None:
        super().__init__(config, queue_dir, state_dir)
        self.accounts: list[str] = list(config.get("accounts") or [])
        self._services_for = services_for or drive.build_services
        self._now = now or (lambda: datetime.now(UTC))
        self.stats: collections.Counter = collections.Counter()

    def health_check(self) -> bool:
        for email in self.accounts:
            try:
                load_credentials(email)
                return True
            except GdriveAuthError:
                continue
        return False

    # run() is overridden: Drive notes are upserted directly (new → pipeline,
    # changed → in-place rewrite) instead of going through the event queue.
    def fetch(self, since: datetime) -> list[dict]:
        raise NotImplementedError("GdriveConnector.run() upserts directly")

    def normalize(self, raw: dict) -> dict:
        raise NotImplementedError("GdriveConnector.run() upserts directly")

    def run(self) -> int:
        started = self._now()
        for_each_account(
            "gdrive", self.accounts, lambda email: self._sync_account(email, started),
            account_id=lambda email: email, auth_errors=(GdriveAuthError,),
        )
        self._save_last_run()
        log.info("gdrive sync: %s", dict(self.stats))
        try:
            from ghostbrain.worker.audit import audit_log
            audit_log("gdrive_sync", None, **{k: int(v) for k, v in self.stats.items()})
        except Exception:
            log.debug("audit_log failed", exc_info=True)
        return self.stats["imported"] + self.stats["updated"]

    def _sync_account(self, email: str, started: datetime) -> list[dict]:
        services = self._services_for(email)
        stored = _load_cursors().get(email)
        since = drive.parse_time(stored) if stored else started - FIRST_RUN_LOOKBACK
        cutoff = started - DEBOUNCE
        oldest_deferred: datetime | None = None
        folders: dict = {}
        token: str | None = None
        while True:
            files, token = drive.list_page(services.drive, after=since, page_token=token)
            for f in files:
                if not drive.is_mine(f):
                    continue
                modified = drive.parse_time(f["modifiedTime"])
                if modified > cutoff:
                    self.stats["deferred"] += 1
                    oldest_deferred = min(oldest_deferred or modified, modified)
                    continue
                outcome, _fallback = ingest.ingest_file(services, email, f, folders)
                self.stats[outcome] += 1
            if not token:
                break
        cursor = started if oldest_deferred is None else min(started, oldest_deferred - timedelta(seconds=1))
        _save_cursor(email, cursor)
        return []
