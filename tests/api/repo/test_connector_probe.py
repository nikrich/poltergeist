import os
from pathlib import Path
import pytest
from ghostbrain.api.repo.connector_probe import probe, ProbeResult


@pytest.fixture
def state(tmp_path, monkeypatch):
    d = tmp_path / "state"
    d.mkdir()
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(d))
    # Clean up any SLACK_TOKEN_* env vars that might be in the environment
    for key in list(os.environ.keys()):
        if key.startswith("SLACK_TOKEN_"):
            monkeypatch.delenv(key, raising=False)
    return d


def test_gmail_off_when_no_token(state):
    r = probe("gmail")
    assert r.state == "off"
    assert r.account is None


def test_gmail_on_when_token_present(state):
    (state / "gmail.you_at_gmail_com.token").write_text("{}")
    r = probe("gmail")
    assert r.state == "on"
    assert r.account == "you@gmail.com"


def test_slack_off_when_no_token(state):
    assert probe("slack").state == "off"


def test_slack_on_when_token_file_present(state):
    (state / "slack.work.token").write_text("xoxp-abc\n")
    assert probe("slack").state == "on"
