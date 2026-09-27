import pytest
from ghostbrain.api.auth.disconnect import disconnect, _safe_account


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


def test_disconnect_jira_keeps_shared_site_token(env):
    """Jira disconnect removes only the jira account; a shared site token stays
    while Confluence still has an account for it."""
    from ghostbrain import accounts
    from ghostbrain.accounts import Account
    from ghostbrain.connectors.atlassian._base import save_token, token_path

    accounts.upsert_account(Account("jira", "acme.atlassian.net"))
    accounts.upsert_account(Account("confluence", "acme.atlassian.net"))
    save_token("acme.atlassian.net", "tok")

    disconnect("jira", account="acme.atlassian.net")

    assert accounts.get_account("jira", "acme.atlassian.net") is None
    assert accounts.get_account("confluence", "acme.atlassian.net") is not None
    assert token_path("acme.atlassian.net").exists(), "Confluence still uses it"


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


def test_disconnect_rejects_path_traversal_account():
    """Verify _safe_account rejects path-manipulating values."""
    # Test rejected cases
    assert _safe_account("../x") is None
    assert _safe_account("a/b") is None
    assert _safe_account("a\\b") is None
    assert _safe_account("x\x00y") is None
    assert _safe_account("..") is None
    assert _safe_account("../../../etc/passwd") is None

    # Test edge cases
    assert _safe_account(None) is None
    assert _safe_account("") is None
    assert _safe_account("   ") is None

    # Test accepted cases
    assert _safe_account("you@gmail.com") == "you@gmail.com"
    assert _safe_account("work") == "work"
    assert _safe_account("you.name@corp.co") == "you.name@corp.co"


def test_disconnect_slack_rejected_account_does_not_delete_all(env):
    """Verify rejected account does not trigger delete-all-workspaces branch."""
    s, _ = env
    # Seed two slack token files
    (s / "slack.work.token").write_text("xoxp-work")
    (s / "slack.other.token").write_text("xoxp-other")

    # Call disconnect with a path-manipulating account
    disconnect("slack", account="../evil")

    # Verify BOTH slack token files STILL EXIST
    assert (s / "slack.work.token").exists(), "slack.work.token should not be deleted"
    assert (s / "slack.other.token").exists(), "slack.other.token should not be deleted"
