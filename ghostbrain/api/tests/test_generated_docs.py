from pathlib import Path

import pytest

from ghostbrain.api.repo import generated_docs as repo

HTML = "<!doctype html><html><head><style>body{color:red}</style></head><body><h1>Q3</h1></body></html>"


def test_writes_html_under_generated_docs(tmp_vault: Path):
    result = repo.write_doc("Q3 One-Pager", HTML)
    assert result["title"] == "Q3 One-Pager"
    assert result["path"].startswith("20-contexts/generated-docs/")
    assert result["path"].endswith(".html")
    f = tmp_vault / result["path"]
    assert f.exists()
    assert f.read_text(encoding="utf-8") == HTML  # stored as-is, no wrapping


def test_slug_from_title(tmp_vault: Path):
    result = repo.write_doc("Hiring Freeze: 2026!", HTML)
    name = result["path"].rsplit("/", 1)[-1]
    assert name.endswith("-hiring-freeze-2026.html")


def test_empty_title_rejected(tmp_vault: Path):
    with pytest.raises(ValueError):
        repo.write_doc("   ", HTML)


def test_empty_html_rejected(tmp_vault: Path):
    with pytest.raises(ValueError):
        repo.write_doc("t", "   ")


def test_oversize_html_rejected(tmp_vault: Path):
    big = "<p>" + "a" * (repo.MAX_HTML_BYTES) + "</p>"
    with pytest.raises(ValueError):
        repo.write_doc("t", big)


def test_write_endpoint_happy(client, auth_headers):
    res = client.post(
        "/v1/docs/write",
        json={"title": "Board Update", "html": HTML},
        headers=auth_headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["title"] == "Board Update"
    assert body["path"].startswith("20-contexts/generated-docs/")


def test_write_endpoint_empty_html_422(client, auth_headers):
    res = client.post(
        "/v1/docs/write", json={"title": "x", "html": ""}, headers=auth_headers
    )
    assert res.status_code == 422


def test_write_endpoint_oversize_400(client, auth_headers):
    big = "<p>" + "a" * (repo.MAX_HTML_BYTES) + "</p>"
    res = client.post(
        "/v1/docs/write", json={"title": "x", "html": big}, headers=auth_headers
    )
    assert res.status_code == 400
