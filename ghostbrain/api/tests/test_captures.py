"""GET /v1/captures and GET /v1/captures/{id}."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient


def _write_pending(vault: Path, capture_id: str, payload: dict) -> Path:
    pending = vault / "90-meta" / "queue" / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    p = pending / f"{capture_id}.json"
    p.write_text(json.dumps(payload))
    return p


def _write_audit(vault: Path, date_iso: str, lines: list[dict]) -> Path:
    audit = vault / "90-meta" / "audit"
    audit.mkdir(parents=True, exist_ok=True)
    p = audit / f"{date_iso}.jsonl"
    p.write_text("\n".join(json.dumps(l) for l in lines))
    return p


def test_empty_returns_zero_total(client: TestClient, auth_headers: dict[str, str]):
    res = client.get("/v1/captures", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 0
    assert data["items"] == []


def test_pending_items_appear(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _write_pending(tmp_vault, "p1", {
        "source": "gmail", "title": "re: design crit",
        "snippet": "works for me", "from": "theo · 8:14am",
        "tags": ["followup"], "capturedAt": now,
    })
    res = client.get("/v1/captures", headers=auth_headers)
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["title"] == "re: design crit"
    assert data["items"][0]["from"] == "theo · 8:14am"
    assert data["items"][0]["unread"] is True  # recent → unread


def test_audit_items_appear(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    _write_audit(tmp_vault, today, [{
        "id": "a1", "source": "slack", "title": "#product-feedback",
        "snippet": "users ask for shortcuts", "from": "mira · 8:01am",
        "tags": ["feedback"], "capturedAt": yesterday,
    }])
    res = client.get("/v1/captures", headers=auth_headers)
    data = res.json()
    titles = [i["title"] for i in data["items"]]
    assert "#product-feedback" in titles


def test_limit_caps_results(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    for i in range(10):
        _write_pending(tmp_vault, f"p{i}", {
            "source": "gmail", "title": f"item {i}",
            "snippet": "x", "from": "x · x",
            "tags": [], "capturedAt": now,
        })
    res = client.get("/v1/captures?limit=3", headers=auth_headers)
    data = res.json()
    assert data["total"] == 10
    assert len(data["items"]) == 3


def test_source_filter(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _write_pending(tmp_vault, "g1", {
        "source": "gmail", "title": "x", "snippet": "x",
        "from": "x", "tags": [], "capturedAt": now,
    })
    _write_pending(tmp_vault, "s1", {
        "source": "slack", "title": "y", "snippet": "y",
        "from": "y", "tags": [], "capturedAt": now,
    })
    res = client.get("/v1/captures?source=slack", headers=auth_headers)
    data = res.json()
    assert all(i["source"] == "slack" for i in data["items"])


def test_capture_detail_includes_body(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _write_pending(tmp_vault, "p1", {
        "source": "gmail", "title": "subject",
        "snippet": "snippet here", "from": "x",
        "tags": [], "capturedAt": now,
        "body": "full body text of the email",
    })
    res = client.get("/v1/captures/p1", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["body"] == "full body text of the email"


def test_capture_detail_404(client: TestClient, auth_headers: dict[str, str]):
    res = client.get("/v1/captures/does-not-exist", headers=auth_headers)
    assert res.status_code == 404
