"""Project registry: vault-synced JSON file CRUD."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ghostbrain.api.repo import projects


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    v = tmp_path / "vault"
    (v / "90-meta").mkdir(parents=True)
    (v / "20-contexts").mkdir()
    monkeypatch.setenv("VAULT_PATH", str(v))
    return v


def test_create_writes_registry_and_folder(vault: Path):
    p = projects.create_project("codeship", "Poltergeist", "second brain product")
    assert p == {
        "id": "codeship/poltergeist",
        "context": "codeship",
        "slug": "poltergeist",
        "name": "Poltergeist",
        "description": "second brain product",
        "archived": False,
        "created_at": p["created_at"],
    }
    assert (vault / "20-contexts/codeship/projects/poltergeist").is_dir()
    on_disk = json.loads((vault / "90-meta/projects.json").read_text())
    assert on_disk == [p]


def test_create_rejects_unknown_context_and_duplicate(vault: Path):
    with pytest.raises(projects.UnknownContext):
        projects.create_project("nope", "X")
    projects.create_project("personal", "Home Lab")
    with pytest.raises(projects.ProjectExists):
        projects.create_project("personal", "home-lab")  # same slug


def test_list_filters_archived_by_default(vault: Path):
    projects.create_project("personal", "A")
    projects.create_project("personal", "B")
    projects.update_project("personal", "b", archived=True)
    assert [p["slug"] for p in projects.list_projects()] == ["a"]
    assert [p["slug"] for p in projects.list_projects(include_archived=True)] == ["a", "b"]


def test_update_edits_and_returns_none_for_missing(vault: Path):
    projects.create_project("sanlam", "Capstone", "old")
    p = projects.update_project("sanlam", "capstone", name="Capstone v2", description="new")
    assert p["name"] == "Capstone v2" and p["description"] == "new"
    assert projects.update_project("sanlam", "missing", name="x") is None


def test_get_project_active_only_flag(vault: Path):
    projects.create_project("codeship", "Ship")
    assert projects.get_project("codeship", "ship")["name"] == "Ship"
    projects.update_project("codeship", "ship", archived=True)
    assert projects.get_project("codeship", "ship", active_only=True) is None
    assert projects.get_project("codeship", "ship") is not None


def test_corrupt_registry_reads_as_empty(vault: Path):
    (vault / "90-meta/projects.json").write_text("{nope")
    assert projects.list_projects() == []


def test_active_destinations_and_prompt_lines(vault: Path):
    projects.create_project("codeship", "Poltergeist", "the second brain")
    projects.create_project("codeship", "Archived One")
    projects.update_project("codeship", "archived-one", archived=True)
    dests = projects.active_destinations()
    assert "codeship/poltergeist" in dests
    assert "codeship/archived-one" not in dests
    assert {"sanlam", "codeship", "reducedrecipes", "personal"} <= set(dests)
    lines = projects.project_prompt_lines()
    assert lines == ["codeship/poltergeist — Poltergeist: the second brain"]
