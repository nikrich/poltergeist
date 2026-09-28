from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from ghostbrain.connectors.gdrive import backfill
from ghostbrain.connectors.gdrive.auth import GdriveAuthError
from ghostbrain.connectors.gdrive.drive import DriveApiDisabled

ACCOUNT = "a@x.com"


def _local_today() -> date:
    return datetime.now(UTC).astimezone().date()


def _since_for_years(years: int) -> date:
    today = _local_today()
    try:
        return today.replace(year=today.year - years)
    except ValueError:  # Feb 29 -> Feb 28
        return today.replace(year=today.year - years, day=28)


def _register_gdrive_account(vault: Path, account_id: str = ACCOUNT) -> None:
    (vault / "90-meta" / "accounts.yaml").write_text(
        yaml.safe_dump({"version": 1, "accounts": [
            {"connector": "gdrive", "id": account_id, "context": "work"},
        ]}),
        encoding="utf-8",
    )


def test_get_backfill_404_unknown_account(client: TestClient, auth_headers, tmp_vault: Path):
    resp = client.get(
        f"/v1/connectors/gdrive/accounts/{ACCOUNT}/backfill", headers=auth_headers,
    )
    assert resp.status_code == 404


def test_get_backfill_404_when_not_started(client: TestClient, auth_headers, tmp_vault: Path):
    _register_gdrive_account(tmp_vault)
    resp = client.get(
        f"/v1/connectors/gdrive/accounts/{ACCOUNT}/backfill", headers=auth_headers,
    )
    assert resp.status_code == 404


