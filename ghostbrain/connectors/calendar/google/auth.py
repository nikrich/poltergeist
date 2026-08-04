"""Google Calendar OAuth helpers.

Tokens live at ``~/.ghostbrain/state/google_calendar.<slug>.token`` and
are managed per-account. The OAuth client (Desktop app credentials) lives
at ``~/.ghostbrain/state/google_oauth_client.json`` and is shared.

The interactive consent flow runs once per account via
``ghostbrain-calendar-auth google <email>``; subsequent fetches use the
saved refresh token silently.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

log = logging.getLogger("ghostbrain.connectors.calendar.google.auth")

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


class GoogleAuthError(RuntimeError):
    """Raised when Google credentials are missing, expired beyond refresh,
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
    return state_dir() / f"google_calendar.{slug}.token"


def load_credentials(account_email: str):
    """Return refreshed `google.oauth2.credentials.Credentials` for the
    account. Raises ``GoogleAuthError`` when missing or unrefreshable."""
    # Lazy import — heavy and only this path needs them.
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    tpath = token_path(account_email)
    if not tpath.exists():
        raise GoogleAuthError(
            f"No saved token for {account_email}. "
            f"Run: ghostbrain-calendar-auth google {account_email}"
        )
    creds = Credentials.from_authorized_user_file(str(tpath), SCOPES)

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError as e:
                raise GoogleAuthError(
                    f"Refresh token rejected for {account_email}: {e}. "
                    f"Re-run: ghostbrain-calendar-auth google {account_email}"
                ) from e
            tpath.write_text(creds.to_json(), encoding="utf-8")
            tpath.chmod(0o600)
        else:
            raise GoogleAuthError(
                f"Credentials invalid for {account_email} and no refresh "
                "token available. Re-run the auth command."
            )

    return creds


def run_oauth_flow(account_email: str) -> Path:
    """Open a browser, walk the user through Google consent, save the
    resulting token. Returns the token file path."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    client_path = oauth_client_path()
    if not client_path.exists():
        raise GoogleAuthError(
            f"OAuth client config not found at {client_path}. "
            "Create a Desktop OAuth client at "
            "https://console.cloud.google.com/apis/credentials and "
            "download the JSON to that path."
        )

    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_path),
        SCOPES,
    )
    # `run_local_server` spins up a local listener for the OAuth redirect.
    # `login_hint` pre-fills the account selector with the email we want.
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
