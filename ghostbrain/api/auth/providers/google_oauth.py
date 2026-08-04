"""Google OAuth provider for Gmail and Calendar connectors.

Reuses the per-connector auth modules (gmail.auth, calendar.google.auth) which
both expose oauth_client_path() and run_oauth_flow(email). The client JSON is
shared; if missing, start() asks for it and submit() writes it. Then per account,
submit() triggers an open_browser flow and poll() runs it.
"""
from __future__ import annotations

from ghostbrain.api.auth.providers.base import NextAction


def _mod(connector_id: str):
    """Return the auth module for the given connector (gmail or calendar)."""
    if connector_id == "gmail":
        from ghostbrain.connectors.gmail import auth as m
        return m
    from ghostbrain.connectors.calendar.google import auth as m
    return m


class GoogleProvider:
    pattern = "google_oauth"

    def __init__(self) -> None:
        self._flows: dict[str, object] = {}  # session_id -> flow (for cancel)

    def _account_field(self, connector_id: str) -> NextAction:
        return NextAction(
            kind="need_input",
            message=("A browser window will open for Google consent. Google shows an "
                     '"unverified app" warning for your own client — choose Advanced → Continue.'),
            fields=[{"name": "account", "label": "Google account email", "type": "text",
                     "placeholder": "you@gmail.com"}],
        )

    def start(self, connector_id: str, params: dict) -> NextAction:
        """Start a new authentication session.

        If the client JSON is missing, ask for it. Otherwise, ask for the account.
        """
        m = _mod(connector_id)
        if not m.oauth_client_path().exists():
            return NextAction(
                kind="need_input",
                message="Paste the Desktop OAuth client JSON you downloaded from Google Cloud.",
                fields=[{"name": "client_json", "label": "OAuth client JSON", "type": "textarea"}],
            )
        return self._account_field(connector_id)

    def submit(self, connector_id: str, session, data: dict) -> NextAction:
        """Submit data to advance the authentication session.

        If client_json is provided, write it and ask for the account.
        If account is provided, trigger the browser flow (poll() will run it).
        """
        m = _mod(connector_id)
        if "client_json" in data and data["client_json"].strip():
            path = m.oauth_client_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(data["client_json"].strip(), encoding="utf-8")
            path.chmod(0o600)
            action = self._account_field(connector_id)
            session.status = "waiting_input"
            session.next = action
            return action
        account = (data.get("account") or "").strip()
        if not account:
            session.status = "error"
            session.error = "Account email is required"
            return NextAction(kind="need_input", fields=[])
        # Hand off to the browser flow; poll() will run it.
        # Store target account on session for poll() to read.
        session._google_account = account  # type: ignore[attr-defined]
        session.status = "pending"
        action = NextAction(
            kind="open_browser",
            auth_url="about:blank",
            message="Opening your browser for Google sign-in…"
        )
        session.next = action
        # AuthSessionManager.submit() will spawn poll() for this long-running action.
        # Do NOT manually spawn a thread here.
        return action

    def poll(self, connector_id: str, session) -> None:
        """Poll for the browser-based OAuth flow completion.

        Reads the account email from session._google_account, calls the connector's
        run_oauth_flow() which opens the browser and polls the local redirect server,
        then sets the session to success or error.
        """
        m = _mod(connector_id)
        account = getattr(session, "_google_account", None)
        if not account:
            session.status = "error"
            session.error = "No account specified"
            return
        try:
            m.run_oauth_flow(account)  # opens system browser, run_local_server catches redirect
        except Exception as e:  # noqa: BLE001
            session.status = "error"
            session.error = str(e)
            return
        session.status = "success"
        session.account = account
        session.next = NextAction(kind="done")

    def account_label(self, session) -> str | None:
        """Return a display label for the authenticated account."""
        return session.account
