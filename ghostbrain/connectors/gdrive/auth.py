"""Google Drive OAuth helpers.

Reuses the shared ``google_oauth_client.json`` Desktop OAuth client that Gmail
and Calendar use; ``drive.readonly`` also authorises read calls to the Docs and
Sheets APIs. Tokens live at ``<state>/gdrive.<slug>.token`` per account.
"""

from __future__ import annotations

import os
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


class GdriveAuthError(RuntimeError):
    """Drive credentials are missing, expired beyond refresh, or rejected."""


def state_dir() -> Path:
    raw = os.environ.get("GHOSTBRAIN_STATE_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".ghostbrain" / "state").resolve()


def slug(account_email: str) -> str:
    return account_email.lower().replace("@", "_at_").replace(".", "_")


def oauth_client_path() -> Path:
    return state_dir() / "google_oauth_client.json"


def token_path(account_email: str) -> Path:
    return state_dir() / f"gdrive.{slug(account_email)}.token"


def load_credentials(account_email: str):
    """Return refreshed Google ``Credentials``; raises ``GdriveAuthError``."""
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    from ghostbrain.connectors.gmail.auth import _write_token_atomic

    tpath = token_path(account_email)
    if not tpath.exists():
        raise GdriveAuthError(
            f"No saved token for {account_email}. Connect Google Drive in the app."
        )
    creds = Credentials.from_authorized_user_file(str(tpath), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError as e:
                raise GdriveAuthError(
                    f"Refresh token rejected for {account_email}: {e}. Reauthorize."
                ) from e
            _write_token_atomic(tpath, creds.to_json())
        else:
            raise GdriveAuthError(
                f"Credentials invalid for {account_email} and no refresh token. Reauthorize."
            )
    return creds


def run_oauth_flow(account_email: str) -> Path:
    """Browser consent for the Drive read scope; saves and returns the token path."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    from ghostbrain.connectors.gmail.auth import _write_token_atomic

    client_path = oauth_client_path()
    if not client_path.exists():
        raise GdriveAuthError(
            f"OAuth client config not found at {client_path}. Create a Desktop OAuth "
            "client at https://console.cloud.google.com/apis/credentials."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(client_path), SCOPES)
    creds = flow.run_local_server(
        port=0, open_browser=True, login_hint=account_email,
        prompt="consent", access_type="offline",
    )
    tpath = token_path(account_email)
    tpath.parent.mkdir(parents=True, exist_ok=True)
    _write_token_atomic(tpath, creds.to_json())
    return tpath
