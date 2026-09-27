"""Account -> context routing sits after specific rules and before the LLM."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ghostbrain.worker import router as router_mod


@pytest.fixture
def v(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    meta = root / "90-meta"
    meta.mkdir(parents=True)
    (meta / "routing.yaml").write_text(yaml.safe_dump({
        "contexts": ["personal", "agencyx", "agencyy"],
        "gmail": {"sender_domains": {"agencyx.com": "agencyx"}},
        "github": {"orgs": {"agencyy-org": "agencyy"}},
        "confluence": {"spaces": {"YDOCS": "agencyy"}},
        "calendar": {"macos": {"accounts": {"Work": "agencyx"}}},
    }), encoding="utf-8")
    (meta / "accounts.yaml").write_text(yaml.safe_dump({"version": 1, "accounts": [
        {"connector": "gmail", "id": "me@gmail.com", "context": "personal"},
        {"connector": "gmail", "id": "unassigned@gmail.com"},
        {"connector": "gmail", "id": "stale@gmail.com", "context": "gone"},
        {"connector": "slack", "id": "agencyx", "context": "agencyx"},
        {"connector": "calendar_google", "id": "me@agencyx.com", "context": "agencyx"},
        {"connector": "jira", "id": "agencyx.atlassian.net", "context": "agencyx"},
        {"connector": "confluence", "id": "agencyx.atlassian.net", "context": "agencyx"},
        {"connector": "github", "id": "nikrich", "context": "personal"},
        {"connector": "microsoft", "id": "me@agencyy.com", "context": "agencyy"},
    ]}), encoding="utf-8")
    return root


def _routing(root: Path) -> dict:
    return yaml.safe_load((root / "90-meta" / "routing.yaml").read_text(encoding="utf-8"))


@pytest.mark.parametrize("event,ctx", [
    ({"source": "gmail", "metadata": {"accountId": "me@gmail.com", "from_domain": "random.org"}}, "personal"),
    ({"source": "slack", "metadata": {"accountId": "agencyx", "workspace_slug": "agencyx"}}, "agencyx"),
    ({"source": "calendar", "metadata": {"provider": "google", "account": "me@agencyx.com",
                                         "accountId": "me@agencyx.com"}}, "agencyx"),
    ({"source": "jira", "metadata": {"accountId": "agencyx.atlassian.net", "site": "agencyx.atlassian.net"}}, "agencyx"),
    ({"source": "github", "metadata": {"accountId": "nikrich", "repo": "someone/else"}}, "personal"),
    ({"source": "teams_chat", "metadata": {"accountId": "ME@agencyy.com"}}, "agencyy"),
])
def test_account_rule_routes_each_connector(v, event, ctx):
    d = router_mod._fast_route({"id": "e1", **event}, _routing(v))
    assert d is not None
    assert (d.context, d.method, d.confidence) == (ctx, "account", 0.95)


def test_sender_domain_beats_account(v):
    ev = {"id": "e", "source": "gmail", "metadata": {"accountId": "me@gmail.com", "from_domain": "agencyx.com"}}
    d = router_mod._fast_route(ev, _routing(v))
    assert (d.context, d.method) == ("agencyx", "path")


def test_github_org_beats_account(v):
    ev = {"id": "e", "source": "github", "metadata": {"accountId": "nikrich", "org": "agencyy-org"}}
    d = router_mod._fast_route(ev, _routing(v))
    assert (d.context, d.method) == ("agencyy", "path")


def test_confluence_space_beats_account(v):
    ev = {"id": "e", "source": "confluence",
          "metadata": {"accountId": "agencyx.atlassian.net", "space": "YDOCS"}}
    d = router_mod._fast_route(ev, _routing(v))
    assert (d.context, d.method) == ("agencyy", "path")


def test_macos_calendar_rule_unaffected(v):
    ev = {"id": "e", "source": "calendar", "metadata": {"provider": "macos", "account": "Work", "accountId": "Work"}}
    d = router_mod._fast_route(ev, _routing(v))
    assert (d.context, d.method) == ("agencyx", "path")


@pytest.mark.parametrize("account_id", ["unassigned@gmail.com", "stale@gmail.com", "stranger@gmail.com", None])
def test_unassigned_or_stale_account_falls_through_to_llm(v, account_id):
    ev = {"id": "e", "source": "gmail", "metadata": {"accountId": account_id, "from_domain": "random.org"}}
    assert router_mod._fast_route(ev, _routing(v)) is None


def test_account_rule_skips_llm_in_route_event(v, monkeypatch):
    def no_llm(*a, **k):
        raise AssertionError("LLM must not be called")

    monkeypatch.setattr(router_mod, "_route_via_llm", no_llm)
    ev = {"id": "e", "source": "slack", "title": "hi", "body": "hello",
          "metadata": {"accountId": "agencyx", "workspace_slug": "agencyx"}}
    d = router_mod.route_event(ev, routing=_routing(v), config={})
    assert (d.context, d.method) == ("agencyx", "account")


def test_legacy_routing_blocks_no_longer_route(v):
    """The workspace/site/calendar-account rules moved into accounts.yaml."""
    routing = {**_routing(v),
               "slack": {"workspaces": {"legacy": {"context": "agencyx"}}},
               "jira": {"sites": {"legacy.atlassian.net": "agencyx"}},
               "calendar": {"google": {"accounts": {"legacy@x.com": "agencyx"}}}}
    for ev in (
        {"id": "e", "source": "slack", "metadata": {"workspace_slug": "legacy"}},
        {"id": "e", "source": "jira", "metadata": {"site": "legacy.atlassian.net"}},
        {"id": "e", "source": "calendar", "metadata": {"provider": "google", "account": "legacy@x.com"}},
    ):
        assert router_mod._fast_route(ev, routing) is None


def test_account_route_survives_registry_errors(v, monkeypatch, caplog):
    def boom(*a, **k):
        raise RuntimeError("accounts.yaml exploded")

    monkeypatch.setattr(router_mod.accounts, "context_for", boom)
    ev = {"id": "e1", "source": "gmail", "metadata": {"accountId": "me@gmail.com"}}
    assert router_mod._account_route(ev) is None
    assert any("accounts.yaml exploded" in r.getMessage() for r in caplog.records)
