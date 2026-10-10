"""Daily maintenance shared by page history (A3) and the change log (B2).

Change rows older than a year go first. Then A3's retention + blob GC runs,
which keeps every blob a remaining row names (the "changes" ref source) and
skips GC entirely when the change log can't be read."""
from __future__ import annotations

import logging
from datetime import datetime

from ghostbrain.changes import log as changes_log

log = logging.getLogger("ghostbrain.changes")


def run_prune(now: datetime | None = None) -> dict:
    from ghostbrain.history import store

    try:
        pruned: int | None = changes_log.prune(now)
    except changes_log.ChangeLogError:
        log.exception("change-log retention failed; history prune continues")
        pruned = None
    changes_log.register_with_history()
    details = store.prune(now).to_details()
    return {**details, "changesPruned": pruned}
