import os

import pytest
from ghostbrain.api.repo.dotenv_store import set_env, remove_env, read_env, env_path


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path / "state"))
    return tmp_path


@pytest.fixture
def clean_process_env():
    """Save/restore os.environ around a test so live-env mutations don't leak."""
    saved = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


def test_set_and_read(home):
    set_env({"ATLASSIAN_EMAIL": "me@x.com", "ATLASSIAN_TOKEN_SFT": "tok"})
    assert read_env()["ATLASSIAN_EMAIL"] == "me@x.com"
    assert read_env()["ATLASSIAN_TOKEN_SFT"] == "tok"


def test_upsert_preserves_others(home):
    set_env({"A": "1"})
    set_env({"B": "2"})
    env = read_env()
    assert env["A"] == "1" and env["B"] == "2"


def test_remove(home):
    set_env({"A": "1", "B": "2"})
    remove_env(["A"])
    assert "A" not in read_env()
    assert read_env()["B"] == "2"


def test_set_env_updates_process_env(home, clean_process_env):
    os.environ.pop("ATLASSIAN_TOKEN_ACME", None)
    set_env({"ATLASSIAN_TOKEN_ACME": "tok"})
    assert os.environ["ATLASSIAN_TOKEN_ACME"] == "tok"


def test_remove_env_updates_process_env(home, clean_process_env):
    set_env({"ATLASSIAN_TOKEN_ACME": "tok"})
    assert os.environ["ATLASSIAN_TOKEN_ACME"] == "tok"
    remove_env(["ATLASSIAN_TOKEN_ACME"])
    assert "ATLASSIAN_TOKEN_ACME" not in os.environ
