"""PUT /v1/notes — path-addressed upsert (Familiar plugin write-back)."""


def test_upsert_creates_nested_note(client, tmp_vault, auth_headers):
    r = client.put(
        "/v1/notes",
        json={"path": "Familiar/briefings/2026-07-08.md", "content": "---\ntype: familiar-briefing\n---\n\n# Briefing\n"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json() == {"path": "Familiar/briefings/2026-07-08.md", "created": True}
    on_disk = (tmp_vault / "Familiar" / "briefings" / "2026-07-08.md").read_text()
    assert on_disk.startswith("---\ntype: familiar-briefing")


def test_upsert_replaces_existing(client, tmp_vault, auth_headers):
    p = tmp_vault / "Familiar"
    p.mkdir()
    (p / "memory.md").write_text("old\n")
    r = client.put("/v1/notes", json={"path": "Familiar/memory.md", "content": "new body\n"}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["created"] is False
    assert (p / "memory.md").read_text() == "new body\n"


def test_upsert_rejects_traversal_and_non_md(client, tmp_vault, auth_headers):
    assert client.put("/v1/notes", json={"path": "../evil.md", "content": "x"}, headers=auth_headers).status_code == 400
    assert client.put("/v1/notes", json={"path": "Familiar/run.sh", "content": "x"}, headers=auth_headers).status_code == 400


def test_upsert_rejects_empty_content(client, tmp_vault, auth_headers):
    r = client.put("/v1/notes", json={"path": "Familiar/memory.md", "content": "  "}, headers=auth_headers)
    assert r.status_code == 422
