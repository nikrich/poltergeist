"""Queue worker daemon. See SPEC §5.2.

Phase 1: ``process_event`` is a stub that just logs the event id.
Routing, note generation, and downstream pipeline steps land in Phase 3.
"""

from __future__ import annotations

import json
import logging
import signal
import time
from pathlib import Path

from ghostbrain.paths import queue_dir
from ghostbrain.worker.audit import audit_log
from ghostbrain.worker.pipeline import process_event as _pipeline_process_event

SLEEP_INTERVAL = 5  # seconds between polls when the queue is empty

log = logging.getLogger("ghostbrain.worker")

_running = True


def _handle_signal(signum, _frame) -> None:
    global _running
    log.info("Received signal %s, shutting down", signum)
    _running = False


def _ensure_queue_dirs(root: Path) -> None:
    for sub in ("pending", "processing", "failed", "done"):
        (root / sub).mkdir(parents=True, exist_ok=True)


def _claim_next(root: Path) -> Path | None:
    """Atomically claim the oldest pending event by renaming it into ``processing/``."""
    pending = sorted((root / "pending").glob("*.json"))
    if not pending:
        return None
    src = pending[0]
    dst = root / "processing" / src.name
    try:
        src.rename(dst)
    except FileNotFoundError:
        # Another worker grabbed it (or it vanished); skip.
        return None
    return dst


def _move(src: Path, dst_dir: Path) -> Path:
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    src.rename(dst)
    return dst


def process_event(event: dict) -> dict:
    """Run an event through the full pipeline (Phase 3+)."""
    return _pipeline_process_event(event)


def run_loop() -> None:
    root = queue_dir()
    _ensure_queue_dirs(root)
    log.info("Worker started. queue=%s", root)
    audit_log("worker_started", queue_dir=str(root))

    while _running:
        event_path = _claim_next(root)
        if event_path is None:
            time.sleep(SLEEP_INTERVAL)
            continue

        event_id = event_path.stem
        # Phase A — process. A failure here leaves the file in processing/ so
        # the except branch can move it to failed/.
        processed_ok = False
        summary: dict = {}
        try:
            event = json.loads(event_path.read_text(encoding="utf-8"))
            event_id = event.get("id", event_id)
            summary = process_event(event) or {}
            processed_ok = True
        except Exception as e:  # noqa: BLE001
            log.exception("Processing failed for %s", event_id)
            if event_path.exists():
                failed_path = _move(event_path, root / "failed")
                (failed_path.with_suffix(failed_path.suffix + ".error")).write_text(
                    f"{type(e).__name__}: {e}\n", encoding="utf-8"
                )
            audit_log("event_failed", event_id, error=f"{type(e).__name__}: {e}")

        if not processed_ok:
            continue

        # Phase B — move to done/ + audit. A failure here MUST NOT push the file
        # into failed/ (it was processed successfully) and MUST NOT crash the
        # worker. The pipeline now puts a `status` key in the summary on the
        # skip path, which used to collide with the explicit `status=` kwarg
        # below and TypeError out — we strip reserved keys from the spread to
        # prevent that.
        try:
            _move(event_path, root / "done")
        except Exception:  # noqa: BLE001
            log.exception("Failed to move %s to done/ (already moved?)", event_id)

        # Exclude every key the audit_log call already binds — event_id is
        # positional, status/source are keyword. Without this, a summary dict
        # carrying any of them produces "multiple values for keyword argument".
        reserved = {"event_id", "status", "source"}
        extras = {k: v for k, v in summary.items() if v is not None and k not in reserved}
        try:
            audit_log(
                "event_processed",
                event_id,
                status="success",
                source=event.get("source"),
                **extras,
            )
        except Exception:  # noqa: BLE001
            log.exception("audit_log failed for %s (event still counted as processed)", event_id)

    audit_log("worker_stopped")
    log.info("Worker stopped")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    run_loop()


if __name__ == "__main__":
    main()
