"""B3: write routes say when a change is waiting for approval."""
from __future__ import annotations

from ghostbrain.api.repo.notes_manual import write_inbox_jot
from ghostbrain.api.tests.conftest import write_note
from ghostbrain.changes import log as changes
from ghostbrain.vault_write import compute_etag

ASSIST = {"X-Poltergeist-Actor": "assistant"}
FAM = {"X-Poltergeist-Actor": "plugin:familiar"}
PREFS = "80-profile/preferences.md"


def _if_match(data: bytes) -> dict:
    etag = compute_etag(data)
    return {"If-Match": f'"{etag}"'}


def test_an_assistant_edit_to_the_stable_profile_is_pending(tmp_vault, client, auth_headers):
    note = write_note(tmp_vault, PREFS, "# Preferences\n\n- spaces\n")
    before = note.read_bytes()
    r = client.patch("/v1/notes/body", json={"path": PREFS, "body": "- tabs"},
                     headers={**auth_headers, **ASSIST, **_if_match(before)})
    assert r.status_code == 200
    out = r.json()
    assert out["status"] == "pending" and out["changeId"]
    assert out["etag"] == compute_etag(before)
    assert note.read_bytes() == before


def test_a_plain_assistant_edit_reports_applied(tmp_vault, client, auth_headers):
    note = write_note(tmp_vault, "20-contexts/work/notes/plan.md", "---\ntitle: Plan\n---\n\nfirst\n")
    r = client.patch("/v1/notes/body", json={"path": "20-contexts/work/notes/plan.md", "body": "second"},
                     headers={**auth_headers, **ASSIST, **_if_match(note.read_bytes())})
    assert r.status_code == 200
    assert r.json()["status"] == "applied" and r.json()["changeId"]


def test_a_user_edit_reports_applied_with_no_change(tmp_vault, client, auth_headers):
    write_note(tmp_vault, PREFS, "# Preferences\n")
    r = client.patch("/v1/notes/body", json={"path": PREFS, "body": "- tabs"}, headers=auth_headers)
    assert (r.json()["status"], r.json()["changeId"]) == ("applied", None)


def test_an_assistant_jot_edit_adding_a_script_is_pending(tmp_vault, client, auth_headers):
    rec = write_inbox_jot("my jot")
    path = tmp_vault / rec["path"]
    before = path.read_bytes()
    r = client.patch(f"/v1/notes/{rec['id']}", json={"body": "my jot\n\n<script>steal()</script>"},
                     headers={**auth_headers, **ASSIST, **_if_match(before)})
    assert r.status_code == 200 and r.json()["status"] == "pending"
    assert path.read_bytes() == before


def test_a_plugin_filing_a_users_jot_is_pending(tmp_vault, client, auth_headers):
    rec = write_inbox_jot("my jot")
    path = tmp_vault / rec["path"]
    r = client.post(f"/v1/notes/{rec['id']}/route", json={"context": "work"},
                    headers={**auth_headers, **FAM, **_if_match(path.read_bytes())})
    assert r.status_code == 200 and r.json()["status"] == "pending"
    assert path.exists()


def test_a_plugin_deleting_a_users_jot_gets_202_and_the_file_stays(tmp_vault, client, auth_headers):
    rec = write_inbox_jot("my jot")
    path = tmp_vault / rec["path"]
    r = client.delete(f"/v1/notes/{rec['id']}",
                      headers={**auth_headers, **FAM, **_if_match(path.read_bytes())})
    assert r.status_code == 202
    [row] = changes.list_changes(status="pending")
    assert r.json() == {"status": "pending", "changeId": str(row.id)}
    assert (row.op, row.risk_reasons) == ("delete", ("deletes a note it didn't create",))
    assert path.exists()


def test_a_generated_doc_with_a_script_waits(tmp_vault, client, auth_headers):
    r = client.post("/v1/docs/write", json={"title": "Report", "html": "<p>hi</p><script>x()</script>"},
                    headers=auth_headers)
    assert r.status_code == 200
    out = r.json()
    assert out["status"] == "pending" and out["changeId"]
    assert not (tmp_vault / out["path"]).exists()
    plain = client.post("/v1/docs/write", json={"title": "Report", "html": "<p>hi</p>"},
                        headers=auth_headers).json()
    assert plain["status"] == "applied"
    assert (tmp_vault / plain["path"]).exists()


def test_a_plugin_upsert_into_90_meta_is_pending(tmp_vault, client, auth_headers):
    r = client.put("/v1/notes", json={"path": "90-meta/templates/standup.md", "content": "# Standup\n"},
                   headers={**auth_headers, **FAM})
    assert r.status_code == 200
    out = r.json()
    assert (out["status"], out["created"], out["etag"]) == ("pending", True, None)
    assert not (tmp_vault / "90-meta/templates/standup.md").exists()
