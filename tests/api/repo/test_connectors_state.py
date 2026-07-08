import pytest
from ghostbrain.api.repo.connectors import get_connector


@pytest.fixture
def env(tmp_path, monkeypatch):
    s = tmp_path / "state"; s.mkdir()
    v = tmp_path / "vault"; (v / "90-meta").mkdir(parents=True)
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(s))
    monkeypatch.setenv("VAULT_PATH", str(v))
    return s, v


def test_gmail_off_by_default(env):
    assert get_connector("gmail")["state"] == "off"


def test_gmail_account_populated_from_token(env):
    s, _ = env
    (s / "gmail.you_at_gmail_com.token").write_text("{}")
    rec = get_connector("gmail")
    assert rec["state"] == "on"
    assert rec["account"] == "you@gmail.com"


def test_last_run_keeps_connector_on(env):
    s, _ = env
    (s / "github.last_run").write_text("2026-07-01T00:00:00Z")
    # gh probe returns off in CI, but last_run must keep it on
    assert get_connector("github")["state"] == "on"
