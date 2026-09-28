from __future__ import annotations

import yaml


def _accounts(vault, entries):
    (vault / "90-meta" / "accounts.yaml").write_text(
        yaml.safe_dump({"version": 1, "accounts": entries}), encoding="utf-8")


def _registry(vault):
    return yaml.safe_load((vault / "90-meta" / "accounts.yaml").read_text())["accounts"]


def test_patch_sets_context_and_enabled(client, auth_headers, tmp_vault):
    _accounts(tmp_vault, [{"connector": "gmail", "id": "a@x.com"}])
    r = client.patch("/v1/connectors/gmail/accounts/a@x.com",
                     json={"context": "work", "enabled": False}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == {"id": "a@x.com", "context": "work", "enabled": False, "health": None}
    assert _registry(tmp_vault) == [{"connector": "gmail", "id": "a@x.com", "context": "work", "enabled": False}]


def test_patch_null_unassigns_and_partial_body_keeps_other_field(client, auth_headers, tmp_vault):
    _accounts(tmp_vault, [{"connector": "slack", "id": "acme", "context": "work", "enabled": False}])
    r = client.patch("/v1/connectors/slack/accounts/acme", json={"context": None}, headers=auth_headers)
    assert r.json()["context"] is None and r.json()["enabled"] is False


def test_patch_microsoft_via_teams_id(client, auth_headers, tmp_vault):
    _accounts(tmp_vault, [{"connector": "microsoft", "id": "me@acme.com"}])
    r = client.patch("/v1/connectors/teams_chat/accounts/me@acme.com", json={"context": "consulting"}, headers=auth_headers)
    assert r.status_code == 200 and _registry(tmp_vault)[0]["context"] == "consulting"


def test_patch_errors(client, auth_headers, tmp_vault):
    _accounts(tmp_vault, [{"connector": "gmail", "id": "a@x.com"}])
    assert client.patch("/v1/connectors/joplin/accounts/x", json={}, headers=auth_headers).status_code == 404
    assert client.patch("/v1/connectors/gmail/accounts/nobody@x.com", json={}, headers=auth_headers).status_code == 404
    assert client.patch("/v1/connectors/gmail/accounts/a@x.com", json={"context": "nope"}, headers=auth_headers).status_code == 422


def test_patch_enabled_null_rejected(client, auth_headers, tmp_vault):
    _accounts(tmp_vault, [{"connector": "gmail", "id": "a@x.com"}])
    r = client.patch("/v1/connectors/gmail/accounts/a@x.com", json={"enabled": None}, headers=auth_headers)
    assert r.status_code == 422
    assert _registry(tmp_vault) == [{"connector": "gmail", "id": "a@x.com"}]
