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


def test_refreshed_token_written_atomically_with_600(monkeypatch):
    """Refreshed Google Drive tokens are written atomically with mode 600."""
    import os
    import stat
    import sys

    from google.oauth2.credentials import Credentials

    from ghostbrain.connectors.gdrive import auth

    class FakeCreds:
        valid = False
        expired = True
        refresh_token = "r"

        def refresh(self, request):
            pass

        def to_json(self):
            return '{"token": "new"}'

    tpath = auth.token_path("a@x.com")
    tpath.parent.mkdir(parents=True, exist_ok=True)
    tpath.write_text('{"token": "old"}', encoding="utf-8")
    monkeypatch.setattr(Credentials, "from_authorized_user_file",
                        classmethod(lambda cls, *a, **k: FakeCreds()))
    replaced: list[tuple] = []
    real_replace = os.replace

    def spy(src, dst):
        replaced.append((os.fspath(src), os.fspath(dst)))
        if sys.platform != "win32":
            assert stat.S_IMODE(os.stat(src).st_mode) == 0o600
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    auth.load_credentials("a@x.com")

    assert len(replaced) == 1
    src, dst = replaced[0]
    assert dst == os.fspath(tpath)
    assert os.path.dirname(src) == os.fspath(tpath.parent) and src != dst
    assert not os.path.exists(src)
    assert tpath.read_text(encoding="utf-8") == '{"token": "new"}'
    if sys.platform != "win32":
        assert stat.S_IMODE(tpath.stat().st_mode) == 0o600
    assert [p.name for p in tpath.parent.iterdir()] == [tpath.name]
