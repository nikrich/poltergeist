"""GET /v1/activity."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient


def _write_audit_event(vault: Path, date_iso: str, event: dict) -> None:
    audit = vault / "90-meta" / "audit"
    audit.mkdir(parents=True, exist_ok=True)
    path = audit / f"{date_iso}.jsonl"
    with path.open("a") as f:
        f.write(json.dumps(event) + "\n")


def test_empty_returns_no_activity(client: TestClient, auth_headers: dict[str, str]):
    res = client.get("/v1/activity?windowMinutes=240", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == []


def test_includes_recent_events(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    one_min_ago = (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    _write_audit_event(tmp_vault, today, {
        "id": "evt1", "source": "gmail", "verb": "archived",
        "subject": "3 newsletters", "at": one_min_ago,
    })
    res = client.get("/v1/activity?windowMinutes=240", headers=auth_headers)
    data = res.json()
    assert len(data) == 1
    assert data[0]["source"] == "gmail"
    assert data[0]["verb"] == "archived"


def test_excludes_old_events(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    five_hours_ago = (now - timedelta(hours=5)).isoformat().replace("+00:00", "Z")
    _write_audit_event(tmp_vault, today, {
        "id": "evt-old", "source": "gmail", "verb": "x",
        "subject": "old", "at": five_hours_ago,
    })
    # windowMinutes=240 = 4 hours
    res = client.get("/v1/activity?windowMinutes=240", headers=auth_headers)
    assert res.json() == []
