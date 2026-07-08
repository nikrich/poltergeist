import pytest
from ghostbrain.api.auth.disconnect import disconnect


@pytest.fixture
def env(tmp_path, monkeypatch):
    s = tmp_path / "state"; s.mkdir()
    v = tmp_path / "vault"; (v / "90-meta").mkdir(parents=True)
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(s))
    monkeypatch.setenv("VAULT_PATH", str(v))
    return s, v


def test_disconnect_slack_removes_token_file(env):
    s, _ = env
    (s / "slack.work.token").write_text("xoxp")
    disconnect("slack", account="work")
    assert not (s / "slack.work.token").exists()


def test_disconnect_joplin_removes_routing_token(env):
    from ghostbrain.api.repo.routing import merge_routing, load_routing
    merge_routing({"joplin": {"token": "abc", "host": "h"}})
    disconnect("joplin", account=None)
    assert "token" not in load_routing().get("joplin", {})


def test_disconnect_missing_is_noop(env):
    disconnect("gmail", account="nobody@x.com")  # must not raise
