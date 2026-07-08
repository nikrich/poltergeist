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


def test_disconnect_jira_keeps_env_token(env):
    """Verify jira disconnect removes routing but preserves shared Atlassian .env token."""
    from ghostbrain.api.repo.routing import merge_routing, load_routing
    from ghostbrain.api.repo.dotenv_store import set_env, read_env

    # Seed routing and shared Atlassian token
    merge_routing({
        "jira": {"sites": {"acme.atlassian.net": "needs_review"}},
        "confluence": {"sites": {"acme.atlassian.net": "needs_review"}}
    })
    set_env({
        "ATLASSIAN_EMAIL": "me@x.com",
        "ATLASSIAN_TOKEN_ACME": "tok"
    })

    # Disconnect jira
    disconnect("jira", account=None)

    # Verify jira.sites is removed
    routing = load_routing()
    assert "sites" not in routing.get("jira", {}), "jira.sites should be removed"

    # Verify confluence.sites is still present
    assert "sites" in routing.get("confluence", {}), "confluence.sites should remain"

    # Verify .env token is not deleted
    env_vars = read_env()
    assert env_vars.get("ATLASSIAN_EMAIL") == "me@x.com", "ATLASSIAN_EMAIL should be preserved"
    assert env_vars.get("ATLASSIAN_TOKEN_ACME") == "tok", "ATLASSIAN_TOKEN_ACME should be preserved"


def test_disconnect_claude_code_malformed_json_is_noop(env, monkeypatch, tmp_path):
    """Verify claude_code disconnect tolerates malformed settings.json."""
    from pathlib import Path

    # Monkeypatch Path.home to use tmp_path
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    # Create settings.json with non-object JSON (array)
    settings_dir = tmp_path / ".claude"
    settings_dir.mkdir()
    settings_file = settings_dir / "settings.json"
    settings_file.write_text("[1, 2, 3]")

    # Should not raise
    disconnect("claude_code", account=None)

    # Verify settings.json was not modified (it's still invalid)
    assert settings_file.read_text() == "[1, 2, 3]"
