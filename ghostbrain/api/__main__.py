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

import atexit  # noqa: E402
import logging
import secrets
import socket
import sys
from datetime import datetime  # noqa: E402
from typing import IO  # noqa: E402

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


def _publish_descriptor(port: int, token: str) -> IO | None:
    """Claim the sidecar singleton and, if won, publish the runtime descriptor.

    The descriptor is a single shared file advertising one sidecar to MCP
    clients. Gating its write on a dedicated ``sidecar`` flock means a second
    instance — a stray ``python -m ghostbrain.api``, a restart race — cannot
    clobber the primary's descriptor or orphan it with a dead pid on a hard
    exit (which surfaced as the chat's vault tools reporting "not running"
    while the app was plainly up). Only the lock holder publishes and, on a
    clean exit, removes the descriptor; a non-holder leaves it untouched.

    Returns the held lock (the caller MUST keep a reference for the process
    lifetime — the OS frees it on exit/crash) or ``None`` if another live
    sidecar already owns the descriptor.

    Cleanup relies on atexit: during the process lifetime uvicorn owns
    SIGTERM/SIGINT and shuts down gracefully, after which the interpreter exits
    normally and atexit fires. On SIGKILL or a crash the stale descriptor is
    harmless — load_descriptor() pid-liveness-checks it, and the next boot
    reclaims the freed lock and republishes.
    """
    from ghostbrain.api import runtime
    from ghostbrain.api.main import API_VERSION

    lock = runtime.acquire_singleton_lock("sidecar")
    if lock is None:
        log.warning(
            "another ghostbrain.api sidecar already owns the descriptor; not "
            "publishing this instance (MCP clients keep using the primary)"
        )
        return None

    runtime.write_descriptor(
        port=port,
        token=token,
        pid=os.getpid(),
        version=API_VERSION,
        started_at=datetime.now().astimezone().isoformat(),
    )
    atexit.register(runtime.remove_descriptor)
    return lock


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    # The packaged build ships one executable. When invoked as `ghostbrain-api
    # mcp` it serves the Poltergeist MCP stdio server instead of the HTTP sidecar
    # — this is how chat gets vault tools without a second, ML-heavy PyInstaller
    # bundle (see ghostbrain.llm.agent.find_mcp_binary).
    if argv and argv[0] == "mcp":
        from ghostbrain.mcp.__main__ import main as mcp_main

        mcp_main()
        return 0

    return _run_api_server()


def _run_api_server() -> int:
    # Import the app stack lazily, AFTER the `mcp` dispatch above. The frozen
    # `ghostbrain-api mcp` subprocess must not pay for — or crash/stall on — the
    # full route tree (uvicorn + every route + their transitive deps) before its
    # MCP handshake; that coupling surfaced as "vault server still connecting".
    import uvicorn

    from ghostbrain.api.main import create_app

    token = secrets.token_hex(32)
    port = _pick_port()
    app = create_app(token=token)
    # Keep the descriptor lock alive for the process lifetime by stashing it on
    # app.state (the OS frees it on exit/crash). None means another sidecar is
    # the primary and owns the descriptor — this instance still serves its
    # parent over HTTP, it just doesn't advertise itself to MCP clients.
    app.state.descriptor_lock = _publish_descriptor(port=port, token=token)

    # Wire the scheduler lifecycle BEFORE printing READY, so the desktop can
    # query /v1/scheduler/status immediately and get a real answer.
    scheduler_enabled = _scheduler_enabled()
    if scheduler_enabled:
        # Single-instance guard: if another ghostbrain.api is already running
        # the scheduler/recorder, do NOT boot a second one. Two schedulers race
        # on the shared recorder state file and double-record meetings — the
        # desktop then can't stop a recording it doesn't own. Hold the lock for
        # the process lifetime (stash on app.state); the OS frees it on
        # exit/crash.
        from ghostbrain.api import runtime

        scheduler_lock = runtime.acquire_singleton_lock("scheduler")
        if scheduler_lock is None:
            log.warning(
                "another ghostbrain.api scheduler is already running; starting "
                "this instance read-only (no scheduler/recorder) to avoid "
                "double-recording meetings"
            )
            scheduler_enabled = False

    if scheduler_enabled:
        from ghostbrain.scheduler_jobs import build as build_scheduler

        app.state.scheduler_lock = scheduler_lock
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
