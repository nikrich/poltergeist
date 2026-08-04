"""Router destination enum + project parsing/validation."""
from __future__ import annotations

from pathlib import Path

import pytest

from ghostbrain.api.repo import projects
from ghostbrain.worker.router import build_router_schema, parse_destination


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    v = tmp_path / "vault"
    (v / "90-meta").mkdir(parents=True)
    (v / "90-meta" / "routing.yaml").write_text(
        "contexts:\n  - personal\n  - work\n  - consulting\n  - side-project\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("VAULT_PATH", str(v))
    return v


def test_build_router_schema_includes_destinations(vault):
    projects.create_project("consulting", "Poltergeist")
    schema = build_router_schema()
    enum = schema["properties"]["context"]["enum"]
    assert "consulting/poltergeist" in enum
    assert "needs_review" in enum
    assert "work" in enum


def test_parse_destination_bare_context(vault):
    assert parse_destination("work") == ("work", None)
    assert parse_destination("needs_review") == ("needs_review", None)


def test_parse_destination_valid_project(vault):
    projects.create_project("consulting", "Poltergeist")
    assert parse_destination("consulting/poltergeist") == ("consulting", "poltergeist")


def test_parse_destination_unknown_or_archived_project_degrades(vault):
    projects.create_project("consulting", "Poltergeist")
    projects.update_project("consulting", "poltergeist", archived=True)
    assert parse_destination("consulting/poltergeist") == ("consulting", None)
    assert parse_destination("consulting/never-existed") == ("consulting", None)
    # garbage context in a pair degrades to needs_review
    assert parse_destination("nope/x") == ("needs_review", None)
