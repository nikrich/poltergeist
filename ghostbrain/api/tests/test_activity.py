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
    one_min_ago = (now - timedelta(minutes=1)).isoformat()
    _write_audit_event(tmp_vault, today, {
        "ts": one_min_ago,
        "event_type": "event_processed",
        "event_id": "evt1",
        "source": "gmail",
        "status": "success",
        "context": "personal",
        "inbox_path": "/v/00-inbox/raw/gmail/20260507T144500-3-newsletters.md",
    })
    res = client.get("/v1/activity?windowMinutes=240", headers=auth_headers)
    data = res.json()
    assert len(data) == 1
    assert data[0]["source"] == "gmail"
    assert data[0]["verb"] == "processed"
    # Subject should strip the timestamp prefix from the inbox basename.
    assert data[0]["subject"] == "3-newsletters"


def test_digest_event_uses_digest_source(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    one_min_ago = (now - timedelta(minutes=1)).isoformat()
    _write_audit_event(tmp_vault, today, {
        "ts": one_min_ago,
        "event_type": "digest_generated",
        "event_id": "2026-05-08",
        "path": "/v/10-daily/2026-05-08.md",
        "notes_count": 0,
    })
    res = client.get("/v1/activity?windowMinutes=240", headers=auth_headers)
    data = res.json()
    assert len(data) == 1
    assert data[0]["source"] == "digest"
    assert data[0]["verb"] == "wrote digest"


def test_excludes_old_events(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    five_hours_ago = (now - timedelta(hours=5)).isoformat()
    _write_audit_event(tmp_vault, today, {
        "ts": five_hours_ago,
        "event_type": "event_processed",
        "event_id": "evt-old",
        "source": "gmail",
    })
    # windowMinutes=240 = 4 hours
    res = client.get("/v1/activity?windowMinutes=240", headers=auth_headers)
    assert res.json() == []
