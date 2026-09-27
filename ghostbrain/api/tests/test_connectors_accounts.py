from __future__ import annotations

from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from ghostbrain import accounts_health


def _accounts(vault: Path, entries: list[dict]) -> None:
    (vault / "90-meta" / "accounts.yaml").write_text(
        yaml.safe_dump({"version": 1, "accounts": entries}), encoding="utf-8")


def test_detail_lists_accounts_with_health(client: TestClient, auth_headers, tmp_vault: Path):
    _accounts(tmp_vault, [
        {"connector": "gmail", "id": "a@x.com", "context": "work"},
        {"connector": "gmail", "id": "b@x.com"},
    ])
    accounts_health.record("gmail", "a@x.com", accounts_health.STATUS_OK)
    body = client.get("/v1/connectors/gmail", headers=auth_headers).json()
    assert body["account"] == "2 accounts"
    by_id = {a["id"]: a for a in body["accounts"]}
    assert by_id["a@x.com"]["context"] == "work"
    assert by_id["a@x.com"]["health"]["status"] == "ok"
    assert by_id["b@x.com"]["health"] is None


def test_single_account_summary_and_microsoft_shared(client, auth_headers, tmp_vault):
    _accounts(tmp_vault, [{"connector": "microsoft", "id": "me@agencyy.com"}])
    rows = {c["id"]: c for c in client.get("/v1/connectors", headers=auth_headers).json()}
    assert rows["teams_chat"]["account"] == "me@agencyy.com"
    assert rows["outlook_mail"]["account"] == "me@agencyy.com"


def test_state_err_when_every_account_failing(client, auth_headers, tmp_vault):
    _accounts(tmp_vault, [{"connector": "slack", "id": "a"}, {"connector": "slack", "id": "b"}])
    accounts_health.record("slack", "a", accounts_health.STATUS_AUTH, "revoked")
    accounts_health.record("slack", "b", accounts_health.STATUS_ERROR, "boom")
    row = next(c for c in client.get("/v1/connectors", headers=auth_headers).json() if c["id"] == "slack")
    assert row["state"] == "err" and row["error"] == "all accounts need attention"
    accounts_health.record("slack", "b", accounts_health.STATUS_OK)
    row = next(c for c in client.get("/v1/connectors", headers=auth_headers).json() if c["id"] == "slack")
    assert row["state"] != "err"
