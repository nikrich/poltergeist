"""Drives the MSAL interactive (system-browser loopback) sign-in from the
sidecar, exposing observable state so the desktop UI can trigger + poll it.

One process-singleton holder runs the blocking MSAL call on a worker thread.
The MSAL PublicClientApplication is injectable so tests never open a browser."""
from __future__ import annotations

import threading
from dataclasses import dataclass

from ghostbrain.connectors.microsoft.graph.auth import (
    _build_app,
    cache_location,
    have_token,
    resolve_scopes,
)


@dataclass
class AuthState:
    state: str  # "idle" | "pending" | "connected" | "error"
    account: str | None = None
    error: str | None = None


class AlreadyRunning(RuntimeError):
    """Raised when start() is called while a sign-in is already in flight."""


def _result_error(result: dict) -> str:
    return (
        result.get("error_description")
        or result.get("error")
        or "Microsoft sign-in failed."
    )


class InteractiveAuth:
    def __init__(self, app_factory=_build_app) -> None:
        self._app_factory = app_factory
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._state = AuthState(state="idle")

    def start(self, config: dict) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise AlreadyRunning("a Microsoft sign-in is already in progress")
            self._state = AuthState(state="pending")
            self._thread = threading.Thread(
                target=self._run, args=(config,), daemon=True
            )
            self._thread.start()

    def _run(self, config: dict) -> None:
        try:
            app = self._app_factory(config)
            result = app.acquire_token_interactive(
                resolve_scopes(config), prompt="select_account", timeout=180
            )
            if "access_token" not in result:
                self._set(AuthState(state="error", error=_result_error(result)))
                return
            accounts = app.get_accounts()
            username = accounts[0].get("username") if accounts else None
            self._set(AuthState(state="connected", account=username))
        except Exception as e:  # noqa: BLE001
            self._set(AuthState(state="error", error=str(e) or "Sign-in failed."))

    def _set(self, state: AuthState) -> None:
        with self._lock:
            self._state = state

    def _running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self, config: dict) -> AuthState:
        with self._lock:
            running = self._running()
            snapshot = self._state
        if running or snapshot.state == "error":
            return snapshot
        if have_token(config):
            account = snapshot.account or self._account(config)
            return AuthState(state="connected", account=account)
        return AuthState(state="idle")

    def _account(self, config: dict) -> str | None:
        try:
            accounts = self._app_factory(config).get_accounts()
        except Exception:  # noqa: BLE001
            return None
        return accounts[0].get("username") if accounts else None

    def disconnect(self, config: dict) -> None:
        try:
            app = self._app_factory(config)
            for acct in app.get_accounts():
                app.remove_account(acct)
        except Exception:  # noqa: BLE001
            pass
        try:
            cache_location().unlink(missing_ok=True)
        except OSError:
            pass
        self._set(AuthState(state="idle"))

    def wait(self, timeout: float = 5.0) -> None:
        """Test helper: join the worker thread if one is running."""
        t = self._thread
        if t is not None:
            t.join(timeout)
