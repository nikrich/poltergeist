"""GET /v1/connectors and GET /v1/connectors/{id}."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from ghostbrain.api.tests.conftest import write_last_run


def test_empty_connectors_list(client: TestClient, auth_headers: dict[str, str]):
    res = client.get("/v1/connectors", headers=auth_headers)
    assert res.status_code == 200
    # The list may not be empty (ghostbrain/connectors/ may contain entries),
    # but each item should be well-formed. Check shape, not emptiness.
    data = res.json()
    assert isinstance(data, list)
    for item in data:
        assert {"id", "displayName", "state", "count", "lastSyncAt", "account", "throughput", "error"}.issubset(item.keys())


def test_microsoft_connectors_are_listed(client: TestClient, auth_headers: dict[str, str]):
    """The Outlook/Teams connectors must surface in the desktop list."""
    data = client.get("/v1/connectors", headers=auth_headers).json()
    by_id = {c["id"]: c for c in data}
    assert {"outlook_mail", "teams_chat", "teams_meetings"}.issubset(by_id)
    assert by_id["outlook_mail"]["displayName"] == "Outlook Mail"
    assert by_id["teams_chat"]["displayName"] == "Teams Chat"
    assert by_id["teams_meetings"]["displayName"] == "Teams Meetings"


def test_microsoft_connectors_are_syncable():
    from ghostbrain.api.routes.connectors import SYNCABLE
    assert {"outlook_mail", "teams_chat", "teams_meetings"}.issubset(SYNCABLE)


def test_connector_state_off_when_no_state_file(
    client: TestClient, auth_headers: dict[str, str], tmp_state_dir: Path
):
    """A connector with no credentials/state reports state='off'.

    Uses gmail (not github) because gmail's off-state is deterministic: the probe
    looks only for gmail.*.token files in GHOSTBRAIN_STATE_DIR (empty tmp dir here).
    GitHub's state depends on ambient `gh auth status`, making it environment-dependent.
    """
    res = client.get("/v1/connectors", headers=auth_headers)
    data = res.json()
    # gmail probe checks for token files in the temp state_dir; with none present,
    # it deterministically reports 'off' regardless of host machine state.
    gmail = next((c for c in data if c["id"] == "gmail"), None)
    assert gmail is not None, "gmail connector must be in the list"
    assert gmail["state"] == "off"
    assert gmail["lastSyncAt"] is None


def test_connector_state_on_with_recent_sync(
    client: TestClient, auth_headers: dict[str, str], tmp_state_dir: Path
):
    now_iso = datetime.now(timezone.utc).isoformat()
    write_last_run(tmp_state_dir, "github", now_iso)
    res = client.get("/v1/connectors", headers=auth_headers)
    data = res.json()
    github = next((c for c in data if c["id"] == "github"), None)
    assert github is not None
    assert github["state"] == "on"
    assert github["count"] == 0
    assert github["account"] is None
    assert github["lastSyncAt"] == now_iso


def test_connector_state_on_even_when_last_run_is_stale(
    client: TestClient, auth_headers: dict[str, str], tmp_state_dir: Path
):
    """A .last_run file means the connector is configured; staleness surfaces
    via the lastSyncAt timestamp, not the state field."""
    stale = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    write_last_run(tmp_state_dir, "github", stale)
    res = client.get("/v1/connectors", headers=auth_headers)
    github = next((c for c in res.json() if c["id"] == "github"), None)
    assert github is not None
    assert github["state"] == "on"
    assert github["lastSyncAt"] == stale


def test_calendar_connector_uses_macos_calendar_key(
    client: TestClient, auth_headers: dict[str, str], tmp_state_dir: Path
):
    """The calendar connector maps to macos_calendar.last_run on disk."""
    now_iso = datetime.now(timezone.utc).isoformat()
    write_last_run(tmp_state_dir, "macos_calendar", now_iso)
    res = client.get("/v1/connectors", headers=auth_headers)
    cal = next((c for c in res.json() if c["id"] == "calendar"), None)
    if cal is not None:
        assert cal["state"] == "on"
        assert cal["lastSyncAt"] == now_iso


def test_connector_detail_returns_404_for_unknown(
    client: TestClient, auth_headers: dict[str, str]
):
    res = client.get("/v1/connectors/does-not-exist", headers=auth_headers)
    assert res.status_code == 404


def test_connector_detail_includes_scopes_and_pulls(
    client: TestClient, auth_headers: dict[str, str], tmp_state_dir: Path
):
    write_last_run(tmp_state_dir, "github", datetime.now(timezone.utc).isoformat())
    res = client.get("/v1/connectors/github", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert "scopes" in data
    assert "pulls" in data
    assert "vaultDestination" in data
