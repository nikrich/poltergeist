"""GET /v1/vault/resolve: a wikilink target as written -> the note it opens."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from ghostbrain.vault_index.links import get_link_index


def _write(vault: Path, rel: str, text: str = "x") -> None:
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _resolve(client: TestClient, auth_headers, target: str):
    get_link_index().refresh()
    return client.get("/v1/vault/resolve", params={"target": target}, headers=auth_headers)


def test_bare_name_resolves_to_the_unique_note(client, auth_headers, tmp_vault):
    _write(tmp_vault, "20-contexts/work/Beta.md")
    assert _resolve(client, auth_headers, "beta").json() == {
        "path": "20-contexts/work/Beta.md", "exists": True, "indexing": False,
    }


def test_path_form_passes_through(client, auth_headers, tmp_vault):
    _write(tmp_vault, "20-contexts/work/Beta.md")
    assert _resolve(client, auth_headers, "20-contexts/work/Beta").json() == {
        "path": "20-contexts/work/Beta.md", "exists": True, "indexing": False,
    }


def test_unwritten_page_reports_missing(client, auth_headers, tmp_vault):
    assert _resolve(client, auth_headers, "Someday Idea").json() == {
        "path": "Someday Idea.md", "exists": False, "indexing": False,
    }


def test_ambiguous_bare_name_stays_unresolved(client, auth_headers, tmp_vault):
    _write(tmp_vault, "20-contexts/work/Beta.md")
    _write(tmp_vault, "20-contexts/personal/beta.md")
    assert _resolve(client, auth_headers, "Beta").json() == {
        "path": "Beta.md", "exists": False, "indexing": False,
    }


def test_rejects_attachments_and_escapes(client, auth_headers, tmp_vault):
    assert _resolve(client, auth_headers, "diagram.png").status_code == 400
    assert _resolve(client, auth_headers, "../outside").status_code == 400
    assert client.get("/v1/vault/resolve", params={"target": ""}, headers=auth_headers).status_code == 422
