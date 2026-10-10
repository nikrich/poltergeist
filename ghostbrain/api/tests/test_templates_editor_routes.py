"""/v1/templates editor routes (C3): lint, Test run, source read/save, new, query values."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ghostbrain.templates.starters import ONE_ON_ONE

NOW = datetime(2026, 10, 9, 14, 30, tzinfo=timezone(timedelta(hours=2)))
REL = "90-meta/templates/one-on-one.md"


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch):
    monkeypatch.setattr("ghostbrain.templates.env._now", lambda: NOW)


def _files(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def _seed(client, auth_headers) -> None:
    assert client.get("/v1/templates", headers=auth_headers).status_code == 200


def test_lint_returns_positioned_diagnostics(client, auth_headers):
    src = "---\ntemplate:\n  name: T\n---\n# {{persn}}\n"
    r = client.post("/v1/templates/lint", headers=auth_headers, json={"source": src})
    assert r.status_code == 200
    [d] = r.json()["diagnostics"]
    assert (d["line"], d["col"], d["severity"], d["code"]) == (5, 3, "warning", "unknown-name")


def test_lint_rejects_oversize_source(client, auth_headers):
    r = client.post("/v1/templates/lint", headers=auth_headers, json={"source": "x" * 256_001})
    assert r.status_code == 422


def test_test_run_renders_and_writes_nothing(client, auth_headers, tmp_vault):
    _seed(client, auth_headers)
    before = _files(tmp_vault)
    r = client.post("/v1/templates/render", headers=auth_headers,
                    json={"source": ONE_ON_ONE, "answers": {"person": "Alex"}, "id": "one-on-one",
                          "dry_run": True})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True and data["error"] is None
    assert data["wouldBeFiledAt"] == "20-contexts/work/one-on-ones/2026-10-09-alex-1-1.md"
    assert data["rendered"]["title"] == "2026-10-09 Alex 1-1"
    assert data["rendered"]["frontmatter"]["fromTemplate"] == "one-on-one"
    assert [p["id"] for p in data["prompts"]] == ["person", "focus"]
    assert _files(tmp_vault) == before


def test_test_run_of_broken_source_is_200_with_the_error(client, auth_headers):
    r = client.post("/v1/templates/render", headers=auth_headers,
                    json={"source": "---\ntemplate:\n  name: [x\n---\n", "answers": {}})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False and data["rendered"] is None
    assert data["error"].startswith("template has errors: line 4")


def test_test_run_requires_dry_run_true(client, auth_headers):
    r = client.post("/v1/templates/render", headers=auth_headers,
                    json={"source": ONE_ON_ONE, "answers": {}, "dry_run": False})
    assert r.status_code == 422


def test_source_round_trip_with_etag(client, auth_headers, tmp_vault):
    _seed(client, auth_headers)
    got = client.get("/v1/templates/one-on-one/source", headers=auth_headers)
    assert got.status_code == 200
    body = got.json()
    assert body["path"] == REL and body["source"] == ONE_ON_ONE and body["etag"]
    new = ONE_ON_ONE.replace("# 1-1 with", "# Weekly 1-1 with")
    r = client.patch("/v1/templates/one-on-one/source", headers={**auth_headers, "If-Match": body["etag"]},
                     json={"source": new})
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["status"] == "applied" and saved["etag"] != body["etag"]
    assert (tmp_vault / REL).read_text(encoding="utf-8") == new


def test_save_with_a_stale_etag_is_409_and_writes_nothing(client, auth_headers, tmp_vault):
    _seed(client, auth_headers)
    r = client.patch("/v1/templates/one-on-one/source",
                     headers={**auth_headers, "If-Match": "0000000000000000"}, json={"source": "x\n"})
    assert r.status_code == 409 and r.json()["currentEtag"]
    assert (tmp_vault / REL).read_text(encoding="utf-8") == ONE_ON_ONE


@pytest.mark.parametrize("tid", ["nope", "..secret", "UPPER"])
def test_unknown_template_source_is_404(client, auth_headers, tmp_vault, tid):
    _seed(client, auth_headers)
    assert client.get(f"/v1/templates/{tid}/source", headers=auth_headers).status_code == 404
    r = client.patch(f"/v1/templates/{tid}/source", headers=auth_headers, json={"source": "x"})
    assert r.status_code == 404


def test_new_blank_template_is_listed(client, auth_headers, tmp_vault):
    r = client.post("/v1/templates", headers=auth_headers, json={"name": "Weekly review"})
    assert r.status_code == 201, r.text
    assert r.json()["id"] == "weekly-review" and r.json()["status"] == "applied"
    names = [t["name"] for t in client.get("/v1/templates", headers=auth_headers).json()["templates"]]
    assert "Weekly review" in names and "1-1" in names


def test_new_template_rejects_a_bad_name(client, auth_headers):
    assert client.post("/v1/templates", headers=auth_headers, json={"name": ""}).status_code == 422
    r = client.post("/v1/templates", headers=auth_headers, json={"name": "a\nb"})
    assert r.status_code == 422


def test_query_values_shape(client, auth_headers):
    data = client.get("/v1/templates/query-values", headers=auth_headers).json()
    assert set(data) == {"types", "statuses", "indexing"}


def test_save_is_attributed_to_the_actor_header(client, auth_headers, tmp_vault):
    from ghostbrain.changes import log as changes

    _seed(client, auth_headers)
    etag = client.get("/v1/templates/one-on-one/source", headers=auth_headers).json()["etag"]
    r = client.patch("/v1/templates/one-on-one/source",
                     headers={**auth_headers, "If-Match": etag, "X-Poltergeist-Actor": "plugin:familiar"},
                     json={"source": ONE_ON_ONE + "\nplugin line\n"})
    assert r.status_code == 200, r.text
    r = client.patch("/v1/templates/one-on-one/source",
                     headers={**auth_headers, "If-Match": r.json()["etag"]},
                     json={"source": ONE_ON_ONE + "\nuser line\n"})
    assert r.status_code == 200, r.text
    # The change log records non-user writes only: the plugin save, not the user's.
    [logged] = [c for c in changes.list_changes() if c.rel_path == REL]
    assert (logged.actor, logged.op, logged.reason) == ("plugin:familiar", "modify", "edit template one-on-one")
