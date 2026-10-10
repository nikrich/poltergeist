"""/v1/design/packs* and /v1/design/settings routes."""
from __future__ import annotations

import json
import time
from pathlib import Path

from ghostbrain.design import packs


def _make_pack(vault: Path, pack_id: str, name: str = "Acme") -> None:
    d = vault / "90-meta" / "design-systems" / pack_id
    d.mkdir(parents=True)
    (d / "pack.json").write_text(json.dumps({
        "id": pack_id, "name": name, "source": "src", "imported_at": "2026-10-10T00:00:00+00:00",
    }))
    (d / "tokens.css").write_text(":root{--a:1}")
    (d / "README.md").write_text("# x")


def test_list_packs(client, auth_headers, tmp_vault):
    _make_pack(tmp_vault, "acme")
    r = client.get("/v1/design/packs", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body[0]["id"] == packs.BUILTIN_PACK_ID and body[0]["builtin"] is True
    assert body[1] == {
        "id": "acme", "name": "Acme", "source": "src",
        "imported_at": "2026-10-10T00:00:00+00:00", "builtin": False,
    }


def test_delete_pack(client, auth_headers, tmp_vault):
    _make_pack(tmp_vault, "acme")
    assert client.delete("/v1/design/packs/acme", headers=auth_headers).status_code == 204
    assert client.delete("/v1/design/packs/acme", headers=auth_headers).status_code == 404
    r = client.delete(f"/v1/design/packs/{packs.BUILTIN_PACK_ID}", headers=auth_headers)
    assert r.status_code == 400


def test_import_and_poll(client, auth_headers, tmp_vault, monkeypatch):
    def fake_start(source, name=None):
        return {"id": "job1", "source": source, "status": "running", "message": None, "pack_id": None}

    monkeypatch.setattr(packs, "start_import", fake_start)
    monkeypatch.setattr(packs, "get_import", lambda jid: (
        {"id": "job1", "source": "s", "status": "done", "message": None, "pack_id": "acme"}
        if jid == "job1" else None
    ))
    r = client.post("/v1/design/packs/import", json={"source": "s", "name": "Acme"}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == {"id": "job1", "source": "s", "status": "running", "message": None, "pack_id": None}
    r = client.get("/v1/design/packs/import/job1", headers=auth_headers)
    assert r.json()["status"] == "done" and r.json()["pack_id"] == "acme"
    assert client.get("/v1/design/packs/import/nope", headers=auth_headers).status_code == 404


def test_import_end_to_end_with_fake_agent(client, auth_headers, tmp_vault, monkeypatch):
    import subprocess

    monkeypatch.setattr(packs, "_find_claude_binary", lambda: "/usr/bin/claude")

    def run(cmd, cwd, timeout):
        (Path(cwd) / "tokens.css").write_text(":root{--ds-color-primary:#000}")
        (Path(cwd) / "README.md").write_text("# Brand")
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"result": "ok"}), "")

    monkeypatch.setattr(packs, "_run_agent", run)
    job = client.post("/v1/design/packs/import", json={"source": "/some/folder"}, headers=auth_headers).json()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        state = client.get(f"/v1/design/packs/import/{job['id']}", headers=auth_headers).json()
        if state["status"] != "running":
            break
        time.sleep(0.02)
    assert state["status"] == "done" and state["pack_id"] == "brand"
    ids = [p["id"] for p in client.get("/v1/design/packs", headers=auth_headers).json()]
    assert "brand" in ids


def test_import_validation(client, auth_headers):
    assert client.post("/v1/design/packs/import", json={"source": ""}, headers=auth_headers).status_code == 422
    assert client.post("/v1/design/packs/import", json={}, headers=auth_headers).status_code == 422


def test_settings_get_put(client, auth_headers, tmp_vault):
    r = client.get("/v1/design/settings", headers=auth_headers)
    assert r.json() == {"listen": True, "budget_usd": 2.0, "default_pack": packs.BUILTIN_PACK_ID,
                        "code_roots": ["~/development"], "web": True}
    _make_pack(tmp_vault, "acme")
    r = client.put(
        "/v1/design/settings", json={"listen": False, "default_pack": "acme"}, headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json() == {"listen": False, "budget_usd": 2.0, "default_pack": "acme", "code_roots": ["~/development"], "web": True}
    assert client.get("/v1/design/settings", headers=auth_headers).json()["listen"] is False
    bad = client.put("/v1/design/settings", json={"budget_usd": 100}, headers=auth_headers)
    assert bad.status_code == 422
    bad = client.put("/v1/design/settings", json={"default_pack": "nope"}, headers=auth_headers)
    assert bad.status_code == 422


def test_project_design_system_round_trip(client, auth_headers, tmp_vault):
    H = auth_headers
    created = client.post("/v1/projects", json={"context": "work", "name": "Shop"}, headers=H).json()
    assert created["design_system"] is None
    _make_pack(tmp_vault, "acme")
    r = client.patch("/v1/projects/work/shop", json={"design_system": "acme"}, headers=H)
    assert r.status_code == 200 and r.json()["design_system"] == "acme"
    assert client.get("/v1/projects", headers=H).json()[0]["design_system"] == "acme"
    # unrelated edits keep it
    r = client.patch("/v1/projects/work/shop", json={"description": "d"}, headers=H)
    assert r.json()["design_system"] == "acme"
    # unknown pack → 422, unchanged
    r = client.patch("/v1/projects/work/shop", json={"design_system": "nope"}, headers=H)
    assert r.status_code == 422
    assert client.get("/v1/projects", headers=H).json()[0]["design_system"] == "acme"
    # builtin is valid; explicit null clears
    r = client.patch("/v1/projects/work/shop", json={"design_system": packs.BUILTIN_PACK_ID}, headers=H)
    assert r.json()["design_system"] == packs.BUILTIN_PACK_ID
    r = client.patch("/v1/projects/work/shop", json={"design_system": None}, headers=H)
    assert r.status_code == 200 and r.json()["design_system"] is None


def test_project_design_system_survives_rename(client, auth_headers, tmp_vault, tmp_chats_dir):
    H = auth_headers
    client.post("/v1/projects", json={"context": "work", "name": "Shop"}, headers=H)
    r = client.patch(
        "/v1/projects/work/shop",
        json={"name": "Store", "design_system": packs.BUILTIN_PACK_ID},
        headers=H,
    )
    assert r.status_code == 200
    assert r.json()["slug"] == "store" and r.json()["design_system"] == packs.BUILTIN_PACK_ID
