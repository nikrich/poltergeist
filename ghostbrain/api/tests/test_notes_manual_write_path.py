"""Jot writers on the vault write path: golden parity with the legacy
frontmatter.dumps writers, hand-edit preservation, If-Match, actors."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import frontmatter
import pytest

from ghostbrain import vault_write
from ghostbrain.api.repo import notes_manual
from ghostbrain.api.repo.notes_manual import (
    extract_tags,
    mark_manual_review,
    move_jot,
    read_jot,
    set_frontmatter_fields,
    update_jot_body,
    write_inbox_jot,
)
from ghostbrain.vault_write import compute_etag

NOW = "2026-10-09T10:00:00+00:00"
WHEN = datetime(2026, 5, 14, 9, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _frozen(monkeypatch, tmp_vault):
    monkeypatch.setattr(notes_manual, "_now_iso", lambda: NOW)
    monkeypatch.setattr(vault_write.writer, "_now_iso", lambda: NOW)
    (tmp_vault / "00-inbox" / "raw" / "manual").mkdir(parents=True, exist_ok=True)


def _legacy(text: str, mutate) -> str:
    post = frontmatter.loads(text)
    mutate(post)
    return frontmatter.dumps(post) + "\n"


def test_write_inbox_jot_bytes_unchanged(tmp_vault):
    rec = write_inbox_jot("hello #a", captured_at=WHEN)
    text = (tmp_vault / rec["path"]).read_text()
    expected = frontmatter.dumps(frontmatter.Post(
        "hello #a", id=rec["id"], type="note", source="manual", context=None,
        created=WHEN.isoformat(), updated=WHEN.isoformat(), ingestedAt=NOW,
        routingStatus="pending", routingConfidence=None, routingMethod=None,
        routingReasoning=None, tags=["a"],
    )) + "\n"
    assert text == expected


def test_update_jot_body_golden(tmp_vault):
    rec = write_inbox_jot("original", captured_at=WHEN)
    p = tmp_vault / rec["path"]
    before = p.read_text()

    def legacy(post):
        post.content = "new body #x"
        post["updated"] = NOW
        post["tags"] = extract_tags("new body #x")

    res = update_jot_body(rec["id"], "new body #x")
    assert p.read_text() == _legacy(before, legacy)
    assert res["etag"] == compute_etag(p.read_bytes())
    assert res["updated"] == NOW


def test_mark_manual_review_golden(tmp_vault):
    rec = write_inbox_jot("ambiguous", captured_at=WHEN)
    p = tmp_vault / rec["path"]
    before = p.read_text()

    def legacy(post):
        post["routingStatus"] = "manual_review"
        post["routingReasoning"] = "too vague"
        post["updated"] = NOW

    mark_manual_review(rec["id"], "too vague")
    assert p.read_text() == _legacy(before, legacy)


def test_move_jot_without_project_golden(tmp_vault):
    rec = write_inbox_jot("file me", captured_at=WHEN)
    before = (tmp_vault / rec["path"]).read_text()

    def legacy(post):
        post["context"] = "work"
        post["routingStatus"] = "routed"
        post["routingConfidence"] = 0.9
        post["routingMethod"] = "llm"
        post["routingReasoning"] = "matches work"
        post["updated"] = NOW

    res = move_jot(rec["id"], to_context="work", confidence=0.9, method="llm", reasoning="matches work")
    assert not (tmp_vault / rec["path"]).exists()
    assert (tmp_vault / res["path"]).read_text() == _legacy(before, legacy)
    assert res["etag"] == compute_etag((tmp_vault / res["path"]).read_bytes())


def test_move_jot_with_project_appends_key_and_keeps_other_lines(tmp_vault):
    rec = write_inbox_jot("project jot", captured_at=WHEN)
    res = move_jot(rec["id"], to_context="work", to_project="alpha", confidence=1.0,
                   method="user", reasoning="manual re-route by user")
    text = (tmp_vault / res["path"]).read_text()
    assert res["path"] == f"20-contexts/work/projects/alpha/{rec['id']}.md"
    assert text.split("---\n")[1].endswith("project: alpha\n")
    assert frontmatter.loads(text)["project"] == "alpha"


def test_set_frontmatter_fields_appends_new_keys_and_keeps_existing_lines(tmp_vault):
    rec = write_inbox_jot("export me", captured_at=WHEN)
    p = tmp_vault / rec["path"]
    before_lines = p.read_text().split("---\n")[1].splitlines()
    set_frontmatter_fields(rec["id"], {"confluence_page_id": "123", "confluence_space": "ENG"})
    after_lines = p.read_text().split("---\n")[1].splitlines()
    assert after_lines[-2:] == ["confluence_page_id: '123'", "confluence_space: ENG"]
    unchanged = [l for l in before_lines if not l.startswith("updated:")]
    assert all(l in after_lines for l in unchanged)
    assert f"updated: '{NOW}'" in after_lines


def test_hand_edited_jot_keeps_comment_and_key_order(tmp_vault):
    jot_id = "manual-20260101T000000-hand"
    p = tmp_vault / "00-inbox/raw/manual" / f"{jot_id}.md"
    original = (
        "---\n"
        "# my jot\n"
        f"id: {jot_id}\n"
        "source: manual\n"
        'title: "Hand: written"\n'
        "updated: '2026-01-01T00:00:00+00:00'\n"
        "tags: []\n"
        "---\n"
        "\n"
        "hello\n"
    )
    p.write_text(original)
    update_jot_body(jot_id, "hello #y")
    assert p.read_text() == original.replace(
        "'2026-01-01T00:00:00+00:00'", f"'{NOW}'"
    ).replace("tags: []\n", "tags:\n- y\n").replace("\nhello\n", "\nhello #y\n")


def test_read_jot_returns_etag(tmp_vault):
    rec = write_inbox_jot("read me", captured_at=WHEN)
    assert read_jot(rec["id"])["etag"] == compute_etag((tmp_vault / rec["path"]).read_bytes())


def test_patch_jot_if_match(client, tmp_vault, auth_headers):
    rec = write_inbox_jot("original", captured_at=WHEN)
    etag = compute_etag((tmp_vault / rec["path"]).read_bytes())
    stale = client.patch(
        f"/v1/notes/{rec['id']}", json={"body": "x"},
        headers={**auth_headers, "If-Match": '"0000000000000000"'},
    )
    assert stale.status_code == 409
    ok = client.patch(
        f"/v1/notes/{rec['id']}", json={"body": "x"},
        headers={**auth_headers, "If-Match": f'"{etag}"'},
    )
    assert ok.status_code == 200
    assert ok.json()["etag"] == compute_etag((tmp_vault / ok.json()["path"]).read_bytes())


def test_route_response_has_etag(client, tmp_vault, auth_headers):
    rec = write_inbox_jot("route me", captured_at=WHEN)
    r = client.post(f"/v1/notes/{rec['id']}/route", json={"context": "work"}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["etag"] == compute_etag((tmp_vault / r.json()["path"]).read_bytes())


def test_actors_threaded(monkeypatch, tmp_vault):
    seen: list[tuple[str, str]] = []
    real = vault_write.write

    def spy(rel_path, **kw):
        seen.append((kw.get("op", "modify"), kw["actor"]))
        return real(rel_path, **kw)

    monkeypatch.setattr(vault_write, "write", spy)
    from ghostbrain.worker.router import RoutingDecision

    monkeypatch.setattr(
        notes_manual, "route_event",
        lambda event, **kw: RoutingDecision(context="work", confidence=0.9, reasoning="r",
                                            method="llm", secondary_contexts=[]),
    )
    rec = write_inbox_jot("auto", captured_at=WHEN)
    notes_manual.route_existing_jot(rec["id"])
    assert seen == [("create", "user"), ("move", "worker:jot-router")]


def test_extract_photo_uses_assistant_actor_and_returns_etag(monkeypatch, tmp_vault):
    rec = write_inbox_jot("shot", captured_at=WHEN)
    monkeypatch.setattr(notes_manual, "llm_run", lambda *a, **kw: SimpleNamespace(text="board text"))
    actors: list[str] = []
    real = vault_write.write
    monkeypatch.setattr(vault_write, "write", lambda rel, **kw: actors.append(kw["actor"]) or real(rel, **kw))
    out = notes_manual.extract_photo_into_jot(rec["id"], "90-meta/assets/jots/x.jpg")
    assert out["extracted"] is True
    assert actors == ["assistant"]
    assert out["etag"] == compute_etag((tmp_vault / out["path"]).read_bytes())
