"""Phase 1 + Phase 3 worker smoke test.

Drops a synthetic non-Claude event in ``pending/``, runs the worker briefly,
and asserts the event lands in ``done/`` with an audit-log entry.

Phase 3 wired the real pipeline into ``process_event``. To keep this test
LLM-free, we use a ``manual`` source with a ``metadata.projectPath`` that
matches a known routing rule — the path-first router resolves it without an
LLM call.
"""

from __future__ import annotations

import importlib
import json
import threading
import time
from pathlib import Path

import pytest


def test_worker_processes_pending_event(vault: Path) -> None:
    from ghostbrain.worker import main as worker_main

    queue = vault / "90-meta" / "queue"
    pending = queue / "pending"

    # Add a routing rule the smoke event will match.
    routing = vault / "90-meta" / "routing.yaml"
    routing.write_text(
        "version: 1\n"
        "claude_code:\n"
        "  project_paths:\n"
        f"    \"{vault}/fake-project\": consulting\n"
    )

    event = {
        "id": "smoke-test-1",
        "source": "manual",
        "type": "note",
        "timestamp": "2026-05-07T10:00:00Z",
        "title": "Phase 1 smoke",
        "body": "hello",
        "rawData": {},
        "metadata": {"projectPath": str(vault / "fake-project")},
    }
    (pending / "20260507T100000Z-manual-smoke-test-1.json").write_text(
        json.dumps(event)
    )

    worker_main.SLEEP_INTERVAL = 0.1

    t = threading.Thread(target=worker_main.run_loop, daemon=True)
    t.start()

    deadline = time.time() + 10
    done_files: list[Path] = []
    while time.time() < deadline:
        done_files = list((queue / "done").glob("*.json"))
        if done_files:
            break
        time.sleep(0.1)

    worker_main._running = False
    t.join(timeout=5)

    assert done_files, "event never moved to done/"
    assert not list(pending.glob("*.json")), "event still in pending/"
    assert not list((queue / "failed").glob("*.json")), "event ended up in failed/"

    audit_files = list((vault / "90-meta" / "audit").glob("*.jsonl"))
    assert audit_files, "no audit log written"
    parsed = [json.loads(l) for l in audit_files[0].read_text().splitlines()]
    success = [r for r in parsed if r.get("event_type") == "event_processed"]
    assert success, f"no event_processed audit line; got {parsed}"
    assert success[0]["event_id"] == "smoke-test-1"
    assert success[0]["status"] == "success"
    # Pipeline now records routing context too.
    assert success[0].get("context") == "consulting"
    assert success[0].get("method") == "path"
