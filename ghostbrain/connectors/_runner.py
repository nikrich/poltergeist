"""Shared helpers for invoking connectors from the in-process scheduler.

The CLI `__main__.py` files stay untouched — they're what existing launchd
plists call. These helpers exist so the scheduler can call the same
connector logic in-process and capture results structurally instead of
parsing log lines.

Each connector ships a thin `runner.py` that imports `run_connector` (or
calls it directly) and returns a `RunResult`.
"""
from __future__ import annotations

import logging
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from ghostbrain.paths import queue_dir, state_dir, vault_path

log = logging.getLogger("ghostbrain.connectors.runner")


def _audit(event_type: str, name: str, **fields: Any) -> None:
    """Best-effort write to the worker audit log. Swallows failures (e.g.,
    vault unmounted, disk full) so an audit hiccup never propagates into
    the scheduler's status."""
    try:
        from ghostbrain.worker.audit import audit_log
        audit_log(event_type, name, **fields)
    except Exception:  # noqa: BLE001
        log.exception("audit_log failed for %s/%s", event_type, name)


@dataclass
class RunResult:
    """Structured outcome of one connector invocation. Stored in scheduler
    state so the UI can show last-run + error without parsing logs."""

    connector: str
    ok: bool
    started_at: float  # epoch seconds
    finished_at: float
    queued: int = 0
    skipped_reason: str | None = None  # set when ok=True but nothing was done
    error: str | None = None
    error_type: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> int:
        return int((self.finished_at - self.started_at) * 1000)


def load_routing() -> dict:
    """Read vault/90-meta/routing.yaml — the per-connector configuration."""
    f = vault_path() / "90-meta" / "routing.yaml"
    if not f.exists():
        return {}
    return yaml.safe_load(f.read_text(encoding="utf-8")) or {}


def ensure_dirs() -> tuple[Path, Path]:
    """Create + return (queue_dir, state_dir)."""
    q = queue_dir()
    s = state_dir()
    q.mkdir(parents=True, exist_ok=True)
    s.mkdir(parents=True, exist_ok=True)
    return q, s


def run_connector(
    name: str,
    *,
    build: Callable[[dict, Path, Path], object | None],
) -> RunResult:
    """Boilerplate around a connector invocation.

    `build` reads the routing config (already loaded), the queue dir, and
    the state dir, and either returns a Connector instance ready to .run()
    or None to skip (e.g. nothing configured).

    Health-check failures, exceptions, and "nothing configured" all turn
    into a RunResult — the scheduler never sees an exception leak out.
    """
    started = time.time()
    try:
        routing = load_routing()
        q, s = ensure_dirs()
        connector = build(routing, q, s)
        if connector is None:
            _audit("connector_skipped", name, reason="not_configured")
            return RunResult(
                connector=name,
                ok=True,
                started_at=started,
                finished_at=time.time(),
                skipped_reason="not configured",
            )
        if not connector.health_check():  # type: ignore[attr-defined]
            _audit("connector_health_failed", name)
            return RunResult(
                connector=name,
                ok=False,
                started_at=started,
                finished_at=time.time(),
                error="health check failed",
                error_type="HealthCheckFailed",
            )
        queued = connector.run()  # type: ignore[attr-defined]
        _audit("connector_run", name, events_queued=int(queued))
        return RunResult(
            connector=name,
            ok=True,
            started_at=started,
            finished_at=time.time(),
            queued=int(queued),
        )
    except Exception as e:  # noqa: BLE001 — we want to capture EVERY failure
        log.exception("connector %s crashed", name)
        _audit("connector_crashed", name, error=f"{type(e).__name__}: {e}")
        return RunResult(
            connector=name,
            ok=False,
            started_at=started,
            finished_at=time.time(),
            error=str(e),
            error_type=type(e).__name__,
            details={"traceback": traceback.format_exc(limit=5)},
        )
