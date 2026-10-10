"""B2: /v1/changes — list, detail, revert, undo (spec B §5)."""
from __future__ import annotations

from ghostbrain.changes import log as changes
from ghostbrain.history import store
from ghostbrain.vault_write import compute_etag

FAM = {"X-Poltergeist-Actor": "plugin:familiar"}
REL = "Familiar/memory.md"


def _seed(client, auth) -> tuple[int, int]:
    h = {**auth, **FAM}
    assert client.put("/v1/notes", json={"path": REL, "content": "v1"}, headers=h).status_code == 200
    assert client.put("/v1/notes", json={"path": REL, "content": "v2"}, headers=h).status_code == 200
    created, modified = sorted(c.id for c in changes.list_changes())
    return created, modified


def test_list_is_empty_at_first(client, auth_headers):
    r = client.get("/v1/changes", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == {"items": [], "pendingCount": 0, "degraded": False}


def test_list_is_newest_first_and_filters(tmp_vault, client, auth_headers):
    created, modified = _seed(client, auth_headers)
    items = client.get("/v1/changes", headers=auth_headers).json()["items"]
    assert [i["id"] for i in items] == [modified, created]
    assert items[0] == {
        "id": modified, "ts": items[0]["ts"], "actor": "plugin:familiar", "path": REL,
        "destPath": None, "op": "modify", "reason": "plugin write-back", "status": "applied",
        "riskReasons": [], "resolvedTs": None,
    }
    get = lambda **p: client.get("/v1/changes", params=p, headers=auth_headers)
    assert get(actor="assistant").json()["items"] == []
    assert len(get(actor="plugin", q="memory").json()["items"]) == 2
    assert get(status="nope").status_code == 422
    assert get(since="yesterday").status_code == 422
    assert len(get(since="2000-01-01T00:00:00Z").json()["items"]) == 2


def test_detail_has_before_after_current_and_a_unified_diff(tmp_vault, client, auth_headers):
    _, modified = _seed(client, auth_headers)
    d = client.get(f"/v1/changes/{modified}", headers=auth_headers).json()
    assert (d["before"], d["after"], d["current"], d["changedSince"]) == ("v1\n", "v2\n", "v2\n", False)
    assert "-v1" in d["diff"] and "+v2" in d["diff"]
    (tmp_vault / REL).write_text("user edit\n")
    assert client.get(f"/v1/changes/{modified}", headers=auth_headers).json()["changedSince"] is True
    assert client.get("/v1/changes/9999", headers=auth_headers).status_code == 404


def test_revert_then_undo(tmp_vault, client, auth_headers):
    _, modified = _seed(client, auth_headers)
    r = client.post(f"/v1/changes/{modified}/revert", json={"force": False}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == {"id": modified, "status": "reverted", "path": REL,
                        "etag": compute_etag(b"v1\n")}
    assert (tmp_vault / REL).read_text() == "v1\n"
    assert client.post(f"/v1/changes/{modified}/revert", json={},
                       headers=auth_headers).status_code == 400
    u = client.post(f"/v1/changes/{modified}/undo", json={}, headers=auth_headers)
    assert u.status_code == 200 and u.json()["status"] == "applied"
    assert (tmp_vault / REL).read_text() == "v2\n"


def test_revert_without_a_body_defaults_to_no_force(tmp_vault, client, auth_headers):
    _, modified = _seed(client, auth_headers)
    assert client.post(f"/v1/changes/{modified}/revert", headers=auth_headers).status_code == 200


def test_revert_after_an_outside_edit_is_409_until_forced(tmp_vault, client, auth_headers):
    _, modified = _seed(client, auth_headers)
    (tmp_vault / REL).write_text("user edit\n")
    r = client.post(f"/v1/changes/{modified}/revert", json={}, headers=auth_headers)
    assert r.status_code == 409 and "changed since" in r.json()["detail"]
    assert (tmp_vault / REL).read_text() == "user edit\n"
    f = client.post(f"/v1/changes/{modified}/revert", json={"force": True}, headers=auth_headers)
    assert f.status_code == 200
    assert (tmp_vault / REL).read_text() == "v1\n"
    assert store.get_blob(store.list_snapshots(REL)[0].blob) == b"user edit\n"


def test_only_the_user_can_revert_or_undo(tmp_vault, client, auth_headers):
    _, modified = _seed(client, auth_headers)
    for action in ("revert", "undo"):
        r = client.post(f"/v1/changes/{modified}/{action}", json={},
                        headers={**auth_headers, **FAM})
        assert r.status_code == 403


def test_a_collected_version_is_410(tmp_vault, client, auth_headers):
    _, modified = _seed(client, auth_headers)
    store._blob_path(changes.get(modified).before_blob).unlink()
    r = client.post(f"/v1/changes/{modified}/revert", json={}, headers=auth_headers)
    assert r.status_code == 410


def test_dismiss_degraded_is_user_only(client, auth_headers):
    changes.mark_degraded("insert failed")
    r = client.delete("/v1/changes/degraded", headers={**auth_headers, **FAM})
    assert r.status_code == 403
    assert client.get("/v1/changes", headers=auth_headers).json()["degraded"] is True


def test_degraded_flag_and_dismiss(client, auth_headers):
    changes.mark_degraded("insert failed")
    assert client.get("/v1/changes", headers=auth_headers).json()["degraded"] is True
    assert client.delete("/v1/changes/degraded", headers=auth_headers).status_code == 204
    assert client.get("/v1/changes", headers=auth_headers).json()["degraded"] is False


def test_an_unavailable_change_log_is_503(client, auth_headers, monkeypatch):
    def boom(**_k):
        raise changes.ChangeLogError("database is locked")

    monkeypatch.setattr(changes, "list_changes", boom)
    assert client.get("/v1/changes", headers=auth_headers).status_code == 503
