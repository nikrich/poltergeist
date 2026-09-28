from __future__ import annotations

import pytest


def test_slug_and_token_path():
    from ghostbrain.connectors.gdrive import auth

    assert auth.slug("You.Name@Gmail.com") == "you_name_at_gmail_com"
    assert auth.token_path("you@x.com").name == "gdrive.you_at_x_com.token"
    assert auth.SCOPES == ["https://www.googleapis.com/auth/drive.readonly"]


def test_oauth_client_is_shared_with_gmail():
    from ghostbrain.connectors.gdrive import auth
    from ghostbrain.connectors.gmail import auth as gmail_auth

    assert auth.oauth_client_path() == gmail_auth.oauth_client_path()


def test_load_credentials_without_token_raises():
    from ghostbrain.connectors.gdrive import auth

    with pytest.raises(auth.GdriveAuthError, match="No saved token"):
        auth.load_credentials("nobody@x.com")


def test_gdrive_is_an_account_connector():
    from ghostbrain import accounts

    assert "gdrive" in accounts.ACCOUNT_CONNECTORS
    assert accounts.SOURCE_TO_ACCOUNT_CONNECTOR["gdrive"] == "gdrive"
    assert accounts.account_connector_for_event({"source": "gdrive"}) == "gdrive"
