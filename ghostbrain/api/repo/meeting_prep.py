"""On-disk cache for meeting-prep payloads.

Cache files live under ``state_dir() / "meeting-prep" / <event_id>.json``.
``get_prep`` accepts the *expected* event-snapshot hash so callers can
invalidate stale entries when the underlying calendar event changes.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from ghostbrain.api.models.meeting import Prep
from ghostbrain.paths import state_dir

log = logging.getLogger("ghostbrain.api.repo.meeting_prep")

# How long to keep serving a failed prep before treating it as a cache miss
# and retrying. Successful preps (with a brief) are never expired by this —
# only the calendar event's hash invalidates those. The point of this TTL is
# to stop a transient LLM failure (e.g. claude binary missing during one
# build) from getting frozen in the cache and surviving the underlying fix.
ERROR_TTL_S = 300

_executor_lock = threading.Lock()
_inflight: set[str] = set()


def _cache_dir() -> Path:
    d = state_dir() / "meeting-prep"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_path(event_id: str) -> Path:
    safe = event_id.replace("/", "_").replace("\\", "_")
    return _cache_dir() / f"{safe}.json"


def get_prep(event_id: str, *, expected_hash: str) -> Prep | None:
    """Return the cached Prep iff present and its snapshot hash matches."""
    path = _cache_path(event_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text("utf-8"))
        prep = Prep.model_validate(payload)
    except Exception as e:  # noqa: BLE001
        log.warning("could not parse cached prep %s: %s", path, e)
        return None
    if prep.event_snapshot.hash != expected_hash:
        return None
    # If the cached entry is an error-only result, only serve it within the
    # retry window — past that, return None so prewarm can try again. This
    # prevents stale errors (e.g. from a previous broken build) from being
    # re-served forever after the underlying issue has been fixed.
    if prep.error and not prep.brief:
        try:
            generated = datetime.fromisoformat(prep.generated_at)
        except ValueError:
            return None
        age_s = (datetime.now(timezone.utc) - generated).total_seconds()
        if age_s > ERROR_TTL_S:
            return None
    return prep


def set_prep(prep: Prep) -> None:
    """Atomically write a Prep to disk."""
    path = _cache_path(prep.event_id)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(prep.model_dump(by_alias=True), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def prewarm(event_id: str, *, builder=None) -> bool:
    """Kick off ``build_prep`` in a background thread.

    Returns True if a new worker was launched, False if one is already
    running for this event id. Deliberately does not block the caller —
    the cache file lands asynchronously.
    """
    # Lazy import to break the circular dep (the builder imports models).
    if builder is None:
        from ghostbrain.worker.meeting_prep import build_prep
        builder = build_prep

    with _executor_lock:
        if event_id in _inflight:
            return False
        _inflight.add(event_id)

    def _run() -> None:
        try:
            prep = builder(event_id)
            set_prep(prep)
        except Exception:  # noqa: BLE001 — never crash the scheduler thread
            log.exception("prewarm failed for %s", event_id)
        finally:
            with _executor_lock:
                _inflight.discard(event_id)

    threading.Thread(target=_run, daemon=True, name=f"prewarm-{event_id}").start()
    return True
