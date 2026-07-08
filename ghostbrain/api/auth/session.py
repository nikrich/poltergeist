"""In-memory authentication session manager."""
from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field

from ghostbrain.api.auth.providers.base import AuthProvider, NextAction

# status derived from a NextAction kind
_STATUS_FOR_KIND = {
    "need_input": "waiting_input",
    "open_browser": "pending",
    "show_device_code": "pending",
    "need_grant": "pending",
    "done": "success",
}


@dataclass
class Session:
    """Represents an in-progress authentication session."""

    id: str
    connector_id: str
    status: str
    next: NextAction
    account: str | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.monotonic)


class AuthSessionManager:
    """Manages in-progress authentication sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def start(self, connector_id: str, provider: AuthProvider, params: dict) -> Session:
        """Start a new authentication session."""
        action = provider.start(connector_id, params)
        sess = Session(
            id=secrets.token_hex(16),
            connector_id=connector_id,
            status=_STATUS_FOR_KIND.get(action.kind, "pending"),
            next=action,
        )
        if action.kind == "done":
            sess.account = provider.account_label(sess)
        with self._lock:
            self._sessions[sess.id] = sess
        # kick off background poll for long-running flows
        if action.kind in ("open_browser", "show_device_code", "need_grant"):
            threading.Thread(
                target=self._run_poll, args=(sess, provider), daemon=True
            ).start()
        return sess

    def _run_poll(self, sess: Session, provider: AuthProvider) -> None:
        """Run the polling loop for a long-running authentication flow."""
        try:
            provider.poll(sess.connector_id, sess)
        except Exception as e:  # noqa: BLE001
            sess.status = "error"
            sess.error = str(e)

    def status(self, session_id: str) -> Session | None:
        """Get the status of an authentication session."""
        with self._lock:
            return self._sessions.get(session_id)

    def submit(self, session_id: str, provider: AuthProvider, data: dict) -> Session:
        """Submit data to advance an authentication session."""
        sess = self.status(session_id)
        if sess is None:
            raise KeyError(session_id)
        action = provider.submit(sess.connector_id, sess, data)
        sess.next = action
        if sess.status not in ("success", "error"):
            sess.status = _STATUS_FOR_KIND.get(action.kind, sess.status)
        if sess.status == "success" and sess.account is None:
            sess.account = provider.account_label(sess)
        return sess

    def cancel(self, session_id: str) -> None:
        """Cancel an authentication session."""
        with self._lock:
            self._sessions.pop(session_id, None)

    def sweep(self, now: float, ttl_s: float = 300) -> None:
        """Remove expired authentication sessions."""
        with self._lock:
            expired = [sid for sid, s in self._sessions.items() if now - s.created_at > ttl_s]
            for sid in expired:
                del self._sessions[sid]
