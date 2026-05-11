"""GET /v1/vault/stats returns aggregate vault numbers."""
from pathlib import Path

from fastapi.testclient import TestClient

from ghostbrain.api.tests.conftest import write_last_run, write_note


def test_empty_vault_returns_zeros(client: TestClient, auth_headers: dict[str, str]):
    res = client.get("/v1/vault/stats", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["totalNotes"] == 0
    assert data["queuePending"] == 0
    assert data["vaultSizeBytes"] == 0
    assert data["lastSyncAt"] is None
    assert data["indexedCount"] == 0


def test_counts_markdown_notes_recursively(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    write_note(tmp_vault, "10-daily/2026-05-11.md")
    write_note(tmp_vault, "20-contexts/personal/gmail/foo.md")
    write_note(tmp_vault, "20-contexts/work/slack/bar.md")
    res = client.get("/v1/vault/stats", headers=auth_headers)
    assert res.json()["totalNotes"] == 3


def test_counts_pending_queue_entries(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    pending = tmp_vault / "90-meta" / "queue" / "pending"
    (pending / "1.json").write_text("{}")
    (pending / "2.json").write_text("{}")
    res = client.get("/v1/vault/stats", headers=auth_headers)
    assert res.json()["queuePending"] == 2


def test_last_sync_is_max_of_last_run_files(
    client: TestClient, auth_headers: dict[str, str], tmp_state_dir: Path
):
    """lastSyncAt = max timestamp across <connector>.last_run flat text files."""
    write_last_run(tmp_state_dir, "github", "2026-05-11T12:00:00Z")
    write_last_run(tmp_state_dir, "slack", "2026-05-11T13:30:00Z")
    res = client.get("/v1/vault/stats", headers=auth_headers)
    data = res.json()
    assert data["lastSyncAt"] == "2026-05-11T13:30:00Z"  # max


def test_indexed_count_is_inbox_file_count(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    """indexedCount counts markdown files under <vault>/00-inbox/raw/<source>/."""
    write_note(tmp_vault, "00-inbox/raw/gmail/a.md", "---\nid: a\n---\nbody")
    write_note(tmp_vault, "00-inbox/raw/gmail/b.md", "---\nid: b\n---\nbody")
    write_note(tmp_vault, "00-inbox/raw/slack/c.md", "---\nid: c\n---\nbody")
    res = client.get("/v1/vault/stats", headers=auth_headers)
    assert res.json()["indexedCount"] == 3
