"""Gmail OAuth helpers.

Reuses the same ``google_oauth_client.json`` Desktop OAuth client that
the calendar connector already uses — Google scopes are independent, so
adding Gmail does not require a second OAuth client. Tokens live at
``~/.ghostbrain/state/gmail.<slug>.token`` per account.

Run ``ghostbrain-gmail-auth <email>`` once for the browser consent flow;
subsequent fetches use the saved refresh token silently.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger("ghostbrain.connectors.gmail.auth")

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class GmailAuthError(RuntimeError):
    """Raised when Gmail credentials are missing, expired beyond refresh,
    or otherwise unusable."""


def state_dir() -> Path:
    raw = os.environ.get("GHOSTBRAIN_STATE_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".ghostbrain" / "state").resolve()


def oauth_client_path() -> Path:
    return state_dir() / "google_oauth_client.json"


def token_path(account_email: str) -> Path:
    slug = (
        account_email.lower()
        .replace("@", "_at_")
        .replace(".", "_")
    )
    return state_dir() / f"gmail.{slug}.token"


def load_credentials(account_email: str):
    """Return refreshed Google ``Credentials`` for the account. Raises
    ``GmailAuthError`` when missing or unrefreshable."""
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    tpath = token_path(account_email)
    if not tpath.exists():
        raise GmailAuthError(
            f"No saved token for {account_email}. "
            f"Run: ghostbrain-gmail-auth {account_email}"
        )
    creds = Credentials.from_authorized_user_file(str(tpath), SCOPES)

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError as e:
                raise GmailAuthError(
                    f"Refresh token rejected for {account_email}: {e}. "
                    f"Re-run: ghostbrain-gmail-auth {account_email}"
                ) from e
            tpath.write_text(creds.to_json(), encoding="utf-8")
            tpath.chmod(0o600)
        else:
            raise GmailAuthError(
                f"Credentials invalid for {account_email} and no refresh "
                "token available. Re-run the auth command."
            )

    return creds


def run_oauth_flow(account_email: str) -> Path:
    """Open a browser, walk the user through Google consent for the
    Gmail read scope, save the resulting token. Returns the token path."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    client_path = oauth_client_path()
    if not client_path.exists():
        raise GmailAuthError(
            f"OAuth client config not found at {client_path}. "
            "Create a Desktop OAuth client at "
            "https://console.cloud.google.com/apis/credentials and "
            "download the JSON to that path."
        )

    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_path),
        SCOPES,
    )
    creds = flow.run_local_server(
        port=0,
        open_browser=True,
        login_hint=account_email,
        prompt="consent",
        access_type="offline",
    )

    tpath = token_path(account_email)
    tpath.parent.mkdir(parents=True, exist_ok=True)
    tpath.write_text(creds.to_json(), encoding="utf-8")
    tpath.chmod(0o600)
    return tpath
