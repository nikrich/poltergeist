"""GET /v1/activity/heatmap and the new ?date= param on GET /v1/activity."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient


def _write_audit_event(vault: Path, date_iso: str, event: dict) -> None:
    audit = vault / "90-meta" / "audit"
    path = audit / f"{date_iso}.jsonl"
    with path.open("a") as f:
        f.write(json.dumps(event) + "\n")


def test_heatmap_empty(client: TestClient, auth_headers: dict[str, str]):
    res = client.get("/v1/activity/heatmap", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == {"days": [], "total": 0, "maxCount": 0}


def test_heatmap_aggregates_with_by_source(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    today = datetime.now(timezone.utc).date().isoformat()
    _write_audit_event(tmp_vault, today, {
        "ts": f"{today}T10:00:00+00:00",
        "event_type": "event_processed",
        "event_id": "evt1",
        "source": "gmail",
    })
    _write_audit_event(tmp_vault, today, {
        "ts": f"{today}T11:00:00+00:00",
        "event_type": "connector_skipped",
        "event_id": "joplin",
    })
    res = client.get("/v1/activity/heatmap?days=30", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 2
    assert data["maxCount"] == 2
    assert data["days"] == [
        {"date": today, "count": 2, "bySource": {"gmail": 1, "system": 1}}
    ]


def test_heatmap_days_bounds(client: TestClient, auth_headers: dict[str, str]):
    assert client.get("/v1/activity/heatmap?days=0", headers=auth_headers).status_code == 422
    assert client.get("/v1/activity/heatmap?days=731", headers=auth_headers).status_code == 422
    assert client.get("/v1/activity/heatmap?days=1", headers=auth_headers).status_code == 200
    assert client.get("/v1/activity/heatmap?days=730", headers=auth_headers).status_code == 200


def test_activity_date_param_returns_whole_day(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    day = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
    _write_audit_event(tmp_vault, day, {
        "ts": f"{day}T09:00:00+00:00",
        "event_type": "event_processed",
        "event_id": "evt1",
        "source": "gmail",
    })
    res = client.get(f"/v1/activity?date={day}", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["id"] == f"audit-{day}-0"
    assert data[0]["source"] == "gmail"
    assert data[0]["verb"] == "processed"


def test_activity_date_wins_over_window_minutes(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    day = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
    _write_audit_event(tmp_vault, day, {
        "ts": f"{day}T09:00:00+00:00",
        "event_type": "event_processed",
        "event_id": "evt1",
        "source": "gmail",
    })
    # windowMinutes=1 alone would exclude a 30-day-old event; date wins.
    res = client.get(f"/v1/activity?date={day}&windowMinutes=1", headers=auth_headers)
    assert res.status_code == 200
    assert len(res.json()) == 1


def test_activity_invalid_date_422(client: TestClient, auth_headers: dict[str, str]):
    assert client.get("/v1/activity?date=not-a-date", headers=auth_headers).status_code == 422
    assert client.get("/v1/activity?date=2026-13-45", headers=auth_headers).status_code == 422
