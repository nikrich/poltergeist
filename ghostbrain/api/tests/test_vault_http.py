"""GET etag + vault-write error → HTTP mapping (spec B1)."""
from __future__ import annotations

from fastapi import Depends
from fastapi.testclient import TestClient

from ghostbrain.api.main import create_app
from ghostbrain.api.repo.note import get_note
from ghostbrain.api.tests.conftest import TEST_TOKEN, write_note
from ghostbrain.api.vault_http import if_match
from ghostbrain.vault_write import (
    FileMissing,
    InvalidPath,
    MalformedNote,
    WriteConflict,
    compute_etag,
)

NOTE = "---\ntitle: Hello\n---\n\nbody text\n"


def test_get_note_returns_etag_of_file_bytes(tmp_vault):
    p = write_note(tmp_vault, "20-contexts/work/notes/n.md", NOTE)
    data = get_note("20-contexts/work/notes/n.md")
    assert data["etag"] == compute_etag(p.read_bytes())
    assert data["body"] == "body text"
    assert data["title"] == "Hello"


def test_get_note_bom_body_excludes_frontmatter(tmp_vault):
    p = tmp_vault / "20-contexts/work/notes/bom.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes("﻿---\ntitle: Bom\n---\n\nreal body\n".encode("utf-8"))
    data = get_note("20-contexts/work/notes/bom.md")
    assert data["body"] == "real body"
    assert data["frontmatter"] == {"title": "Bom"}


def test_get_note_crlf(tmp_vault):
    p = tmp_vault / "20-contexts/work/notes/crlf.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"---\r\ntitle: C\r\n---\r\n\r\nline one\r\nline two\r\n")
    data = get_note("20-contexts/work/notes/crlf.md")
    assert data["body"] == "line one\r\nline two"
    assert data["frontmatter"]["title"] == "C"


def test_get_route_includes_etag(client, tmp_vault, auth_headers):
    p = write_note(tmp_vault, "20-contexts/work/notes/n.md", NOTE)
    r = client.get("/v1/notes", params={"path": "20-contexts/work/notes/n.md"}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["etag"] == compute_etag(p.read_bytes())


def test_get_note_invalid_yaml_is_still_404(client, tmp_vault, auth_headers):
    write_note(tmp_vault, "20-contexts/work/notes/bad.md", "---\ntitle: [x\n---\n\nb\n")
    r = client.get("/v1/notes", params={"path": "20-contexts/work/notes/bad.md"}, headers=auth_headers)
    assert r.status_code == 404


def _app_raising(exc: Exception) -> TestClient:
    app = create_app(token=TEST_TOKEN)

    @app.get("/v1/__raise")
    def _raise() -> dict:
        raise exc

    @app.get("/v1/__ifmatch")
    def _ifmatch(base: str | None = Depends(if_match)) -> dict:
        return {"base": base}

    return TestClient(app)


def test_write_conflict_maps_to_409_with_current_etag(tmp_vault, tmp_state_dir, auth_headers):
    with _app_raising(WriteConflict("abcdefabcdefabcd")) as c:
        r = c.get("/v1/__raise", headers=auth_headers)
    assert r.status_code == 409
    assert r.json() == {
        "detail": "note changed since you read it — re-read and retry",
        "currentEtag": "abcdefabcdefabcd",
    }


def test_other_errors_map_to_404_422_400(tmp_vault, tmp_state_dir, auth_headers):
    for exc, status in ((FileMissing("x.md"), 404), (MalformedNote("bad"), 422), (InvalidPath("nope"), 400)):
        with _app_raising(exc) as c:
            assert c.get("/v1/__raise", headers=auth_headers).status_code == status


def test_if_match_dependency_normalizes(tmp_vault, tmp_state_dir, auth_headers):
    with _app_raising(RuntimeError("unused")) as c:
        assert c.get("/v1/__ifmatch", headers=auth_headers).json() == {"base": None}
        h = {**auth_headers, "If-Match": 'W/"0123456789abcdef"'}
        assert c.get("/v1/__ifmatch", headers=h).json() == {"base": "0123456789abcdef"}
