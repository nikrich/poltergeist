"""Phase 1 acceptance smoke test.

Drops a synthetic event in ``pending/``, runs the worker briefly in a thread,
and asserts the event lands in ``done/`` with an audit-log entry.
"""

from __future__ import annotations

import importlib
import json
import os
import threading
import time
from pathlib import Path

import pytest


@pytest.fixture()
def tmp_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    # Re-import worker.main so its module-level state picks up the env override
    # via ghostbrain.paths.queue_dir() at run-time (it does, but we reset for safety).
    import ghostbrain.paths as _paths  # noqa: F401
    import ghostbrain.worker.main as worker_main
    importlib.reload(worker_main)
    return tmp_path


def test_worker_processes_pending_event(tmp_vault: Path) -> None:
    from ghostbrain.bootstrap import bootstrap
    from ghostbrain.worker import main as worker_main

    bootstrap(tmp_vault)
    queue = tmp_vault / "90-meta" / "queue"
    pending = queue / "pending"

    event = {
        "id": "smoke-test-1",
        "source": "manual",
        "type": "session",
        "timestamp": "2026-05-07T10:00:00Z",
        "title": "Phase 1 smoke",
        "body": "hello",
        "rawData": {},
        "metadata": {},
    }
    (pending / "20260507T100000Z-manual-smoke-test-1.json").write_text(json.dumps(event))

    # Speed the loop up — default 5s would slow the test.
    worker_main.SLEEP_INTERVAL = 0.1

    t = threading.Thread(target=worker_main.run_loop, daemon=True)
    t.start()

    deadline = time.time() + 10  # acceptance criterion: <10s
    done_files: list[Path] = []
    while time.time() < deadline:
        done_files = list((queue / "done").glob("*.json"))
        if done_files:
            break
        time.sleep(0.1)

    # Stop the worker.
    worker_main._running = False
    t.join(timeout=5)

    assert done_files, "event never moved to done/"
    assert not list(pending.glob("*.json")), "event still in pending/"
    assert not list((queue / "failed").glob("*.json")), "event ended up in failed/"

    audit_files = list((tmp_vault / "90-meta" / "audit").glob("*.jsonl"))
    assert audit_files, "no audit log written"
    audit_lines = audit_files[0].read_text().splitlines()
    parsed = [json.loads(line) for line in audit_lines]
    success = [r for r in parsed if r.get("event_type") == "event_processed"]
    assert success, f"no event_processed audit line; got {parsed}"
    assert success[0]["event_id"] == "smoke-test-1"
    assert success[0]["status"] == "success"
