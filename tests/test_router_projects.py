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
    monkeypatch.setenv("VAULT_PATH", str(v))
    return v


def test_build_router_schema_includes_destinations(vault):
    projects.create_project("codeship", "Poltergeist")
    schema = build_router_schema()
    enum = schema["properties"]["context"]["enum"]
    assert "codeship/poltergeist" in enum
    assert "needs_review" in enum
    assert "sanlam" in enum


def test_parse_destination_bare_context(vault):
    assert parse_destination("sanlam") == ("sanlam", None)
    assert parse_destination("needs_review") == ("needs_review", None)


def test_parse_destination_valid_project(vault):
    projects.create_project("codeship", "Poltergeist")
    assert parse_destination("codeship/poltergeist") == ("codeship", "poltergeist")


def test_parse_destination_unknown_or_archived_project_degrades(vault):
    projects.create_project("codeship", "Poltergeist")
    projects.update_project("codeship", "poltergeist", archived=True)
    assert parse_destination("codeship/poltergeist") == ("codeship", None)
    assert parse_destination("codeship/never-existed") == ("codeship", None)
    # garbage context in a pair degrades to needs_review
    assert parse_destination("nope/x") == ("needs_review", None)