def test_get_backfill_returns_state_with_months(
    client: TestClient, auth_headers, tmp_vault: Path, tmp_state_dir: Path,
):
    _register_gdrive_account(tmp_vault)
    backfill.start(ACCOUNT, since=_local_today().replace(year=_local_today().year - 1))
    resp = client.get(
        f"/v1/connectors/gdrive/accounts/{ACCOUNT}/backfill", headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "running"
    assert "monthsTotal" in body
    assert "monthsDone" in body


def test_estimate_validates_years_range(client: TestClient, auth_headers, tmp_vault: Path):
    _register_gdrive_account(tmp_vault)
    for years in (0, 11):
        resp = client.get(
            f"/v1/connectors/gdrive/accounts/{ACCOUNT}/backfill/estimate?years={years}",
            headers=auth_headers,
        )
        assert resp.status_code == 422


def test_estimate_unknown_account_404(client: TestClient, auth_headers, tmp_vault: Path):
    resp = client.get(
        f"/v1/connectors/gdrive/accounts/{ACCOUNT}/backfill/estimate?years=3",
        headers=auth_headers,
    )
    assert resp.status_code == 404


def test_estimate_success(
    client: TestClient, auth_headers, tmp_vault: Path, monkeypatch,
):
    _register_gdrive_account(tmp_vault)
    monkeypatch.setattr(
        backfill, "estimate",
        lambda account, *, since: {"files": 4200, "capped": False},
    )
    resp = client.get(
        f"/v1/connectors/gdrive/accounts/{ACCOUNT}/backfill/estimate?years=3",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["files"] == 4200
    assert body["capped"] is False
    assert body["since"] == _since_for_years(3).isoformat()


def test_estimate_capped(
    client: TestClient, auth_headers, tmp_vault: Path, monkeypatch,
):
    _register_gdrive_account(tmp_vault)
    monkeypatch.setattr(
        backfill, "estimate",
        lambda account, *, since: {"files": 5000, "capped": True},
    )
    resp = client.get(
        f"/v1/connectors/gdrive/accounts/{ACCOUNT}/backfill/estimate?years=5",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["files"] == 5000
    assert body["capped"] is True


def test_estimate_auth_error_returns_409(
    client: TestClient, auth_headers, tmp_vault: Path, monkeypatch,
):
    _register_gdrive_account(tmp_vault)

    def _raise(account, *, since):
        raise GdriveAuthError("needs re-auth")

    monkeypatch.setattr(backfill, "estimate", _raise)
    resp = client.get(
        f"/v1/connectors/gdrive/accounts/{ACCOUNT}/backfill/estimate?years=3",
        headers=auth_headers,
    )
    assert resp.status_code == 409
    assert "needs re-auth" in resp.json()["detail"]


def test_estimate_api_disabled_returns_409(
    client: TestClient, auth_headers, tmp_vault: Path, monkeypatch,
):
    _register_gdrive_account(tmp_vault)

    def _raise(account, *, since):
        raise DriveApiDisabled("Drive")

    monkeypatch.setattr(backfill, "estimate", _raise)
    resp = client.get(
        f"/v1/connectors/gdrive/accounts/{ACCOUNT}/backfill/estimate?years=3",
        headers=auth_headers,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == str(DriveApiDisabled("Drive"))


def test_start_backfill_409_when_scheduler_off(
    client: TestClient, auth_headers, tmp_vault: Path,
):
    _register_gdrive_account(tmp_vault)
    client.app.state.scheduler = None
    resp = client.post(
        f"/v1/connectors/gdrive/accounts/{ACCOUNT}/backfill",
        headers=auth_headers, json={"years": 3},
    )
    assert resp.status_code == 409
    assert "in-app scheduler" in resp.json()["detail"]


def test_start_backfill_404_unknown_account(client: TestClient, auth_headers, tmp_vault: Path):
    client.app.state.scheduler = object()
    resp = client.post(
        f"/v1/connectors/gdrive/accounts/{ACCOUNT}/backfill",
        headers=auth_headers, json={"years": 3},
    )
    assert resp.status_code == 404


def test_start_backfill_201(
    client: TestClient, auth_headers, tmp_vault: Path, tmp_state_dir: Path,
):
    _register_gdrive_account(tmp_vault)
    client.app.state.scheduler = object()
    resp = client.post(
        f"/v1/connectors/gdrive/accounts/{ACCOUNT}/backfill",
        headers=auth_headers, json={"years": 3},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "running"
    assert body["account"] == ACCOUNT


def test_start_backfill_validates_years(
    client: TestClient, auth_headers, tmp_vault: Path,
):
    _register_gdrive_account(tmp_vault)
    client.app.state.scheduler = object()
    resp = client.post(
        f"/v1/connectors/gdrive/accounts/{ACCOUNT}/backfill",
        headers=auth_headers, json={"years": 11},
    )
    assert resp.status_code == 422


def test_pause_resume_backfill(
    client: TestClient, auth_headers, tmp_vault: Path, tmp_state_dir: Path,
):
    _register_gdrive_account(tmp_vault)
    backfill.start(ACCOUNT, since=_local_today().replace(year=_local_today().year - 1))

    resp = client.post(
        f"/v1/connectors/gdrive/accounts/{ACCOUNT}/backfill/pause", headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "paused"

    resp = client.post(
        f"/v1/connectors/gdrive/accounts/{ACCOUNT}/backfill/resume", headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"


def test_pause_404_when_no_backfill(client: TestClient, auth_headers, tmp_vault: Path):
    _register_gdrive_account(tmp_vault)
    resp = client.post(
        f"/v1/connectors/gdrive/accounts/{ACCOUNT}/backfill/pause", headers=auth_headers,
    )
    assert resp.status_code == 404


def test_resume_404_when_no_backfill(client: TestClient, auth_headers, tmp_vault: Path):
    _register_gdrive_account(tmp_vault)
    resp = client.post(
        f"/v1/connectors/gdrive/accounts/{ACCOUNT}/backfill/resume", headers=auth_headers,
    )
    assert resp.status_code == 404


def test_delete_backfill_is_idempotent(
    client: TestClient, auth_headers, tmp_vault: Path, tmp_state_dir: Path,
):
    _register_gdrive_account(tmp_vault)
    backfill.start(ACCOUNT, since=_local_today().replace(year=_local_today().year - 1))

    resp = client.delete(
        f"/v1/connectors/gdrive/accounts/{ACCOUNT}/backfill", headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    # Calling again with nothing left to cancel is still a 200 ok.
    resp = client.delete(
        f"/v1/connectors/gdrive/accounts/{ACCOUNT}/backfill", headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_delete_backfill_404_for_unknown_account(
    client: TestClient, auth_headers, tmp_vault: Path,
):
    _register_gdrive_account(tmp_vault)
    resp = client.delete(
        "/v1/connectors/gdrive/accounts/nobody@example.com/backfill", headers=auth_headers,
    )
    assert resp.status_code == 404


def test_delete_backfill_ok_for_known_account_without_backfill(
    client: TestClient, auth_headers, tmp_vault: Path,
):
    _register_gdrive_account(tmp_vault)
    resp = client.delete(
        f"/v1/connectors/gdrive/accounts/{ACCOUNT}/backfill", headers=auth_headers,
    )
    assert resp.status_code == 200 and resp.json() == {"ok": True}


def _transient_errors():
    import httplib2

    from ghostbrain.connectors.gdrive.drive import DriveRateLimited

    return [DriveRateLimited("slow down"), OSError("net down"), TimeoutError("t"),
            httplib2.ServerNotFoundError("no dns")]


def test_estimate_transient_errors_return_503(
    client: TestClient, auth_headers, tmp_vault: Path, monkeypatch,
):
    _register_gdrive_account(tmp_vault)
    for exc in _transient_errors():
        def _raise(account, *, since, exc=exc):
            raise exc

        monkeypatch.setattr(backfill, "estimate", _raise)
        resp = client.get(
            f"/v1/connectors/gdrive/accounts/{ACCOUNT}/backfill/estimate?years=3",
            headers=auth_headers,
        )
        assert resp.status_code == 503, type(exc).__name__
        assert resp.json()["detail"] == "Google Drive is busy — try the estimate again in a minute"
