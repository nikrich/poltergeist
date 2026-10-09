"""GET /v1/vault/backlinks — notes linking to a path."""
from __future__ import annotations

import os
from pathlib import Path

from ghostbrain.vault_index.links import LinkIndex, get_link_index


def _write(vault: Path, rel: str, text: str, mtime: int) -> None:
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    os.utime(p, (mtime, mtime))


def _get(client, auth_headers, path: str):
    get_link_index().refresh()
    return client.get("/v1/vault/backlinks", params={"path": path}, headers=auth_headers)


def test_backlinks_lists_sources_newest_first(client, auth_headers, tmp_vault):
    _write(tmp_vault, "20-contexts/work/alpha.md", "---\ntitle: Alpha\n---\n[[20-contexts/work/alpha]]", 10)
    _write(tmp_vault, "20-contexts/work/standup.md",
           "---\ntitle: Standup\nrelated:\n- '[[20-contexts/work/alpha]]'\n---\n"
           "notes\nask about [[20-contexts/work/alpha|Alpha]] owner\n", 200)
    _write(tmp_vault, "30-cross-context/people/alex.md",
           "---\ntitle: Alex\n---\nworks on [[alpha]]\n", 100)
    resp = _get(client, auth_headers, "20-contexts/work/alpha.md")
    assert resp.status_code == 200
    assert resp.json() == {
        "items": [
            {"path": "20-contexts/work/standup.md", "title": "Standup", "context": "work",
             "snippet": "ask about [[20-contexts/work/alpha|Alpha]] owner"},
            {"path": "30-cross-context/people/alex.md", "title": "Alex", "context": "",
             "snippet": "works on [[alpha]]"},
        ],
        "indexing": False,
    }


def test_frontmatter_only_link_has_empty_snippet(client, auth_headers, tmp_vault):
    _write(tmp_vault, "20-contexts/work/b.md", "b", 10)
    _write(tmp_vault, "20-contexts/work/a.md", "---\nparent: '[[20-contexts/work/b]]'\n---\nbody", 20)
    items = _get(client, auth_headers, "20-contexts/work/b.md").json()["items"]
    assert items == [{"path": "20-contexts/work/a.md", "title": "a", "context": "work", "snippet": ""}]


def test_path_without_md_suffix_is_accepted(client, auth_headers, tmp_vault):
    _write(tmp_vault, "20-contexts/work/b.md", "b", 10)
    _write(tmp_vault, "20-contexts/work/a.md", "[[20-contexts/work/b]]", 20)
    items = _get(client, auth_headers, "20-contexts/work/b").json()["items"]
    assert [i["path"] for i in items] == ["20-contexts/work/a.md"]


def test_unknown_note_returns_empty_list(client, auth_headers, tmp_vault):
    assert _get(client, auth_headers, "20-contexts/work/nope.md").json() == {"items": [], "indexing": False}


def test_bad_paths_are_rejected(client, auth_headers):
    for bad in ("/etc/passwd", "20-contexts/../../x.md", "a\x00b"):
        resp = client.get("/v1/vault/backlinks", params={"path": bad}, headers=auth_headers)
        assert resp.status_code == 400, bad


def test_limit_caps_rows(client, auth_headers, tmp_vault):
    _write(tmp_vault, "20-contexts/work/b.md", "b", 1)
    for i in range(4):
        _write(tmp_vault, f"20-contexts/work/s{i}.md", "[[20-contexts/work/b]]", 10 + i)
    get_link_index().refresh()
    resp = client.get("/v1/vault/backlinks", params={"path": "20-contexts/work/b.md", "limit": 2},
                      headers=auth_headers)
    assert [i["path"] for i in resp.json()["items"]] == ["20-contexts/work/s3.md", "20-contexts/work/s2.md"]


def test_backlinks_reports_indexing_while_cold(client, auth_headers, monkeypatch):
    monkeypatch.setattr(LinkIndex, "ensure_fresh", lambda self, wait=0.25: False)
    resp = client.get("/v1/vault/backlinks", params={"path": "20-contexts/work/b.md"}, headers=auth_headers)
    assert resp.json() == {"items": [], "indexing": True}
