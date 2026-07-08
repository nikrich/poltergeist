import json
import pytest
from ghostbrain.api.auth.providers.cli_login import GitHubProvider
from ghostbrain.api.auth.providers.local_grant import ClaudeCodeProvider, MacosCalendarProvider
from ghostbrain.api.auth.session import Session
from ghostbrain.api.auth.providers.base import NextAction


def _sess(cid):
    return Session(id="s", connector_id=cid, status="pending", next=NextAction(kind="need_grant"))


def test_github_done_when_logged_in(monkeypatch):
    import ghostbrain.api.auth.providers.cli_login as mod
    monkeypatch.setattr(mod, "_gh_logged_in", lambda: (True, "octocat"))
    action = GitHubProvider().start("github", {})
    assert action.kind == "done"


def test_github_need_grant_when_logged_out(monkeypatch):
    import ghostbrain.api.auth.providers.cli_login as mod
    monkeypatch.setattr(mod, "_gh_logged_in", lambda: (False, None))
    action = GitHubProvider().start("github", {})
    assert action.kind == "need_grant"
    assert "gh auth login" in (action.message or "")


def test_claude_code_writes_hook(tmp_path, monkeypatch):
    home = tmp_path
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    (home / ".claude").mkdir()
    (home / ".claude" / "settings.json").write_text(json.dumps({"hooks": {}}))
    monkeypatch.setenv("VAULT_PATH", str(tmp_path / "vault"))
    (tmp_path / "vault" / "90-meta").mkdir(parents=True)
    p = ClaudeCodeProvider()
    sess = _sess("claude_code")
    p.submit("claude_code", sess, {"hook_script": "/x/session-end.sh"})
    assert sess.status == "success"
    data = json.loads((home / ".claude" / "settings.json").read_text())
    assert "SessionEnd" in data["hooks"]


def test_github_submit_is_noop():
    sess = _sess("github")
    action = GitHubProvider().submit("github", sess, {})
    assert action is sess.next
    assert sess.status == "pending"


def test_macos_submit_is_noop():
    sess = _sess("macos_calendar")
    action = MacosCalendarProvider().submit("macos_calendar", sess, {})
    assert action is sess.next
    assert sess.status == "pending"


def test_macos_poll_denied_sets_error(monkeypatch):
    import ghostbrain.api.auth.providers.local_grant as mod
    monkeypatch.setattr(mod, "_macos_calendar_authorized", lambda: False)
    sess = _sess("macos_calendar")
    MacosCalendarProvider().poll("macos_calendar", sess)
    assert sess.status == "error"
    assert sess.next.kind == "need_grant"


def test_macos_poll_success_when_authorized(monkeypatch):
    import ghostbrain.api.auth.providers.local_grant as mod
    monkeypatch.setattr(mod, "_macos_calendar_authorized", lambda: True)
    sess = _sess("macos_calendar")
    MacosCalendarProvider().poll("macos_calendar", sess)
    assert sess.status == "success"
    assert sess.next.kind == "done"


def test_macos_poll_success_when_unknown(monkeypatch):
    import ghostbrain.api.auth.providers.local_grant as mod
    monkeypatch.setattr(mod, "_macos_calendar_authorized", lambda: None)
    sess = _sess("macos_calendar")
    MacosCalendarProvider().poll("macos_calendar", sess)
    assert sess.status == "success"
    assert sess.next.kind == "done"
