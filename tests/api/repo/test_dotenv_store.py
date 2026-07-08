import pytest
from ghostbrain.api.repo.dotenv_store import set_env, remove_env, read_env, env_path


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path / "state"))
    return tmp_path


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
