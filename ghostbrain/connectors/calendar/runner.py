"""In-process runner for the Calendar connectors (google + macos).

The CLI runs both providers and continues past one failing. This runner
mirrors that behavior: returns ok=True if at least one provider ran cleanly
and at least one was configured; surfaces the first error otherwise.
"""
from __future__ import annotations

import logging
import time
import traceback

from ghostbrain.connectors._runner import RunResult, ensure_dirs, load_routing
from ghostbrain.connectors.calendar.google import GoogleCalendarConnector
from ghostbrain.connectors.calendar.google.auth import GoogleAuthError
from ghostbrain.connectors.calendar.macos import MacosCalendarConnector

log = logging.getLogger("ghostbrain.connectors.calendar.runner")


def run() -> RunResult:
    started = time.time()
    try:
        routing = load_routing()
        queue_dir, state_dir = ensure_dirs()
    except Exception as e:  # noqa: BLE001
        return RunResult(
            connector="calendar",
            ok=False,
            started_at=started,
            finished_at=time.time(),
            error=str(e),
            error_type=type(e).__name__,
        )

    cal_cfg = routing.get("calendar") or {}
    providers = []

    google_cfg = cal_cfg.get("google") or {}
    google_accounts = dict(google_cfg.get("accounts") or {})
    if google_accounts:
        providers.append((
            "google",
            GoogleCalendarConnector(
                config={
                    "accounts": google_accounts,
                    "calendars_per_account": google_cfg.get("calendars_per_account") or {},
                },
                queue_dir=queue_dir,
                state_dir=state_dir,
            ),
        ))

    macos_cfg = cal_cfg.get("macos") or {}
    macos_accounts = dict(macos_cfg.get("accounts") or {})
    if macos_accounts:
        providers.append((
            "macos",
            MacosCalendarConnector(
                config={"accounts": macos_accounts},
                queue_dir=queue_dir,
                state_dir=state_dir,
            ),
        ))

    if not providers:
        return RunResult(
            connector="calendar",
            ok=True,
            started_at=started,
            finished_at=time.time(),
            skipped_reason="not configured",
        )

    total_queued = 0
    per_provider: dict[str, dict] = {}
    first_error: tuple[str, str, str] | None = None  # (provider, type, message)

    for name, connector in providers:
        try:
            queued = connector.run()
            per_provider[name] = {"ok": True, "queued": int(queued)}
            total_queued += int(queued)
        except GoogleAuthError as e:
            log.error("calendar.google auth error: %s", e)
            per_provider[name] = {"ok": False, "error": str(e), "error_type": "GoogleAuthError"}
            if first_error is None:
                first_error = (name, "GoogleAuthError", str(e))
        except Exception as e:  # noqa: BLE001
            log.exception("calendar.%s failed", name)
            per_provider[name] = {
                "ok": False,
                "error": str(e),
                "error_type": type(e).__name__,
                "traceback": traceback.format_exc(limit=5),
            }
            if first_error is None:
                first_error = (name, type(e).__name__, str(e))

    ok = first_error is None
    return RunResult(
        connector="calendar",
        ok=ok,
        started_at=started,
        finished_at=time.time(),
        queued=total_queued,
        error=None if ok else f"{first_error[0]}: {first_error[2]}",  # type: ignore[index]
        error_type=None if ok else first_error[1],  # type: ignore[index]
        details={"providers": per_provider},
    )
