"""B3: approve / reject held changes over HTTP (spec B §5)."""
from __future__ import annotations

from ghostbrain.changes import log as changes
from ghostbrain.history import store
from ghostbrain.vault_write import compute_etag

FAM = {"X-Poltergeist-Actor": "plugin:familiar"}
TEMPLATE = "90-meta/templates/standup.md"
BODY = "# Standup\n\n- yesterday\n"


def _propose(client, auth) -> int:
    r = client.put("/v1/notes", json={"path": TEMPLATE, "content": BODY}, headers={**auth, **FAM})
    assert r.status_code == 200 and r.json()["status"] == "pending"
    return int(r.json()["changeId"])


def test_a_plugin_template_waits_in_the_pending_list(tmp_vault, client, auth_headers):
    cid = _propose(client, auth_headers)
    assert not (tmp_vault / TEMPLATE).exists()
    listing = client.get("/v1/changes", params={"status": "pending"}, headers=auth_headers).json()
    assert listing["pendingCount"] == 1
    [item] = listing["items"]
    assert (item["id"], item["status"], item["riskReasons"]) == (cid, "pending", ["edits a template"])
    d = client.get(f"/v1/changes/{cid}", headers=auth_headers).json()
    assert (d["before"], d["after"], d["changedSince"]) == (None, BODY, False)


def test_approve_writes_it(tmp_vault, client, auth_headers):
    cid = _propose(client, auth_headers)
    r = client.post(f"/v1/changes/{cid}/approve", json={}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == {"id": cid, "status": "applied", "path": TEMPLATE,
                        "etag": compute_etag(BODY.encode())}
    assert (tmp_vault / TEMPLATE).read_text() == BODY
    assert client.get("/v1/changes", headers=auth_headers).json()["pendingCount"] == 0


def test_approve_without_a_body_defaults_to_no_force(tmp_vault, client, auth_headers):
    cid = _propose(client, auth_headers)
    assert client.post(f"/v1/changes/{cid}/approve", headers=auth_headers).status_code == 200


def test_reject_writes_nothing(tmp_vault, client, auth_headers):
    cid = _propose(client, auth_headers)
    r = client.post(f"/v1/changes/{cid}/reject", headers=auth_headers)
    assert r.status_code == 200 and r.json() == {"id": cid, "status": "rejected"}
    assert not (tmp_vault / TEMPLATE).exists()
    assert client.post(f"/v1/changes/{cid}/reject", headers=auth_headers).status_code == 400
    assert client.post(f"/v1/changes/{cid}/approve", json={}, headers=auth_headers).status_code == 400


def test_only_the_user_decides(tmp_vault, client, auth_headers):
    cid = _propose(client, auth_headers)
    h = {**auth_headers, **FAM}
    assert client.post(f"/v1/changes/{cid}/approve", json={}, headers=h).status_code == 403
    assert client.post(f"/v1/changes/{cid}/reject", headers=h).status_code == 403
    assert changes.get(cid).status == "pending"
    assert client.post("/v1/changes/9999/approve", json={}, headers=h).status_code == 403


def test_stale_approval_is_409_until_forced(tmp_vault, client, auth_headers):
    cid = _propose(client, auth_headers)
    (tmp_vault / TEMPLATE).parent.mkdir(parents=True, exist_ok=True)
    (tmp_vault / TEMPLATE).write_text("the user wrote this first\n")
    assert client.get(f"/v1/changes/{cid}", headers=auth_headers).json()["changedSince"] is True
    r = client.post(f"/v1/changes/{cid}/approve", json={}, headers=auth_headers)
    assert r.status_code == 409 and "changed since" in r.json()["detail"]
    assert (tmp_vault / TEMPLATE).read_text() == "the user wrote this first\n"
    assert changes.get(cid).status == "pending"
    f = client.post(f"/v1/changes/{cid}/approve", json={"force": True}, headers=auth_headers)
    assert f.status_code == 200
    assert (tmp_vault / TEMPLATE).read_text() == BODY
    assert store.get_blob(store.list_snapshots(TEMPLATE)[0].blob) == b"the user wrote this first\n"


def test_unknown_and_collected(tmp_vault, client, auth_headers):
    assert client.post("/v1/changes/9999/approve", json={}, headers=auth_headers).status_code == 404
    assert client.post("/v1/changes/9999/reject", headers=auth_headers).status_code == 404
    cid = _propose(client, auth_headers)
    store._blob_path(changes.get(cid).pending_bytes_blob).unlink()
    assert client.post(f"/v1/changes/{cid}/approve", json={}, headers=auth_headers).status_code == 410
