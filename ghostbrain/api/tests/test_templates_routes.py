"""/v1/templates: list, functions, create (write path, user), render (no write)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

NOW = datetime(2026, 10, 9, 14, 30, tzinfo=timezone(timedelta(hours=2)))


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch):
    monkeypatch.setattr("ghostbrain.templates.env._now", lambda: NOW)


def _files(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def _put(vault: Path, name: str, text: str) -> None:
    (vault / "90-meta/templates").mkdir(parents=True, exist_ok=True)
    (vault / "90-meta/templates" / name).write_text(text, encoding="utf-8")


def test_list_seeds_three_starters(client, auth_headers, tmp_vault):
    r = client.get("/v1/templates", headers=auth_headers)
    assert r.status_code == 200
    items = r.json()["templates"]
    assert [t["name"] for t in items] == ["1-1", "Decision record", "Meeting notes"]
    assert all(t["valid"] for t in items)
    assert (tmp_vault / "90-meta/templates/one-on-one.md").is_file()


def test_functions_registry(client, auth_headers):
    data = client.get("/v1/templates/functions", headers=auth_headers).json()
    assert {f["name"] for f in data["filters"]} == {"format", "slug", "upper", "lower", "default"}
    assert any(f["owner"] == "person" and f["name"] == "link" for f in data["fields"])
    assert [k["name"] for k in data["queryKeys"]] == [
        "type", "context", "tag", "mentions", "status", "since", "sort", "limit",
    ]


def test_create_one_on_one(client, auth_headers, tmp_vault):
    client.get("/v1/templates", headers=auth_headers)  # seed
    r = client.post("/v1/templates/one-on-one/create", headers=auth_headers,
                    json={"answers": {"person": "30-cross-context/people/alex"}})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["path"] == "20-contexts/work/one-on-ones/2026-10-09-alex-1-1.md"
    assert body["title"] == "2026-10-09 Alex 1-1" and body["status"] == "applied" and body["etag"]
    text = (tmp_vault / body["path"]).read_text(encoding="utf-8")
    head, note_body = text[4:].split("---\n\n", 1)
    fm = yaml.safe_load(head)
    assert fm["attendees"] == ["[[30-cross-context/people/alex]]"]
    assert fm["fromTemplate"] == "one-on-one" and fm["created"] == "2026-10-09T14:30:00+02:00"
    assert note_body.startswith("# 1-1 with [[30-cross-context/people/alex]] — 9 Oct 2026\n")


def test_create_goes_through_write_path_as_user(client, auth_headers, tmp_vault, monkeypatch):
    from ghostbrain import vault_write

    seen = []
    real = vault_write.write_new

    def spy(rel_path, content, *, actor, reason="", max_attempts=100):
        seen.append(actor)
        return real(rel_path, content, actor=actor, reason=reason, max_attempts=max_attempts)

    monkeypatch.setattr("ghostbrain.templates.create.vault_write.write_new", spy)
    client.get("/v1/templates", headers=auth_headers)
    r = client.post("/v1/templates/meeting-notes/create", headers=auth_headers,
                    json={"answers": {"topic": "Planning"}})
    assert r.status_code == 201 and seen == ["user"]


def test_create_ignores_an_actor_in_the_body(client, auth_headers, tmp_vault, monkeypatch):
    from ghostbrain import vault_write

    seen = []
    real = vault_write.write_new

    def spy(rel_path, content, *, actor, reason="", max_attempts=100):
        seen.append(actor)
        return real(rel_path, content, actor=actor, reason=reason, max_attempts=max_attempts)

    monkeypatch.setattr("ghostbrain.templates.create.vault_write.write_new", spy)
    client.get("/v1/templates", headers=auth_headers)
    r = client.post("/v1/templates/meeting-notes/create", headers=auth_headers,
                    json={"answers": {"topic": "Planning"}, "actor": "agent"})
    assert r.status_code == 201 and seen == ["user"]


def test_create_twice_same_answers_gets_suffix(client, auth_headers, tmp_vault):
    client.get("/v1/templates", headers=auth_headers)
    paths = [
        client.post("/v1/templates/meeting-notes/create", headers=auth_headers,
                    json={"answers": {"topic": "Planning"}}).json()["path"]
        for _ in range(2)
    ]
    assert paths == ["20-contexts/work/meetings/2026-10-09-planning.md",
                     "20-contexts/work/meetings/2026-10-09-planning-2.md"]


def test_missing_required_answer_names_the_field(client, auth_headers, tmp_vault):
    client.get("/v1/templates", headers=auth_headers)
    r = client.post("/v1/templates/one-on-one/create", headers=auth_headers, json={"answers": {}})
    assert r.status_code == 422 and r.json()["detail"] == "person: an answer is required"


def test_non_string_answers_are_rejected(client, auth_headers, tmp_vault):
    r = client.post("/v1/templates/one-on-one/create", headers=auth_headers,
                    json={"answers": {"person": ["x"]}})
    assert r.status_code == 422


def test_control_characters_in_an_answer_are_422_and_write_nothing(client, auth_headers, tmp_vault):
    client.get("/v1/templates", headers=auth_headers)
    before = _files(tmp_vault)
    r = client.post("/v1/templates/meeting-notes/create", headers=auth_headers,
                    json={"answers": {"topic": "nul\x00here\x1b[31m"}})
    assert r.status_code == 422 and r.json()["detail"].startswith("topic: ")
    assert _files(tmp_vault) == before


@pytest.mark.parametrize("tid", ["nope", ".secret", "..secret", "UPPER"])
def test_unknown_or_unsafe_ids_are_404(client, auth_headers, tmp_vault, tid):
    for action in ("create", "render"):
        r = client.post(f"/v1/templates/{tid}/{action}", headers=auth_headers, json={"answers": {}})
        assert r.status_code == 404
        assert r.json()["detail"] == f"template not found: {tid}"


def test_encoded_traversal_id_is_404(client, auth_headers, tmp_vault):
    r = client.post("/v1/templates/..%2F..%2Froutingyaml/create", headers=auth_headers,
                    json={"answers": {}})
    # Starlette decodes %2F before routing, so this never matches {template_id}:
    # a plain routing 404.
    assert r.status_code == 404 and r.json()["detail"] == "Not Found"
    # Encoded dots without a slash do reach the route, and the id check refuses them.
    r = client.post("/v1/templates/%2E%2E/create", headers=auth_headers, json={"answers": {}})
    assert r.status_code == 404 and r.json()["detail"] == "template not found: .."


def test_create_with_broken_template_is_422(client, auth_headers, tmp_vault):
    _put(tmp_vault, "broken.md", "---\ntemplate:\n  name: [unclosed\n---\n")
    r = client.post("/v1/templates/broken/create", headers=auth_headers, json={"answers": {}})
    assert r.status_code == 422 and r.json()["detail"].startswith("template has errors: line ")


def test_escaping_folder_is_400_and_writes_nothing(client, auth_headers, tmp_vault):
    _put(tmp_vault, "evil.md", '---\ntemplate:\n  name: Evil\n  file:\n    folder: "../../outside"\n---\nx\n')
    before = _files(tmp_vault.parent)
    r = client.post("/v1/templates/evil/create", headers=auth_headers, json={"answers": {}})
    assert r.status_code == 400
    assert _files(tmp_vault.parent) == before


def test_render_returns_note_and_writes_nothing(client, auth_headers, tmp_vault):
    client.get("/v1/templates", headers=auth_headers)
    before = _files(tmp_vault)
    r = client.post("/v1/templates/meeting-notes/render", headers=auth_headers,
                    json={"answers": {"topic": "Planning", "context": "personal"}})
    assert r.status_code == 200
    data = r.json()
    assert data["path"] == "20-contexts/personal/meetings/2026-10-09-planning.md"
    assert data["folder"] == "20-contexts/personal/meetings"
    assert data["filename"] == "2026-10-09-planning.md"
    assert data["body"].startswith("# Planning — 9 Oct 2026\n")
    assert data["frontmatter"]["type"] == "meeting"
    assert _files(tmp_vault) == before
