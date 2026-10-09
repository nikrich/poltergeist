"""GET /v1/vault/suggest — pages, tags, people over the link index."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from ghostbrain.vault_index.links import LinkIndex, get_link_index


def _note(vault: Path, rel: str, body: str = "", *, mtime: int, **meta) -> None:
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    fm = "".join(f"{k}: {v}\n" for k, v in meta.items())
    p.write_text(f"---\n{fm}---\n{body}" if meta else body, encoding="utf-8")
    os.utime(p, (mtime, mtime))


def _suggest(client: TestClient, auth_headers, **params) -> dict:
    get_link_index().refresh()
    resp = client.get("/v1/vault/suggest", params=params, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_pages_rank_prefix_then_substring_then_recency(client, auth_headers, tmp_vault):
    _note(tmp_vault, "20-contexts/work/alpha-plan.md", mtime=100, title="Alpha plan")
    _note(tmp_vault, "20-contexts/work/alpha-older.md", mtime=50, title="Alpha older")
    _note(tmp_vault, "20-contexts/work/review.md", mtime=200, title="The alpha review")
    _note(tmp_vault, "20-contexts/work/other.md", mtime=300, title="Unrelated")
    data = _suggest(client, auth_headers, kind="page", q="alp")
    assert data["indexing"] is False
    assert [i["label"] for i in data["items"]] == ["Alpha plan", "Alpha older", "The alpha review"]
    assert data["items"][0] == {
        "kind": "page",
        "label": "Alpha plan",
        "path": "20-contexts/work/alpha-plan.md",
        "context": "work",
        "detail": "20-contexts/work/alpha-plan",
        "count": None,
    }


def test_empty_query_returns_most_recent_first_and_respects_limit(client, auth_headers, tmp_vault):
    for i in range(5):
        _note(tmp_vault, f"20-contexts/work/n{i}.md", mtime=100 + i, title=f"Note {i}")
    data = _suggest(client, auth_headers, kind="page", q="", limit=3)
    assert [i["label"] for i in data["items"]] == ["Note 4", "Note 3", "Note 2"]


def test_tags_aggregate_frontmatter_and_hashtags(client, auth_headers, tmp_vault):
    _note(tmp_vault, "20-contexts/work/a.md", "plan the #roadmap", mtime=100, tags="[Roadmap, 'has space']")
    _note(tmp_vault, "20-contexts/work/b.md", "#roadmap again", mtime=300)
    _note(tmp_vault, "20-contexts/work/c.md", "#release-q4 and #read-later", mtime=200)
    data = _suggest(client, auth_headers, kind="tag", q="#r")
    # roadmap is newest (300) and counted once per note; the 200-tie breaks alphabetically
    assert [(i["label"], i["count"]) for i in data["items"]] == [
        ("roadmap", 2),
        ("read-later", 1),
        ("release-q4", 1),
    ]
    first = data["items"][0]
    assert first["kind"] == "tag" and first["path"] is None and first["detail"] == "2 notes"
    assert "has space" not in [i["label"] for i in _suggest(client, auth_headers, kind="tag", q="")["items"]]


def test_tag_table_follows_index_changes(client, auth_headers, tmp_vault):
    _note(tmp_vault, "20-contexts/work/a.md", "#alpha", mtime=100)
    assert [i["label"] for i in _suggest(client, auth_headers, kind="tag", q="")["items"]] == ["alpha"]
    _note(tmp_vault, "20-contexts/work/b.md", "#beta", mtime=200)
    assert [i["label"] for i in _suggest(client, auth_headers, kind="tag", q="")["items"]] == ["beta", "alpha"]


def test_persons_come_only_from_the_people_folder(client, auth_headers, tmp_vault):
    _note(tmp_vault, "30-cross-context/people/alex-smith.md", "", mtime=100)
    _note(tmp_vault, "30-cross-context/people/alexa.md", mtime=200, title="Alexa Jones")
    _note(tmp_vault, "20-contexts/work/alex-notes.md", mtime=300, title="Alex notes")
    data = _suggest(client, auth_headers, kind="person", q="@alex")
    assert [i["label"] for i in data["items"]] == ["Alexa Jones", "Alex Smith"]
    assert data["items"][1]["path"] == "30-cross-context/people/alex-smith.md"
    assert data["items"][1]["kind"] == "person"


def test_suggest_rejects_bad_params(client, auth_headers):
    assert client.get("/v1/vault/suggest", params={"kind": "file"}, headers=auth_headers).status_code == 422
    assert client.get(
        "/v1/vault/suggest", params={"kind": "page", "limit": 51}, headers=auth_headers
    ).status_code == 422
    assert client.get(
        "/v1/vault/suggest", params={"kind": "page", "q": "x" * 201}, headers=auth_headers
    ).status_code == 422


def test_suggest_reports_indexing_while_cold(client, auth_headers, monkeypatch):
    monkeypatch.setattr(LinkIndex, "ensure_fresh", lambda self, wait=0.25: False)
    resp = client.get("/v1/vault/suggest", params={"kind": "page", "q": "a"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "indexing": True}


def test_suggest_requires_auth(client):
    assert client.get("/v1/vault/suggest", params={"kind": "page"}).status_code == 401
