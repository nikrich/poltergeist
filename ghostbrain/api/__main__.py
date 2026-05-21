"""Run the ghostbrain read API as a subprocess from Electron main.

Picks a random free port on 127.0.0.1, generates a random 256-bit hex token,
prints the READY banner to stdout BEFORE handing off to uvicorn (so the parent
process can capture port + token from a single line), then runs the server.

If GHOSTBRAIN_SCHEDULER_ENABLED=1, also boots the in-process scheduler
(connector cron jobs + worker + recorder). When unset/0, the API is the same
read-only sidecar it's always been.
"""
from __future__ import annotations

# PyInstaller fork-bomb guard. Must run BEFORE any other import.
#
# torch / transformers / sentence-transformers / joblib (all bundled) import
# `multiprocessing` at module load. On macOS the default start method is
# `spawn`, which re-execs `sys.executable -B -S -I -c "from
# multiprocessing.resource_tracker import main; main(N)"` to launch the
# resource_tracker helper. `sys.executable` is the PyInstaller binary, and
# the bootloader does not honour `-c` — so unless freeze_support() short-
# circuits, the bundle just runs `__main__.py` again: another full uvicorn
# instance with its own scheduler firing connectors and shelling out to
# `claude -p`. That child does the same on its own ML imports, and the
# population grows on every interaction. PyInstaller's docs are explicit:
# "if the program will use multiprocessing it must call freeze_support() at
# the top of its main script. Otherwise it will go into an infinite loop
# creating new copies of itself." The PyInstaller runtime hook installs a
# `_freeze_support` that detects the spawn argv and sys.exit()s — but only
# if we actually call it. In dev (non-frozen) this is a no-op.
from multiprocessing import freeze_support
freeze_support()

import os

# PyInstaller-bundled Python has no system CA store. requests/httpx-based
# connectors ship certifi internally so they're fine, but slack_sdk falls
# back to stdlib urllib, which calls ssl.create_default_context() — that
# function reads SSL_CERT_FILE, and without it auth.test dies with
# "CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate" in
# the packaged sidecar. Pointing it at certifi's bundled cacert.pem (which
# PyInstaller already collects) fixes Slack and any other stdlib SSL caller.
# setdefault so corporate-MITM users with their own SSL_CERT_FILE keep theirs.
try:
    import certifi as _certifi
    _ca = _certifi.where()
    os.environ.setdefault("SSL_CERT_FILE", _ca)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", _ca)
except Exception:  # noqa: BLE001
    pass

import logging
import secrets
import socket
import sys

import uvicorn

from ghostbrain.api.main import create_app

log = logging.getLogger("ghostbrain.api.main")


def _pick_port() -> int:
    """Bind a transient socket to an OS-assigned port, then close. Race-y but
    fine for the local-only sidecar; uvicorn re-binds the same port immediately."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _scheduler_enabled() -> bool:
    raw = os.environ.get("GHOSTBRAIN_SCHEDULER_ENABLED", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _include_recorder() -> bool:
    raw = os.environ.get("GHOSTBRAIN_RECORDER_ENABLED", "1").strip().lower()
    return raw in ("1", "true", "yes", "on")


def main() -> int:
    token = secrets.token_hex(32)
    port = _pick_port()
    app = create_app(token=token)

    # Wire the scheduler lifecycle BEFORE printing READY, so the desktop can
    # query /v1/scheduler/status immediately and get a real answer.
    scheduler_enabled = _scheduler_enabled()
    if scheduler_enabled:
        from ghostbrain.scheduler_jobs import build as build_scheduler

        scheduler = build_scheduler(include_recorder=_include_recorder())
        app.state.scheduler = scheduler

        @app.on_event("startup")
        async def _start_scheduler() -> None:
            await scheduler.start()

        @app.on_event("shutdown")
        async def _stop_scheduler() -> None:
            await scheduler.stop()
    else:
        app.state.scheduler = None

    # Print the READY banner BEFORE uvicorn takes over output. Parent process
    # parses this single line to capture port + token. Suffix with a hint about
    # scheduler state so debugging double-fetches is one log line away.
    print(
        f"READY port={port} token={token} scheduler={'on' if scheduler_enabled else 'off'}",
        flush=True,
    )

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        log_level="info",
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
