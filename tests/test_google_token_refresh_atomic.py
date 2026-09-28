"""Refreshed Google OAuth tokens are written atomically with mode 600."""
from __future__ import annotations

import os
import stat
import sys

import pytest

from ghostbrain.connectors.calendar.google import auth as cal_auth
from ghostbrain.connectors.gmail import auth as gmail_auth


class FakeCreds:
    valid = False
    expired = True
    refresh_token = "r"

    def refresh(self, request):
        pass

    def to_json(self):
        return '{"token": "new"}'


@pytest.mark.parametrize("mod", [gmail_auth, cal_auth], ids=["gmail", "calendar"])
def test_refreshed_token_replaced_atomically_with_600(mod, monkeypatch):
    from google.oauth2.credentials import Credentials

    tpath = mod.token_path("a@x.com")
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
    mod.load_credentials("a@x.com")

    assert len(replaced) == 1
    src, dst = replaced[0]
    assert dst == os.fspath(tpath)
    assert os.path.dirname(src) == os.fspath(tpath.parent) and src != dst
    assert not os.path.exists(src)
    assert tpath.read_text(encoding="utf-8") == '{"token": "new"}'
    if sys.platform != "win32":
        assert stat.S_IMODE(tpath.stat().st_mode) == 0o600
    assert [p.name for p in tpath.parent.iterdir()] == [tpath.name]
